from typing import TypedDict


class AgentState(TypedDict, total=False):
    # Datos crudos del comentario de TikTok Live (igual al payload real que
    # manda TikTokCommentService.sendDirectToWebhook del backend).
    username: str  # @usuario de TikTok que comento
    comment: str
    store_name: str

    store_id: int
    conversation_id: int  # id local (nuestra BD), no el de Chatwoot
    instance_name: str

    # 'no_registrado' (usuario sin cuenta), 'sin_clasificar' (no hay ninguna
    # etiqueta propia de la tienda que encaje, o la tienda todavia no creo
    # ninguna), o el texto EXACTO de una etiqueta libre que la tienda creo
    # ella misma (ya no son 3 categorias fijas - ver classify_intent).
    intent: str
    label_text: str  # texto real a usar en Chatwoot para esta intencion
    skip_response: bool  # true si la tienda aun no tiene ninguna etiqueta propia
    ai_log_id: int | None  # fila de comment_ai_logs creada por classify_intent
    store: dict | None
    tiktok_user: dict | None  # None si no esta registrado - sin telefono conocido
    products: list[dict]
    response_text: str
