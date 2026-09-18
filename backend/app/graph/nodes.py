"""Nodos del grafo - puerto fiel del workflow real COMPRE_PUES_SISTEMA_N8N.
Disparado por un COMENTARIO de TikTok Live (no por un WhatsApp entrante):
el backend NestJS (TikTokCommentService) manda {username, comment, storeName}
a este webhook, exactamente como antes se lo mandaba a n8n.

Cada tienda tiene su propio proveedor/API key de IA y su propio prompt
(comportamiento del agente), resueltos por store_id en cada mensaje - no hay
un solo agente compartido entre tiendas."""

import logging

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from app.constants import CAPTURE_LABEL
from app.db import LiveshopSessionLocal
from app.graph.state import AgentState
from app.mysql_tools import find_store_by_name, find_products, find_tiktok_user
from app.settings_store import get_store_ai_config, StoreAiSettings
from app import evolution_client, chatwoot_client

logger = logging.getLogger(__name__)

PROVIDER_BASE_URLS = {
    "openai": None,  # default de langchain_openai
    "deepseek": "https://api.deepseek.com",
}

PROVIDER_MODELS = {
    "openai": "gpt-4o-mini",
    "deepseek": "deepseek-chat",
}

SIN_CLASIFICAR = "sin_clasificar"

# USD por 1M tokens (input, output) - aproximado, para poder ver de un
# vistazo cuanto esta costando el agente del live, no una factura exacta.
PRICING_PER_1M = {
    "openai": (0.15, 0.60),
    "deepseek": (0.30, 1.20),
}


def _extract_usage(result) -> tuple[int, int]:
    """Saca (prompt_tokens, completion_tokens) de la respuesta del LLM - la
    forma varia segun el proveedor/version de langchain, se intenta en orden
    de mas a menos confiable en vez de asumir una sola estructura."""
    usage = getattr(result, "usage_metadata", None)
    if usage:
        return usage.get("input_tokens", 0), usage.get("output_tokens", 0)
    token_usage = (getattr(result, "response_metadata", None) or {}).get("token_usage") or {}
    return token_usage.get("prompt_tokens", 0), token_usage.get("completion_tokens", 0)


def _estimate_cost(provider: str | None, prompt_tokens: int, completion_tokens: int) -> float:
    price_in, price_out = PRICING_PER_1M.get(provider or "", (0.0, 0.0))
    return round((prompt_tokens * price_in + completion_tokens * price_out) / 1_000_000, 6)


def _build_llm(cfg: StoreAiSettings) -> ChatOpenAI:
    # Se crea por llamada (no cacheado) para que cambiar proveedor/key desde
    # el panel de esa tienda aplique al instante, sin reiniciar el backend.
    return ChatOpenAI(
        model=PROVIDER_MODELS.get(cfg.ai_provider, PROVIDER_MODELS["openai"]),
        api_key=cfg.ai_api_key,
        base_url=PROVIDER_BASE_URLS.get(cfg.ai_provider),
        temperature=0.3,
    )


def load_store(state: AgentState) -> AgentState:
    """Puerto del nodo 'find store': busca por storeName, no por id - asi
    llega en el payload real del backend."""
    db = LiveshopSessionLocal()
    try:
        store = find_store_by_name(db, state["store_name"])
    finally:
        db.close()
    return {**state, "store": store, "store_id": store["id"] if store else None}


def find_user(state: AgentState) -> AgentState:
    """Puerto del nodo 'find_user': busca por username de TikTok. Si no hay
    fila, el comentario es de alguien no registrado - no hay telefono
    conocido para responder por WhatsApp."""
    db = LiveshopSessionLocal()
    try:
        user = find_tiktok_user(db, state["username"])
    finally:
        db.close()
    return {**state, "tiktok_user": user}


