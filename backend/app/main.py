from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import Base, ai_engine
from app.routers import stores, conversations, webhooks, settings as settings_router, ai_usage, room

app = FastAPI(title="LiveShop AI Orchestrator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(stores.router)
app.include_router(conversations.router)
app.include_router(webhooks.router)
app.include_router(room.router)
app.include_router(settings_router.router)
app.include_router(ai_usage.router)


@app.on_event("startup")
def on_startup():
    # Crea las tablas propias de este servicio si no existen (whatsapp_instances,
    # conversations, messages). Para cambios de esquema mas adelante, pasar a
    # Alembic en vez de create_all.
    Base.metadata.create_all(bind=ai_engine)


@app.get("/health")
def health():
    return {"status": "ok"}
