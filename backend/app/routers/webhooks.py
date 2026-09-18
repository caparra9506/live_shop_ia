from fastapi import APIRouter, Request

from app.db import LiveshopSessionLocal, AiSessionLocal
from app.models import WhatsappInstance, Conversation, Message
from app.mysql_tools import find_store_by_name
from app.graph.graph import get_graph

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
