from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings

# BD propia de este servicio (instancias de WhatsApp, conversaciones, mensajes)
_ai_connect_args = {"check_same_thread": False} if settings.ai_db_url.startswith("sqlite") else {}
ai_engine = create_engine(settings.ai_db_url, pool_pre_ping=True, connect_args=_ai_connect_args)
AiSessionLocal = sessionmaker(bind=ai_engine, autoflush=False, autocommit=False)
Base = declarative_base()

# MySQL de LiveShop, solo lectura (búsquedas del agente: producto/tienda/usuario)
liveshop_engine = create_engine(settings.liveshop_db_url, pool_pre_ping=True)
LiveshopSessionLocal = sessionmaker(bind=liveshop_engine, autoflush=False, autocommit=False)


def get_ai_db():
    db = AiSessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_liveshop_db():
    db = LiveshopSessionLocal()
    try:
        yield db
    finally:
        db.close()
