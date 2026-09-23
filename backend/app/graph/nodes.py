"""Nodos del grafo - puerto fiel del workflow real COMPRE_PUES_SISTEMA_N8N.
Disparado por un COMENTARIO de TikTok Live (no por un WhatsApp entrante):
el backend NestJS (TikTokCommentService) manda {username, comment, storeName}
a este webhook, exactamente como antes se lo mandaba a n8n.

Cada tienda tiene su propio proveedor/API key de IA y su propio prompt
(comportamiento del agente), resueltos por store_id en cada mensaje - no hay
un solo agente compartido entre tiendas."""

import logging
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import httpx
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from app.constants import INTERNAL_LABELS
from app.db import LiveshopSessionLocal
from app.graph.state import AgentState
from app.config import settings
from app.mysql_tools import find_store_by_name, find_products, find_tiktok_user, list_store_products
from app import room_link, sales
from app.labels import apply_classified_label
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
    "jev": (0.042, 0.0),  # TypeSafe: la salida no se cobra
}

# Por debajo de esto la respuesta de Jev se trata como "no encaja" (valor
# sugerido por la doc de TypeSafe para no rutear automaticamente).
JEV_MIN_CONFIDENCE = 0.3


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


def _classifier_cfg(cfg: StoreAiSettings) -> StoreAiSettings:
    """La clasificacion de comentarios va SIEMPRE con DeepSeek: la key propia
    de la tienda si ya usa DeepSeek, si no la key global de clasificacion.
    Sin ninguna de las dos se queda con el proveedor de la tienda (mejor
    clasificar con otro modelo que dejar todo sin clasificar)."""
    if cfg.ai_provider == "deepseek" and cfg.ai_api_key:
        return cfg
    if settings.classifier_deepseek_api_key:
        return replace(cfg, ai_provider="deepseek", ai_api_key=settings.classifier_deepseek_api_key)
    logger.warning("Sin key de DeepSeek para clasificar (store_id=%s), se usa %s", cfg.store_id, cfg.ai_provider)
    return cfg


def classification_prompt(custom_labels: list[str]) -> str:
    """Las etiquetas las inventa cada tienda (pueden no existir "venta" o
    "queja"), asi que la guia describe INTENCIONES tipicas de un live de
    ventas y el modelo las cruza con el significado del nombre de cada
    etiqueta. Sin esta guia confundia preguntas de compra con quejas y
    mandaba a sin_clasificar preguntas por tallas/medidas."""
    options = "\n".join(f"- {label}" for label in custom_labels)
    return (
        "Clasificas comentarios que escriben los clientes durante el live de TikTok de una "
        "tienda que vende productos en vivo (casi siempre ropa y accesorios).\n\n"
        f"Etiquetas que creo la tienda:\n{options}\n- {SIN_CLASIFICAR}\n\n"
        "Elige la etiqueta que mejor describa la INTENCION del comentario, segun lo que "
        "significa el nombre de cada etiqueta. Guia:\n"
        "- Interes de compra (etiqueta de venta/compra/pedido/interes si existe): preguntas por "
        "precio, moneda, tallas, medidas, largo, color, material, stock, al por mayor, si tienen "
        "cierto producto; pedidos como \"lo quiero\", \"mio\", \"yo\", un codigo o numero de "
        "producto; y elogios a un producto (\"divina esa blusa\").\n"
        "- Queja/reclamo: SOLO si el cliente reporta un problema real (pedido que no llego, "
        "producto danado o equivocado, cobro mal, mala atencion). Una pregunta NO es una queja.\n"
        "- Soporte/atencion/dudas: como comprar o pagar, envios, ubicacion de la tienda, "
        "horarios, estado de un pedido.\n"
        f"- {SIN_CLASIFICAR}: saludos, emojis, risas, charla sin relacion con la tienda o "
        "comentarios sin una intencion clara. Ante una pregunta por un producto, NO uses "
        f"{SIN_CLASIFICAR}.\n\n"
        "Responde SOLO con el nombre exacto de una etiqueta de la lista, sin nada mas."
    )


def _classify_with_llm(cfg: StoreAiSettings, comment: str, custom_labels: list[str]) -> tuple[str, int, int]:
    prompt = classification_prompt(custom_labels)
    llm = _build_llm(cfg).bind(temperature=0)
    result = llm.invoke([SystemMessage(content=prompt), HumanMessage(content=comment)])
    prompt_tokens, completion_tokens = _extract_usage(result)
    return result.content.strip(), prompt_tokens, completion_tokens