def _log_comment_ai(state: AgentState, ai_provider: str | None, intent: str, label_text: str,
                     skip_response: bool, success: bool, error: str | None = None,
                     prompt_tokens: int = 0, completion_tokens: int = 0) -> int | None:
    """Deja registro de cada comentario que pasa por el agente - alimenta el
    panel interno de monitoreo (Uso de IA) para que Camilo vea que esta
    decidiendo la IA (y cuanto esta costando) sin tener que mirar logs de
    servidor. Devuelve el id de la fila para que compose_response le sume su
    propio consumo despues (una sola fila por comentario, no dos)."""
    from app.db import AiSessionLocal
    from app.models import CommentAiLog

    db = AiSessionLocal()
    try:
        log = CommentAiLog(
            store_id=state.get("store_id"),
            store_name=(state.get("store") or {}).get("name", state.get("store_name")),
            username=state.get("username", ""),
            comment=state.get("comment", ""),
            ai_provider=ai_provider,
            intent=intent,
            label_text=label_text,
            skip_response=1 if skip_response else 0,
            success=1 if success else 0,
            error_message=error,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost_usd=_estimate_cost(ai_provider, prompt_tokens, completion_tokens),
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        return log.id
    except Exception:
        logger.exception("No se pudo guardar el log de uso de IA (store_id=%s)", state.get("store_id"))
        return None
    finally:
        db.close()


def _add_usage_to_log(log_id: int | None, ai_provider: str | None,
                       prompt_tokens: int, completion_tokens: int) -> None:
    """Le suma el consumo de compose_response a la fila que ya creo
    classify_intent para este mismo comentario."""
    if not log_id:
        return
    from app.db import AiSessionLocal
    from app.models import CommentAiLog

    db = AiSessionLocal()
    try:
        log = db.query(CommentAiLog).filter_by(id=log_id).first()
        if log:
            log.prompt_tokens = (log.prompt_tokens or 0) + prompt_tokens
            log.completion_tokens = (log.completion_tokens or 0) + completion_tokens
            log.estimated_cost_usd = (log.estimated_cost_usd or 0) + _estimate_cost(
                ai_provider, prompt_tokens, completion_tokens
            )
            db.commit()
    except Exception:
        logger.exception("No se pudo sumar el consumo de compose_response al log %s", log_id)
    finally:
        db.close()


def classify_intent(state: AgentState) -> AgentState:
    """Ya NO clasifica en 3 categorias fijas (venta/queja/soporte) - usa las
    etiquetas LIBRES que la propia tienda haya creado (pestaña "Etiquetas",
    "+ Agregar"). Se clasifica a CUALQUIERA que comente, tenga cuenta o no -
    tener cuenta (telefono conocido) solo decide si se le puede responder por
    WhatsApp (ver send_reply), no si se clasifica. Si la tienda todavia no
    creo ninguna etiqueta, o ninguna encaja con el comentario, cae en
    "Nuevo contacto" - y si no hay NINGUNA etiqueta creada todavia, tampoco se
    le responde (skip_response) hasta que la tienda configure sus categorias."""
    cfg = get_store_ai_config(state["store_id"])
    custom_labels = [
        item["title"] for item in cfg.extra_labels
        if item.get("title") and item["title"] != CAPTURE_LABEL
    ]
    no_registrado_text = cfg.labels.get("no_registrado", "Nuevo contacto")

    if not custom_labels:
        _log_comment_ai(state, cfg.ai_provider, SIN_CLASIFICAR, no_registrado_text, True, True)
        return {**state, "intent": SIN_CLASIFICAR, "label_text": no_registrado_text, "skip_response": True}

    options = ", ".join(custom_labels)
    prompt = (
        "Clasifica el siguiente comentario de un cliente en el live de TikTok de una "
        f"tienda, en UNA de estas categorias exactas: {options}, {SIN_CLASIFICAR}. "
        f"Usa '{SIN_CLASIFICAR}' solo si el comentario no encaja claramente en ninguna. "
        "Responde solo con el nombre exacto de la categoria elegida, tal cual esta escrito arriba."
    )
    try:
        llm = _build_llm(cfg)
        result = llm.invoke([SystemMessage(content=prompt), HumanMessage(content=state["comment"])])
        chosen = result.content.strip()
        prompt_tokens, completion_tokens = _extract_usage(result)
    except Exception as e:
        # Si la IA de esta tienda falla (key invalida, proveedor caido, etc.)
        # el comentario igual debe quedar visible como "sin_clasificar" en vez
        # de tumbar todo el webhook y perder el comentario por completo.
        logger.exception("classify_intent fallo para store_id=%s", state.get("store_id"))
        _log_comment_ai(state, cfg.ai_provider, SIN_CLASIFICAR, no_registrado_text, False, False, str(e))
        return {**state, "intent": SIN_CLASIFICAR, "label_text": no_registrado_text, "skip_response": False}

    matched = next((t for t in custom_labels if t.lower() == chosen.lower()), None)
    if matched:
        log_id = _log_comment_ai(state, cfg.ai_provider, matched, matched, False, True,
                                  prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
        return {**state, "intent": matched, "label_text": matched, "skip_response": False, "ai_log_id": log_id}
    log_id = _log_comment_ai(state, cfg.ai_provider, SIN_CLASIFICAR, no_registrado_text, False, True,
                              prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    return {**state, "intent": SIN_CLASIFICAR, "label_text": no_registrado_text, "skip_response": False, "ai_log_id": log_id}


def search_products(state: AgentState) -> AgentState:
    if state["intent"] in ("no_registrado", SIN_CLASIFICAR) or not state.get("store_id"):
        return {**state, "products": []}
    db = LiveshopSessionLocal()
    try:
        products = find_products(db, state["store_id"], state["comment"])
    finally:
        db.close()
    return {**state, "products": products}


def route_to_chatwoot(state: AgentState) -> AgentState:
    """Crea/encuentra el contacto y la conversacion en la cuenta de Chatwoot
    PROPIA de esta tienda, y le pone la etiqueta configurada para la intencion
    detectada. No bloquea la respuesta al cliente si Chatwoot falla."""
    if not state.get("store_id"):
        return state
    cfg = get_store_ai_config(state["store_id"])
    if not cfg.chatwoot_account_id or not cfg.chatwoot_inbox_id:
        return state  # tienda sin Chatwoot aprovisionado todavia

    user = state.get("tiktok_user")
    phone = user["phone"] if user and user.get("phone") else f"tiktok:{state['username']}"

    try:
        contact = chatwoot_client.find_contact_by_phone(state["store_id"], phone)
        if not contact:
            contact = chatwoot_client.create_contact(state["store_id"], phone, name=state["username"])
        contact_id = contact["id"]

        conversation = chatwoot_client.find_open_conversation(state["store_id"], contact_id, cfg.chatwoot_inbox_id)
        if not conversation:
            conversation = chatwoot_client.create_conversation(state["store_id"], contact_id, cfg.chatwoot_inbox_id)

        label = state.get("label_text") or state["intent"]
        chatwoot_client.set_labels(state["store_id"], conversation["id"], [label])

        if state.get("conversation_id"):
            from app.db import AiSessionLocal
            from app.models import Conversation

            db = AiSessionLocal()
            try:
                local_conv = db.query(Conversation).filter_by(id=state["conversation_id"]).first()
                if local_conv:
                    local_conv.chatwoot_conversation_id = conversation["id"]
                    # Se guarda el texto real (no el intent interno) - asi
                    # "sin_clasificar" y "no_registrado" caen bajo la MISMA
                    # columna "Nuevo contacto" en el panel, en vez de dos.
                    local_conv.current_label = label
                    db.commit()
            finally:
                db.close()
    except Exception:
        logger.exception("route_to_chatwoot fallo para store_id=%s username=%s", state.get("store_id"), state.get("username"))
    return state


def compose_response(state: AgentState) -> AgentState:
    """Llama al LLM con el system_prompt PROPIO de la tienda - es lo que hace
    que cada tienda tenga su propio 'comportamiento' de agente."""
    if not state.get("tiktok_user"):
        # Sin cuenta registrada no hay telefono conocido - no se le puede
        # escribir por WhatsApp. Se sigue clasificando (para la etiqueta en
        # Chatwoot), pero NO se gasta una llamada de IA para componer una
        # respuesta que nunca se va a poder enviar - queda sin respuesta,
        # solo se ve el comentario que la persona escribio.
        return {**state, "response_text": ""}

    if state.get("skip_response"):
        # La tienda todavia no creo ninguna etiqueta propia - el comentario
        # queda anotado como "sin_clasificar" en Chatwoot, pero no se le
        # responde nada al cliente hasta que la tienda configure categorias.
        return {**state, "response_text": ""}

    cfg = get_store_ai_config(state["store_id"])
    llm = _build_llm(cfg)

    store_name = (state.get("store") or {}).get("name", state.get("store_name", "la tienda"))
    user = state.get("tiktok_user") or {}
    products = state.get("products") or []
    context_lines = [
        f"Tienda: {store_name}",
        f"Cliente: {user.get('name') or state['username']}",
        f"Intencion detectada: {state['intent']}",
    ]
    if products:
        context_lines.append("Productos encontrados:")
        context_lines += [f"- {p['name']}: ${p['price']} (stock: {p['stock']})" for p in products]
    elif state["intent"] not in ("no_registrado", SIN_CLASIFICAR):
        context_lines.append("No se encontraron productos que coincidan con el comentario.")

    try:
        result = llm.invoke(
            [
                SystemMessage(content=cfg.system_prompt),
                HumanMessage(
                    content=(
                        f"Contexto:\n{chr(10).join(context_lines)}\n\n"
                        f"Comentario del cliente en el live: {state['comment']}"
                    )
                ),
            ]
        )
    except Exception:
        # Igual que en classify_intent - un fallo de la IA aca no debe tumbar
        # el webhook completo (la etiqueta en Chatwoot ya quedo puesta antes).
        logger.exception("compose_response fallo para store_id=%s", state.get("store_id"))
        return {**state, "response_text": ""}

    prompt_tokens, completion_tokens = _extract_usage(result)
    _add_usage_to_log(state.get("ai_log_id"), cfg.ai_provider, prompt_tokens, completion_tokens)
    return {**state, "response_text": result.content.strip()}


def send_reply(state: AgentState) -> AgentState:
    """Solo se manda WhatsApp si el usuario esta registrado (hay telefono
    conocido) y la tienda tiene una instancia de WhatsApp conectada - igual
    que en n8n, un no-registrado solo queda anotado en Chatwoot."""
    user = state.get("tiktok_user")
    if not user or not user.get("phone") or not state.get("instance_name") or not state.get("response_text"):
        return state
    evolution_client.send_text(state["instance_name"], user["phone"], state["response_text"])
    return state
