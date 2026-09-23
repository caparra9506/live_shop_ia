import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.auth import get_current_user, require_store_access, bearer_scheme
from app.config import settings
from app.constants import CAPTURE_LABEL, REGISTERED_LABEL
from app.db import get_ai_db
from app.models import Conversation, Message, WhatsappInstance
from app.schemas import ConversationOut, ConversationDetailOut, MessageOut
from app.settings_store import get_store_ai_config, save_store_ai_config
from app import evolution_client, chatwoot_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationOut])
def list_conversations(
    store_id: int | None = None,
    db: Session = Depends(get_ai_db),
    user: dict = Depends(get_current_user),
):
    if store_id is not None:
        require_store_access(store_id, user)
    elif user.get("role") != "admin":
        raise HTTPException(status_code=400, detail="Falta store_id")

    last_activity = (
        db.query(
            Message.conversation_id.label("conversation_id"),
            func.max(Message.created_at).label("last_at"),
        )
        .group_by(Message.conversation_id)
        .subquery()
    )
    query = (
        db.query(Conversation)
        .options(joinedload(Conversation.messages))
        .outerjoin(last_activity, last_activity.c.conversation_id == Conversation.id)
        .order_by(func.coalesce(last_activity.c.last_at, Conversation.created_at).desc())
    )
    if store_id is not None:
        query = query.filter(Conversation.store_id == store_id)
    conversations = query.limit(200).all()

    result = []
    for conv in conversations:
        incoming = [m for m in conv.messages if m.direction == "in"]
        out = ConversationOut.model_validate(conv)
        out.last_comment = incoming[-1].body if incoming else None
        result.append(out)
    return result


