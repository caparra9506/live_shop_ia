import hmac

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.cart_saved import CartSavedDeps, deliver
from app.room_agent import RoomAgentDeps, answer

router = APIRouter(prefix="/webhooks", tags=["room"])


class RoomMessageIn(BaseModel):
    storeName: str
    username: str
    customerName: str | None = None
    message: str


def _real_deps() -> RoomAgentDeps:
    # Imports aqui (no arriba): traen langchain/SQLAlchemy y el chequeo de la
    # clave debe responder aunque eso no este cargado.
    from langchain_core.messages import HumanMessage, SystemMessage

    from app.db import LiveshopSessionLocal
    from app.graph.nodes import _build_llm, _extract_usage, _log_comment_ai
    from app.mysql_tools import find_store_by_name, list_store_products, list_variants
    from app.settings_store import get_store_ai_config

    def with_db(fn):
        def run(*args):
            db = LiveshopSessionLocal()
            try:
                return fn(db, *args)
            finally:
                db.close()
        return run

    def invoke(cfg, system: str, human: str):
        result = _build_llm(cfg).invoke([SystemMessage(content=system), HumanMessage(content=human)])
        prompt_tokens, completion_tokens = _extract_usage(result)
        return result.content, prompt_tokens, completion_tokens

    def log(store, username, message, cfg, success, prompt_tokens, completion_tokens, error):
        # Mismo registro que los comentarios del live: alimenta el panel de
        # "Uso de IA" (costo por tienda).
        _log_comment_ai(
            {"store_id": store["id"], "store": store, "username": username, "comment": message},
            cfg.ai_provider, "sala_pregunta", "Sala del live", False, success, error,
            prompt_tokens, completion_tokens,
        )

    def record(store, username, message, reply):
        from app.db import AiSessionLocal
        from app.models import Conversation, Message

        db = AiSessionLocal()
        try:
            # Mismo hilo que sus comentarios de TikTok: (tienda, usuario de TikTok)
            conversation = (
                db.query(Conversation).filter_by(store_id=store["id"], contact_phone=username).first()
            )
            if not conversation:
                conversation = Conversation(store_id=store["id"], contact_phone=username)
                db.add(conversation)
                db.commit()
                db.refresh(conversation)
            db.add(Message(conversation_id=conversation.id, direction="in", body=message))
            if reply:
                db.add(Message(conversation_id=conversation.id, direction="out", body=reply))
            db.commit()
        finally:
            db.close()

    return RoomAgentDeps(
        find_store=with_db(find_store_by_name),
        list_catalog=with_db(list_store_products),
        list_variants=with_db(list_variants),
        get_config=get_store_ai_config,
        invoke=invoke,
        log=log,
        record=record,
    )


def _check_internal_key(provided: str | None) -> None:
    if not settings.internal_api_key:
        raise HTTPException(status_code=503, detail="Sala del live no habilitada en este servidor")
    if not provided or not hmac.compare_digest(provided, settings.internal_api_key):
        raise HTTPException(status_code=401, detail="No autorizado")


@router.post("/room-message")
def room_message(body: RoomMessageIn, x_internal_key: str | None = Header(default=None)):
    """Un cliente escribio en la sala del live. Lo llama SOLO el backend
    NestJS (clave compartida). Devuelve {reply, visibility, skipped}: `reply`
    null significa que no hay nada que publicar."""
    _check_internal_key(x_internal_key)
    return answer(_real_deps(), body.storeName, body.username, body.customerName, body.message)


class CartSavedItem(BaseModel):
    name: str
    quantity: int = 1


class CartSavedIn(BaseModel):
    storeName: str
    phone: str
    customerName: str | None = None
    roomUrl: str
    items: list[CartSavedItem] = []


@router.post("/cart-saved")
def cart_saved(body: CartSavedIn, x_internal_key: str | None = Header(default=None)):
    """Termino el live y el pedido de este cliente quedo guardado: un WhatsApp
    con su link de sala. Lo llama SOLO el backend NestJS (clave compartida)."""
    _check_internal_key(x_internal_key)

    from app.db import AiSessionLocal, LiveshopSessionLocal
    from app import evolution_client
    from app.models import WhatsappInstance
    from app.mysql_tools import find_store_by_name

    def find_instance(store_name: str):
        liveshop_db = LiveshopSessionLocal()
        try:
            store = find_store_by_name(liveshop_db, store_name)
        finally:
            liveshop_db.close()
        if not store:
            return None
        ai_db = AiSessionLocal()
        try:
            instance = ai_db.query(WhatsappInstance).filter_by(store_id=store["id"]).first()
            return instance.instance_name if instance else None
        finally:
            ai_db.close()

    deps = CartSavedDeps(find_instance=find_instance, send_text=evolution_client.send_text)
    return deliver(deps, body.storeName, body.phone, body.customerName, body.roomUrl,
                   [item.model_dump() for item in body.items])