def _classify_with_jev(comment: str, custom_labels: list[str]) -> tuple[str, int, int]:
    """Clasifica con Jev (TypeSafe AI): una pregunta Choice tipada cuyas
    opciones son las etiquetas de la tienda - siempre devuelve una de ellas
    (nunca texto libre que haya que emparejar) mas su confianza."""
    criteria: dict[str, str | None] = {label: None for label in custom_labels}
    criteria[SIN_CLASIFICAR] = "El comentario no encaja claramente en ninguna de las otras categorias"
    resp = httpx.post(
        settings.typesafe_api_url,
        headers={"Authorization": f"Bearer {settings.typesafe_api_key}"},
        json={
            "model": settings.typesafe_model,
            "state": comment,
            "questions": {
                "categoria": {
                    "type": "choice",
                    "instructions": "Categoria de este comentario de un cliente en el live de TikTok de una tienda",
                    "criteria": criteria,
                },
            },
        },
        timeout=5.0,
    )
    resp.raise_for_status()
    data = resp.json()
    answer = data["answers"]["categoria"]
    usage = data.get("usage") or {}
    chosen = answer["choice"]
    if (answer.get("confidence") or 0) < JEV_MIN_CONFIDENCE:
        chosen = SIN_CLASIFICAR
    return chosen, usage.get("input_tokens", 0), usage.get("output_tokens", 0)


