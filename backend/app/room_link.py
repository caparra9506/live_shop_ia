"""Link de la sala del live para la oferta de venta por WhatsApp.

Se lo pide al backend NestJS (endpoint interno, clave compartida). Si la
funcion esta apagada, no hay clave o el backend no responde, devuelve None y
la oferta sigue saliendo con el link de pago de siempre: nunca se pierde una
venta por esto."""

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 5


def fetch_room_link(user_id: int, product_id: int | None = None,
                    client: httpx.Client | None = None) -> str | None:
    if not (settings.room_links_enabled and settings.internal_api_key):
        return None

    owns_client = client is None
    client = client or httpx.Client(timeout=TIMEOUT_SECONDS)
    try:
        response = client.post(
            f"{settings.liveshop_backend_url.rstrip('/')}/api/live-room/internal/link",
            json={"tiktokUserId": user_id, "productId": product_id},
            headers={"X-Internal-Key": settings.internal_api_key},
        )
        response.raise_for_status()
        url = response.json().get("url")
        return url if isinstance(url, str) and url.startswith(("http://", "https://")) else None
    except Exception:
        logger.exception("No se pudo obtener el link de sala (user_id=%s); se usa el link de pago", user_id)
        return None
    finally:
        if owns_client:
            client.close()
