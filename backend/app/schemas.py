from datetime import datetime
from pydantic import BaseModel


class WhatsappStatus(BaseModel):
    store_id: int
    instance_name: str | None = None
    status: str
    qr_code: str | None = None

    class Config:
        from_attributes = True


class MessageOut(BaseModel):
    id: int
    direction: str
    body: str
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationOut(BaseModel):
    id: int
    store_id: int
    contact_phone: str
    chatwoot_conversation_id: int | None
    current_label: str | None
    created_at: datetime
    # Ultimo comentario del cliente (mensaje entrante mas reciente) - para que
    # se pueda ver de un vistazo en la lista sin tener que abrir la conversacion.
    last_comment: str | None = None

    class Config:
        from_attributes = True


class ConversationDetailOut(ConversationOut):
    messages: list[MessageOut] = []
