from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ai_db_host: str = "localhost"
    ai_db_port: int = 5432
    ai_db_user: str = "postgres"
    ai_db_password: str = "postgres"
    ai_db_name: str = "liveshop_ai"

    liveshop_db_host: str = "localhost"
    liveshop_db_port: int = 3306
    liveshop_db_user: str = "mysql"
    liveshop_db_password: str = "compre_pues"
    liveshop_db_name: str = "live_shop"

    evolution_api_url: str = "http://liveshop-evolution-api:8080"
    evolution_api_key: str = ""

    # URL por la que Evolution API (mismo docker network) llega a este backend
    # para mandar los webhooks de mensajes entrantes.
    ai_backend_public_url: str = "http://liveshop-ai-backend:8000"

    liveshop_backend_url: str = "http://liveshop-backend:3000"
    # Dominio publico de LiveShop - base de los links de pago (checkout) que se
    # mandan a los clientes por WhatsApp.
    liveshop_public_url: str = "https://liveshop.com.co"

    chatwoot_base_url: str = "http://liveshop-chatwoot:3000"
    chatwoot_api_token: str = ""
    chatwoot_account_id: int = 1
    chatwoot_platform_api_key: str = ""
    chatwoot_admin_token: str = ""

    jwt_secret: str = "abc123"

    # Clave compartida con el backend NestJS para los endpoints internos
    # (sala del live). Vacia = esos endpoints quedan desactivados.
    internal_api_key: str = ""

    # Interruptor: la oferta de venta manda el link de la SALA del live (con el
    # producto abierto) en vez del link de pago directo. Apagado por defecto.
    room_links_enabled: bool = False

    openai_api_key: str = ""

    # Proveedor/API key que usa el agente del live para clasificar y responder
    # cuando una tienda todavia no configuro los suyos propios (panel interno,
    # pestaña "Inteligencia artificial") - asi el agente funciona desde el
    # primer live sin que el vendedor tenga que configurar nada antes.
    default_ai_provider: str = "openai"
    default_ai_api_key: str = ""

    # Override para desarrollo local (ej. "sqlite:///./dev.db") en vez de armar
    # la URL de Postgres a partir de host/user/password - evita depender de
    # tener Docker/Postgres corriendo solo para probar en el laptop.
    ai_db_url_override: str = ""

    @property
    def ai_db_url(self) -> str:
        if self.ai_db_url_override:
            return self.ai_db_url_override
        return (
            f"postgresql+psycopg2://{self.ai_db_user}:{self.ai_db_password}"
            f"@{self.ai_db_host}:{self.ai_db_port}/{self.ai_db_name}"
        )

    @property
    def liveshop_db_url(self) -> str:
        return (
            f"mysql+pymysql://{self.liveshop_db_user}:{self.liveshop_db_password}"
            f"@{self.liveshop_db_host}:{self.liveshop_db_port}/{self.liveshop_db_name}"
        )

    class Config:
        env_file = ".env"


settings = Settings()
