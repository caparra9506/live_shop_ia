"""Cliente HTTP para Evolution API (WhatsApp), soporta multiples instancias
(una por tienda) bajo el mismo despliegue - ver plan de migracion."""

import httpx

from app.config import settings
from app.settings_store import get_infra_settings


def _client() -> httpx.Client:
    api_key = get_infra_settings().evolution_api_key
    headers = {"apikey": api_key, "Content-Type": "application/json"}
    return httpx.Client(base_url=settings.evolution_api_url, headers=headers, timeout=30.0)


def create_instance(instance_name: str) -> dict:
    webhook_url = f"{settings.ai_backend_public_url}/webhooks/evolution/{instance_name}"
    with _client() as client:
        resp = client.post(
            "/instance/create",
            json={
                "instanceName": instance_name,
                "qrcode": True,
                "integration": "WHATSAPP-BAILEYS",
                "webhook": {
                    "url": webhook_url,
                    "byEvents": False,
                    "base64": False,
                    "events": ["MESSAGES_UPSERT"],
                },
            },
        )
        resp.raise_for_status()
        return resp.json()


def set_webhook(instance_name: str) -> dict:
    """Para instancias que ya existian antes de que create_instance configurara
    el webhook (ej. niqui_fashion, creada antes de este cambio)."""
    webhook_url = f"{settings.ai_backend_public_url}/webhooks/evolution/{instance_name}"
    with _client() as client:
        resp = client.post(
            f"/webhook/set/{instance_name}",
            json={
                "webhook": {
                    "enabled": True,
                    "url": webhook_url,
                    "byEvents": False,
                    "base64": False,
                    "events": ["MESSAGES_UPSERT"],
                }
            },
        )
        resp.raise_for_status()
        return resp.json()


def get_connect_qr(instance_name: str) -> dict:
    with _client() as client:
        resp = client.get(f"/instance/connect/{instance_name}")
        resp.raise_for_status()
        return resp.json()


def logout_instance(instance_name: str) -> None:
    """Cierra la sesion de WhatsApp de esa instancia (queda desconectada, hay
    que volver a escanear QR) sin borrar la instancia en si de Evolution."""
    with _client() as client:
        resp = client.delete(f"/instance/logout/{instance_name}")
        resp.raise_for_status()


def get_connection_state(instance_name: str) -> str:
    with _client() as client:
        resp = client.get(f"/instance/connectionState/{instance_name}")
        resp.raise_for_status()
        data = resp.json()
        return data.get("instance", {}).get("state", "close")


def send_text(instance_name: str, phone: str, text: str) -> dict:
    with _client() as client:
        resp = client.post(
            f"/message/sendText/{instance_name}",
            json={"number": phone, "text": text},
        )
        resp.raise_for_status()
        return resp.json()


def send_media(instance_name: str, phone: str, media_url: str, media_type: str, caption: str = "") -> dict:
    with _client() as client:
        resp = client.post(
            f"/message/sendMedia/{instance_name}",
            json={
                "number": phone,
                "mediatype": media_type,  # 'image' | 'document'
                "media": media_url,
                "caption": caption,
            },
        )
        resp.raise_for_status()
        return resp.json()
