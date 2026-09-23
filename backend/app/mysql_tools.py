"""Consultas de SOLO LECTURA contra el MySQL de LiveShop - puerto fiel de los
nodos reales del workflow COMPRE_PUES_SISTEMA_N8N en n8n (SQL extraido
directo de la definicion del workflow, no adivinado).
Cualquier escritura debe ir por la API del backend NestJS, no por aqui."""

from sqlalchemy import bindparam, text
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


def list_store_products(db: Session, store_id: int) -> list[dict]:
    """Catalogo de la tienda (solo lo necesario para detectar el codigo en un
    comentario y armar la oferta) - de solo lectura."""
    rows = db.execute(
        text(
            """
            SELECT p.id, p.name, p.code, p.price, p.stock, p.inStock, p.imageUrl, p.description
            FROM product p
            INNER JOIN category c ON c.id = p.categoryId
            WHERE c.storeId = :store_id
            """
        ),
        {"store_id": store_id},
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


def find_tiktok_user_by_phone(db: Session, store_id: int, phone: str) -> dict | None:
    """Cliente de ESTA tienda con ese WhatsApp (tik_tok_user guarda 10
    digitos sin 57, pero hay filas viejas con el numero completo)."""
    digits = "".join(ch for ch in phone if ch.isdigit())
    short = digits[2:] if len(digits) == 12 and digits.startswith("57") else digits
    row = db.execute(
        text(
            "SELECT id, tiktok, name, phone FROM tik_tok_user "
            "WHERE storeId = :store_id AND phone IN (:short, :full) ORDER BY id DESC LIMIT 1"
        ),
        {"store_id": store_id, "short": short, "full": "57" + short},
    ).mappings().first()
    return dict(row) if row else None


def find_tiktok_handles_by_name(db: Session, store_id: int, name: str, hours: int = 36) -> list[str]:
    """@ de TikTok (sin arroba) cuyo nombre visible se parece a `name`: el que
    vio la extension en el chat del live reciente (live_capture_comment) o el
    que dejo al registrarse (tik_tok_user). La collation de MySQL ya ignora
    mayusculas y tildes. Puede devolver varios: decide quien llama."""
    rows = db.execute(
        text(
            """
            SELECT DISTINCT tiktokHandle AS tiktok FROM live_capture_comment
            WHERE storeId = :store_id AND tiktokHandle IS NOT NULL
              AND displayName LIKE :name
              AND capturedAt >= NOW() - INTERVAL :hours HOUR
            UNION
            SELECT DISTINCT tiktok FROM tik_tok_user
            WHERE storeId = :store_id AND name LIKE :name
            """
        ),
        {"store_id": store_id, "name": f"%{name}%", "hours": hours},
    ).scalars().all()
    return list({r.lower(): r for r in rows if r}.values())


def store_live_info(db: Session, store_id: int) -> dict | None:
    row = db.execute(
        text("SELECT liveStatus, liveConnectedAt, liveDisconnectedAt FROM store WHERE id = :store_id"),
        {"store_id": store_id},
    ).mappings().first()
    return dict(row) if row else None


def list_variants(db: Session, product_ids: list[int]) -> dict[int, list[dict]]:
    """Colores/tallas (y su stock) de esos productos, para contestar "lo
    tienen en negro?". Devuelve {} si no hay ids."""
    if not product_ids:
        return {}
    rows = db.execute(
        text(
            """
            SELECT pv.productId AS product_id, c.name AS color, s.name AS size, pv.stock AS stock
            FROM product_variant pv
            LEFT JOIN color c ON c.id = pv.colorId
            LEFT JOIN size s ON s.id = pv.sizeId
            WHERE pv.productId IN :ids
            """
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": list(product_ids)},
    ).mappings().all()
    out: dict[int, list[dict]] = {}
    for row in rows:
        out.setdefault(row["product_id"], []).append(
            {"color": row["color"], "size": row["size"], "stock": row["stock"]}
        )
    return out
