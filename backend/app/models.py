from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Float
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db import Base


class WhatsappInstance(Base):
    __tablename__ = "whatsapp_instances"

    id = Column(Integer, primary_key=True)
    store_id = Column(Integer, nullable=False, unique=True, index=True)
    instance_name = Column(String(120), nullable=False, unique=True)
    evolution_token = Column(String(255), nullable=True)
    status = Column(String(20), nullable=False, default="disconnected")
    qr_code = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True)
    store_id = Column(Integer, nullable=False, index=True)
    contact_phone = Column(String(40), nullable=False)
    # contact_phone es la llave con la que el webhook agrupa los comentarios
    # (el usuario de TikTok) y NO cambia al registrar al cliente. Estos dos
    # campos guardan lo que el vendedor consiguio por fuera: con
    # whatsapp_phone ya se le puede escribir (y recibir sus respuestas).
    whatsapp_phone = Column(String(40), nullable=True, index=True)
    contact_name = Column(String(120), nullable=True)
    chatwoot_conversation_id = Column(Integer, nullable=True)
    # Ultima intencion clasificada para esta conversacion (venta/queja/soporte/
    # no_registrado) - alimenta la vista de "agrupado por etiqueta" del panel,
    # sin tener que consultarle a Chatwoot cada vez.
    # 120 (no 20) - antes solo cabian slugs cortos como 'venta', pero ahora
    # guarda el TEXTO real de cualquier etiqueta libre que la tienda cree
    # (ej. "En captura de cliente", 22 caracteres) - truncaba con un 500.
    current_label = Column(String(120), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    messages = relationship("Message", back_populates="conversation", order_by="Message.created_at")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False, index=True)
    direction = Column(String(3), nullable=False)  # 'in' | 'out'
    body = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    conversation = relationship("Conversation", back_populates="messages")


class AppSettings(Base):
    """Fila unica (id=1) con config de INFRAESTRUCTURA compartida (no es por
    tienda): la key admin de Evolution API, que administra todas las
    instancias del mismo despliegue. Editable desde el panel, sin reiniciar."""

    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True, default=1)
    evolution_api_key = Column(String(255), nullable=True)
    chatwoot_base_url = Column(String(255), nullable=True)
    # chatwoot_base_url es el host interno de Docker (para que este backend
    # llame la API de Chatwoot server-to-server) - no es navegable desde el
    # navegador de Camilo. chatwoot_public_url es la URL real para los links
    # que se muestran en el panel (ej: http://2.24.139.178:3010).
    chatwoot_public_url = Column(String(255), nullable=True)
    # Token del Platform App de Chatwoot (Super Admin -> Platform Apps) - se
    # saca UNA sola vez, no por tienda. Con esto se pueden crear cuentas y
    # agent bots (con su propio access_token) de forma 100% automatica.
    chatwoot_platform_api_key = Column(String(255), nullable=True)
    # Token PERSONAL de un usuario admin de Chatwoot (Perfil -> Control de
    # acceso a la API) - se usa solo al aprovisionar una tienda nueva, para
    # crear el inbox de esa cuenta (el agent bot no tiene permisos de admin).
    chatwoot_admin_token = Column(String(255), nullable=True)
    # Tu propio user id en Chatwoot (no el de "LiveShop Automation") - se
    # agrega como admin a cada cuenta nueva junto con el usuario de
    # automatización, para que sigas viendo/entrando a cada cuenta en la UI.
    chatwoot_owner_user_id = Column(Integer, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class StoreAiConfig(Base):
    """Config propia de CADA tienda: proveedor/API key de IA, prompt del
    agente y su cuenta de Chatwoot separada (misma instancia de Chatwoot,
    account_id distinto por tienda)."""

    __tablename__ = "store_ai_config"

    id = Column(Integer, primary_key=True)
    store_id = Column(Integer, nullable=False, unique=True, index=True)

    ai_provider = Column(String(20), nullable=False, default="openai")  # 'openai' | 'deepseek'
    ai_api_key = Column(String(255), nullable=True)
    system_prompt = Column(Text, nullable=True)

    chatwoot_account_id = Column(Integer, nullable=True)
    chatwoot_api_token = Column(String(255), nullable=True)
    chatwoot_inbox_id = Column(Integer, nullable=True)

    # Nombres de las etiquetas que se aplican en Chatwoot segun la intencion
    # detectada - editables desde el panel, para que alguien no tecnico pueda
    # renombrarlas sin tocar codigo.
    label_venta = Column(String(60), nullable=False, default="Venta")
    label_queja = Column(String(60), nullable=False, default="Queja")
    label_soporte = Column(String(60), nullable=False, default="Soporte")
    label_no_registrado = Column(String(60), nullable=False, default="Nuevo contacto")

    # Etiquetas adicionales, libres, que el vendedor agrega el mismo desde el
    # panel (no atadas a ninguna intención que detecte la IA) - guardadas
    # como JSON (lista de strings) en un solo campo de texto.
    extra_labels_json = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CommentAiLog(Base):
    """Registro de cada comentario del live que pasa por el agente - para que
    Camilo pueda ver que esta decidiendo la IA (que etiqueta eligio, con que
    proveedor, si fallo) sin tener que revisar logs de servidor a mano."""

    __tablename__ = "comment_ai_logs"

    id = Column(Integer, primary_key=True)
    store_id = Column(Integer, nullable=False, index=True)
    store_name = Column(String(255), nullable=True)
    username = Column(String(255), nullable=False)
    comment = Column(Text, nullable=False)

    ai_provider = Column(String(20), nullable=True)
    intent = Column(String(120), nullable=True)  # 'no_registrado' | 'sin_clasificar' | etiqueta elegida
    label_text = Column(String(120), nullable=True)  # texto puesto en Chatwoot
    skip_response = Column(Integer, nullable=False, default=0)  # 0/1 - no habia etiquetas propias todavia
    success = Column(Integer, nullable=False, default=1)  # 0/1
    error_message = Column(Text, nullable=True)

    # Suma de la llamada de clasificacion + la de composicion de respuesta
    # (si hubo) - para poder ver cuanto esta costando el agente del live.
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)
    estimated_cost_usd = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class StoreMessageTemplate(Base):
    """Mensaje de retención de cada tienda: el texto que el vendedor copia en
    Prospección para pedirle al cliente del live que le escriba por WhatsApp.
    Tabla aparte (no columna en store_ai_config) para que create_all la cree
    sola al arrancar, sin migración a mano."""

    __tablename__ = "store_message_templates"

    store_id = Column(Integer, primary_key=True)
    retention_copy = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
