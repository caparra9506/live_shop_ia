import hmac

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.config import settings
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

    return RoomAgentDeps(
        find_store=with_db(find_store_by_name),
        list_catalog=with_db(list_store_products),
        list_variants=with_db(list_variants),
        get_config=get_store_ai_config,
        invoke=invoke,
        log=log,
    )


@router.post("/room-message")
def room_message(body: RoomMessageIn, x_internal_key: str | None = Header(default=None)):
    """Un cliente escribio en la sala del live. Lo llama SOLO el backend
    NestJS (clave compartida). Devuelve {reply, visibility, skipped}: `reply`
    null significa que no hay nada que publicar."""
    if not settings.internal_api_key:
        raise HTTPException(status_code=503, detail="Sala del live no habilitada en este servidor")
    if not x_internal_key or not hmac.compare_digest(x_internal_key, settings.internal_api_key):
        raise HTTPException(status_code=401, detail="No autorizado")
    return answer(_real_deps(), body.storeName, body.username, body.customerName, body.message)