@router.get("/{conversation_id}", response_model=ConversationDetailOut)
def get_conversation(
    conversation_id: int,
    db: Session = Depends(get_ai_db),
    user: dict = Depends(get_current_user),
):
    conversation = (
        db.query(Conversation)
        .options(joinedload(Conversation.messages))
        .filter(Conversation.id == conversation_id)
        .first()
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversacion no encontrada")
    require_store_access(conversation.store_id, user)
    return conversation


def _apply_internal_label(db: Session, conversation: Conversation, title: str, color: str) -> None:
    """Pone una etiqueta de uso interno en la conversacion (local + Chatwoot),
    creandola en la tienda si todavia no existe."""
    cfg = get_store_ai_config(conversation.store_id)
    if not any(item.get("title") == title for item in cfg.extra_labels):
        save_store_ai_config(
            conversation.store_id,
            extra_labels=[{"title": title, "color": color}, *cfg.extra_labels],
        )

    conversation.current_label = title
    db.commit()
    db.refresh(conversation)

    if conversation.chatwoot_conversation_id:
        try:
            chatwoot_client.set_labels(conversation.store_id, conversation.chatwoot_conversation_id, [title])
        except httpx.HTTPError:
            pass  # la etiqueta local ya quedo puesta, se puede resincronizar despues


@router.post("/{conversation_id}/mark-capturing", response_model=ConversationOut)
def mark_capturing(
    conversation_id: int,
    db: Session = Depends(get_ai_db),
    user: dict = Depends(get_current_user),
):
    """Se llama cuando el vendedor copia el mensaje pidiendo nombre/numero a
    un contacto sin cuenta - le pone la etiqueta 'En captura de cliente' para
    poder seguirle la pista despues, en vez de perderlo mezclado entre todos
    los "Nuevo contacto". Crea la etiqueta sola si la tienda no la tenia."""
    conversation = db.query(Conversation).filter_by(id=conversation_id).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversacion no encontrada")
    require_store_access(conversation.store_id, user)

    _apply_internal_label(db, conversation, CAPTURE_LABEL, "#f59e0b")
    return ConversationOut.model_validate(conversation)


class RegisterUserIn(BaseModel):
    name: str
    phone: str


@router.post("/{conversation_id}/register-user", response_model=ConversationOut)
def register_user(
    conversation_id: int,
    payload: RegisterUserIn,
    db: Session = Depends(get_ai_db),
    user: dict = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    """Guarda nombre/telefono que el vendedor consiguio por fuera (TikTok,
    etc.) para un contacto que llego sin cuenta - crea/actualiza el
    tik_tok_user REAL en el backend NestJS (la escritura no se hace directo
    a MySQL desde aca). NO se toca contact_phone de la conversacion (sigue
    siendo el usuario de TikTok, es la llave que usa el webhook para agrupar
    sus comentarios): el WhatsApp queda en whatsapp_phone, desde donde ya se
    le puede escribir y recibir sus respuestas. La conversacion sale de "En
    captura de cliente" a "Cliente registrado"."""
    conversation = db.query(Conversation).filter_by(id=conversation_id).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversacion no encontrada")
    require_store_access(conversation.store_id, user)

    # tik_tok_user guarda el numero como lo usa el resto del sistema (10
    # digitos, sin indicativo); el 57 solo se agrega al hablar con Evolution.
    phone = "".join(ch for ch in payload.phone if ch.isdigit())
    if len(phone) < 10:
        raise HTTPException(status_code=422, detail="El numero de WhatsApp no parece valido")

    try:
        resp = httpx.post(
            f"{settings.liveshop_backend_url}/api/tiktokuser/manual-register",
            json={
                "storeId": conversation.store_id,
                "tiktok": conversation.contact_phone,
                "name": payload.name,
                "phone": phone,
            },
            headers={"Authorization": f"Bearer {credentials.credentials}"},
            timeout=15.0,
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"No se pudo registrar el cliente: {e}")

    conversation.whatsapp_phone = evolution_client.normalize_phone(phone)
    conversation.contact_name = payload.name.strip()[:120]
    # Si esa persona ya habia escrito por WhatsApp sin dar su @, su chat queda
    # aparte (wa:<numero>): se une aqui para no verla dos veces en el panel.
    from app.whatsapp_link import merge_pending_into

    merge_pending_into(db, conversation)
    _apply_internal_label(db, conversation, REGISTERED_LABEL, "#22c55e")
    return ConversationOut.model_validate(conversation)


class ReplyIn(BaseModel):
    text: str


@router.post("/{conversation_id}/reply", response_model=MessageOut)
def reply_to_conversation(
    conversation_id: int,
    payload: ReplyIn,
    db: Session = Depends(get_ai_db),
    user: dict = Depends(get_current_user),
):
    """Responder a mano desde el panel - para cuando el agente de IA no basta
    y alguien del equipo quiere escribirle directo al cliente."""
    conversation = db.query(Conversation).filter_by(id=conversation_id).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversacion no encontrada")
    require_store_access(conversation.store_id, user)

    phone = conversation.whatsapp_phone or (
        conversation.contact_phone if conversation.contact_phone.lstrip("+").isdigit() else None
    )
    if not phone:
        raise HTTPException(
            status_code=422,
            detail="Este contacto no tiene un telefono de WhatsApp conocido (no esta registrado en la tienda)",
        )

    instance = db.query(WhatsappInstance).filter_by(store_id=conversation.store_id).first()
    if not instance or instance.status != "connected":
        raise HTTPException(status_code=422, detail="El WhatsApp de esta tienda no esta conectado")

    try:
        evolution_client.send_text(instance.instance_name, phone, payload.text)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"No se pudo enviar por WhatsApp: {e}")

    if conversation.chatwoot_conversation_id:
        try:
            chatwoot_client.create_message(
                conversation.store_id, conversation.chatwoot_conversation_id, payload.text
            )
        except Exception:
            logger.exception("No se pudo reflejar la respuesta manual en Chatwoot (conversation_id=%s)", conversation_id)

    message = Message(conversation_id=conversation_id, direction="out", body=payload.text)
    db.add(message)
    db.commit()
    db.refresh(message)
    return message