def classify_intent(state: AgentState) -> AgentState:
    """Ya NO clasifica en 3 categorias fijas (venta/queja/soporte) - usa las
    etiquetas LIBRES que la propia tienda haya creado (pestaña "Etiquetas",
    "+ Agregar"). Se clasifica a CUALQUIERA que comente, tenga cuenta o no -
    tener cuenta (telefono conocido) solo decide si se le puede responder por
    WhatsApp (ver send_reply), no si se clasifica. Si la tienda todavia no
    creo ninguna etiqueta, o ninguna encaja con el comentario, cae en
    "Nuevo contacto" - y si no hay NINGUNA etiqueta creada todavia, tampoco se
    le responde (skip_response) hasta que la tienda configure sus categorias."""
    cfg = _classifier_cfg(get_store_ai_config(state["store_id"]))
    custom_labels = [
        item["title"] for item in cfg.extra_labels
        if item.get("title") and item["title"] not in INTERNAL_LABELS
    ]
    no_registrado_text = cfg.labels.get("no_registrado", "Nuevo contacto")

    if not custom_labels:
        _log_comment_ai(state, cfg.ai_provider, SIN_CLASIFICAR, no_registrado_text, True, True)
        return {**state, "intent": SIN_CLASIFICAR, "label_text": no_registrado_text, "skip_response": True}

    chosen = None
    provider = cfg.ai_provider
    if settings.comment_classifier == "jev" and settings.typesafe_api_key:
        try:
            chosen, prompt_tokens, completion_tokens = _classify_with_jev(state["comment"], custom_labels)
            provider = "jev"
        except Exception:
            # Jev caido/limitado: no se pierde el comentario, lo clasifica el
            # LLM de la tienda como antes.
            logger.exception("Jev fallo para store_id=%s, se usa el LLM de la tienda", state.get("store_id"))

    if chosen is None:
        try:
            chosen, prompt_tokens, completion_tokens = _classify_with_llm(cfg, state["comment"], custom_labels)
        except Exception as e:
            # Si la IA de esta tienda falla (key invalida, proveedor caido, etc.)
            # el comentario igual debe quedar visible como "sin_clasificar" en vez
            # de tumbar todo el webhook y perder el comentario por completo.
            logger.exception("classify_intent fallo para store_id=%s", state.get("store_id"))
            _log_comment_ai(state, cfg.ai_provider, SIN_CLASIFICAR, no_registrado_text, False, False, str(e))
            return {**state, "intent": SIN_CLASIFICAR, "label_text": no_registrado_text, "skip_response": False}

    matched = next((t for t in custom_labels if t.lower() == chosen.lower()), None)
    if matched:
        log_id = _log_comment_ai(state, provider, matched, matched, False, True,
                                  prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
        return {**state, "intent": matched, "label_text": matched, "skip_response": False, "ai_log_id": log_id}
    log_id = _log_comment_ai(state, provider, SIN_CLASIFICAR, no_registrado_text, False, True,
                              prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    return {**state, "intent": SIN_CLASIFICAR, "label_text": no_registrado_text, "skip_response": False, "ai_log_id": log_id}


# Ventana en la que NO se repite el mismo link al mismo cliente (la gente
# comenta "mio" varias veces seguidas).
OFFER_DEDUPE_MINUTES = 10


def _recently_offered(conversation_id: int | None, product_id: int) -> bool:
    if not conversation_id:
        return False
    from app.db import AiSessionLocal
    from app.models import Message

    since = datetime.now(timezone.utc) - timedelta(minutes=OFFER_DEDUPE_MINUTES)
    db = AiSessionLocal()
    try:
        recent = (
            db.query(Message.body)
            .filter(
                Message.conversation_id == conversation_id,
                Message.direction == "out",
                Message.created_at >= since,
            )
            .limit(50)
            .all()
        )
        # Sirve para el link de pago (?productId=) y para el de la sala (?p=)
        return any(sales.mentions_offer(body, product_id) for (body,) in recent)
    finally:
        db.close()


def search_products(state: AgentState) -> AgentState:
    """Dos cosas: (1) deteccion DETERMINISTA del codigo de un producto en el
    comentario -> oferta de venta automatica (imagen + link de pago), y (2) el
    contexto de productos para el LLM, como antes.

    La oferta solo se arma si el cliente esta registrado (hay telefono, igual
    que en n8n) y el producto esta disponible; y no se repite si ya se le
    mando ese mismo link hace poco."""
    if not state.get("store_id"):
        return {**state, "products": [], "offer": None, "offer_suppressed": False}

    db = LiveshopSessionLocal()
    try:
        catalog = list_store_products(db, state["store_id"])
        by_code = sales.match_product_by_code(catalog, state["comment"])
        products = [by_code] if by_code else (
            []
            if state["intent"] in ("no_registrado", SIN_CLASIFICAR)
            else find_products(db, state["store_id"], state["comment"])
        )
    finally:
        db.close()

    offer, suppressed = None, False
    user = state.get("tiktok_user")
    if by_code and user and user.get("phone") and user.get("id") and sales.is_available(by_code):
        if _recently_offered(state.get("conversation_id"), by_code["id"]):
            suppressed = True
        else:
            store_name = (state.get("store") or {}).get("name", state["store_name"])
            customer = user.get("name") or state["username"]
            url = sales.build_checkout_url(settings.liveshop_public_url, store_name, by_code["id"], user["id"])
            caption = sales.build_offer_caption(customer, by_code["name"], by_code["price"], url)
            # Con el interruptor encendido la oferta lleva el link de la sala; si
            # no se puede obtener, sale el link de pago de siempre.
            room_url = room_link.fetch_room_link(user["id"], by_code["id"])
            if room_url:
                url = room_url
                caption = sales.build_room_offer_caption(customer, by_code["name"], by_code["price"], room_url)
            offer = {
                "product_id": by_code["id"],
                "image_url": by_code.get("imageUrl"),
                "checkout_url": url,
                "caption": caption,
            }
    return {**state, "products": products, "offer": offer, "offer_suppressed": suppressed}


def _label_locally(state: AgentState, fallback_label: str) -> str | None:
    """Etiqueta la conversacion en NUESTRA BD (la del tablero de Prospeccion)
    y devuelve la etiqueta con la que quedo - Chatwoot, si la tienda lo tiene,
    solo refleja esta misma etiqueta."""
    label = state.get("label_text") or state.get("intent")
    if not state.get("conversation_id"):
        return label
    from app.db import AiSessionLocal
    from app.models import Conversation

    db = AiSessionLocal()
    try:
        conversation = db.query(Conversation).filter_by(id=state["conversation_id"]).first()
        if apply_classified_label(conversation, label, fallback_label):
            db.commit()
        return (conversation.current_label if conversation else None) or label
    except Exception:
        logger.exception("No se pudo etiquetar la conversacion %s", state.get("conversation_id"))
        return label
    finally:
        db.close()


def route_to_chatwoot(state: AgentState) -> AgentState:
    """Crea/encuentra el contacto y la conversacion en la cuenta de Chatwoot
    PROPIA de esta tienda, y le pone la etiqueta configurada para la intencion
    detectada. No bloquea la respuesta al cliente si Chatwoot falla."""
    if not state.get("store_id"):
        return state

    # La etiqueta local va SIEMPRE y es la fuente de verdad (no depende de
    # Chatwoot ni de WhatsApp): el tablero de Prospeccion agrupa por ella.
    cfg = get_store_ai_config(state["store_id"])
    label = _label_locally(state, cfg.labels.get("no_registrado", "Nuevo contacto"))

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

        chatwoot_client.set_labels(state["store_id"], conversation["id"], [label])

        if state.get("conversation_id"):
            from app.db import AiSessionLocal
            from app.models import Conversation

            db = AiSessionLocal()
            try:
                local_conv = db.query(Conversation).filter_by(id=state["conversation_id"]).first()
                if local_conv:
                    local_conv.chatwoot_conversation_id = conversation["id"]
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

    if state.get("offer_suppressed"):
        # Ya se le mando este link hace poco - no se repite ni se le
        # contesta otra cosa.
        return {**state, "response_text": ""}

    if state.get("offer"):
        # Venta por codigo: el mensaje es la propia oferta (imagen + link),
        # no hace falta llamar al LLM. Va antes de skip_response: vender no
        # depende de que la tienda haya configurado etiquetas.
        return {**state, "response_text": state["offer"]["caption"]}

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

    offer = state.get("offer")
    if offer and offer.get("image_url"):
        try:
            evolution_client.send_media(
                state["instance_name"], user["phone"], offer["image_url"], "image", offer["caption"]
            )
            return state
        except httpx.HTTPError:
            # Si la imagen no se puede enviar (URL rota, etc.) igual sale el
            # link de pago como texto - lo importante es que pueda comprar.
            logger.exception("send_media fallo para store_id=%s, se envia solo el texto", state.get("store_id"))

    evolution_client.send_text(state["instance_name"], user["phone"], state["response_text"])
    return state
