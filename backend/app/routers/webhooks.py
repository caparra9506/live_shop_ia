import logging

from fastapi import APIRouter, Request

from app.db import LiveshopSessionLocal, AiSessionLocal
from app.models import WhatsappInstance, Conversation, Message
from app.mysql_tools import find_store_by_name
from app.graph.graph import get_graph
from app import chatwoot_client, whatsapp_link

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/tiktok-comment")
async def tiktok_comment_webhook(request: Request):
    """Reemplaza el webhook de n8n (COMPRE_PUES_SISTEMA_N8N) que hoy llama
    TikTokCommentService.sendDirectToWebhook() del backend NestJS cuando entra
    un comentario en un TikTok Live. Mismo payload: {username, comment,
    storeName, timestamp} - NO es un mensaje de WhatsApp entrante."""
    payload = await request.json()
    username = payload.get("username")
    comment = payload.get("comment")
    store_name = payload.get("storeName")

    if not username or not comment or not store_name:
        return {"ignored": "payload incompleto (se espera username, comment, storeName)"}

    liveshop_db = LiveshopSessionLocal()
    try:
        store = find_store_by_name(liveshop_db, store_name)
    finally:
        liveshop_db.close()

    if not store:
        return {"error": f"tienda desconocida: {store_name}"}

    ai_db = AiSessionLocal()
    try:
        instance = ai_db.query(WhatsappInstance).filter_by(store_id=store["id"]).first()
        instance_name = instance.instance_name if instance else None

        conversation = (
            ai_db.query(Conversation).filter_by(store_id=store["id"], contact_phone=username).first()
        )
        if not conversation:
            conversation = Conversation(store_id=store["id"], contact_phone=username)
            ai_db.add(conversation)
            ai_db.commit()
            ai_db.refresh(conversation)

        ai_db.add(Message(conversation_id=conversation.id, direction="in", body=comment))
        ai_db.commit()
        conversation_id = conversation.id
    finally:
        ai_db.close()

    graph = get_graph()
    result = graph.invoke(
        {
            "username": username,
            "comment": comment,
            "store_name": store_name,
            "store_id": store["id"],
            "conversation_id": conversation_id,
            "instance_name": instance_name,
        }
    )

    if result.get("response_text"):
        # Vacio significa que compose_response decidio a proposito no
        # responder (sin cuenta registrada, o la tienda aun sin etiquetas) -
        # no se debe guardar una burbuja vacia en la conversacion.
        ai_db = AiSessionLocal()
        try:
            ai_db.add(Message(conversation_id=conversation_id, direction="out", body=result["response_text"]))
            ai_db.commit()
        finally:
            ai_db.close()

    return {"ok": True, "intent": result.get("intent"), "response_text": result.get("response_text")}


def _incoming_text(message: dict) -> str | None:
    return (
        message.get("conversation")
        or (message.get("extendedTextMessage") or {}).get("text")
        or (message.get("imageMessage") or {}).get("caption")
    )


@router.post("/evolution/{instance_name}")
async def evolution_webhook(instance_name: str, request: Request):
    """Mensajes de WhatsApp que un cliente le responde a la tienda. NO dispara
    el agente de IA (eso es solo para comentarios del live) - unicamente se
    guarda el mensaje en la conversacion de ese cliente para que el vendedor
    lo vea y le conteste desde el panel."""
    payload = await request.json()
    data = payload.get("data") or {}
    key = data.get("key") or {}

    if key.get("fromMe"):
        return {"ignored": "mensaje propio"}

    # Evolution v2 puede entregar el id interno (@lid) en remoteJid y el
    # numero real en remoteJidAlt.
    jid = key.get("remoteJid") or ""
    if jid.endswith("@lid"):
        jid = key.get("remoteJidAlt") or jid
    if not jid.endswith("@s.whatsapp.net"):
        return {"ignored": "no es un chat individual"}
    phone = jid.split("@")[0]

    text = _incoming_text(data.get("message") or {})
    if not text:
        return {"ignored": "mensaje sin texto"}

    db = AiSessionLocal()
    try:
        instance = db.query(WhatsappInstance).filter_by(instance_name=instance_name).first()
        if not instance:
            return {"ignored": "instancia desconocida"}

        conversation = (
            db.query(Conversation)
            .filter(
                Conversation.store_id == instance.store_id,
                (Conversation.whatsapp_phone == phone) | (Conversation.contact_phone == phone),
            )
            .order_by(Conversation.created_at.desc())
            .first()
        )
        if not conversation:
            return whatsapp_link.handle_unknown_sender(db, instance, phone, text, data.get("pushName"))
        if conversation.contact_phone.startswith(whatsapp_link.PENDING_PREFIX):
            return whatsapp_link.handle_pending(db, instance, conversation, text)

        db.add(Message(conversation_id=conversation.id, direction="in", body=text))
        db.commit()
        store_id, chatwoot_conversation_id = conversation.store_id, conversation.chatwoot_conversation_id
    finally:
        db.close()

    if chatwoot_conversation_id:
        try:
            chatwoot_client.create_message(store_id, chatwoot_conversation_id, text, incoming=True)
        except Exception:
            logger.exception("No se pudo reflejar el mensaje entrante en Chatwoot (store_id=%s)", store_id)

    return {"ok": True}
