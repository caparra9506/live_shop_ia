"""Consultas de SOLO LECTURA contra el MySQL de LiveShop - puerto fiel de los
nodos reales del workflow COMPRE_PUES_SISTEMA_N8N en n8n (SQL extraido
directo de la definicion del workflow, no adivinado).
Cualquier escritura debe ir por la API del backend NestJS, no por aqui."""

from sqlalchemy import text
from sqlalchemy.orm import Session


def find_store(db: Session, store_id: int) -> dict | None:
    row = db.execute(
        text("SELECT id, name, description, phone FROM store WHERE id = :store_id"),
        {"store_id": store_id},
    ).mappings().first()
    return dict(row) if row else None


def find_store_by_name(db: Session, name: str) -> dict | None:
    """Puerto exacto del nodo 'find store': SELECT * FROM store WHERE name = ?
    - asi llega storeName en el webhook real del backend (TikTokCommentService),
    no un storeId."""
    row = db.execute(
        text("SELECT id, name, description, phone FROM store WHERE name = :name"),
        {"name": name},
    ).mappings().first()
    return dict(row) if row else None


def find_products(db: Session, store_id: int, query: str, limit: int = 5) -> list[dict]:
    rows = db.execute(
        text(
            """
            SELECT p.id, p.name, p.price, p.stock, p.inStock, p.description, p.imageUrl
            FROM product p
            INNER JOIN category c ON c.id = p.categoryId
            WHERE c.storeId = :store_id
              AND p.name LIKE :query
            LIMIT :limit
            """
        ),
        {"store_id": store_id, "query": f"%{query}%", "limit": limit},
    ).mappings().all()
    return [dict(r) for r in rows]


def list_ai_draft_logs(db: Session, limit: int = 100) -> list[dict]:
    """Registro de cada llamada a la IA de vision del panel de tienda (carga
    de productos con foto) - insertado por live_shop_back en su propia BD,
    aqui solo se lee para que Camilo pueda auditar uso y gasto."""
    rows = db.execute(
        text(
            """
            SELECT id, storeId, storeName, imageUrl, note, suggestedName,
                   success, errorMessage, promptTokens, completionTokens,
                   estimatedCostUsd, createdAt
            FROM product_ai_draft_log
            ORDER BY createdAt DESC
            LIMIT :limit
            """
        ),
        {"limit": limit},
    ).mappings().all()
    return [dict(r) for r in rows]


def find_tiktok_user(db: Session, tiktok_username: str) -> dict | None:
    """Puerto exacto del nodo 'find_user': SELECT * FROM tik_tok_user WHERE
    tiktok = ?. Si no hay fila, el comentario es de alguien no registrado -
    no hay telefono conocido para responder por WhatsApp (solo queda el
    registro en Chatwoot, igual que en n8n)."""
    row = db.execute(
        text(
            "SELECT id, tiktok, name, phone, storeId FROM tik_tok_user WHERE tiktok = :username LIMIT 1"
        ),
        {"username": tiktok_username},
    ).mappings().first()
    return dict(row) if row else None
