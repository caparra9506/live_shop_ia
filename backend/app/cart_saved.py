"""Aviso de fin de live: "tu pedido quedó guardado". Lo dispara el backend
NestJS (endpoint interno) una sola vez por cliente cuando termina el live.
Flujo con dependencias inyectables para probarlo sin WhatsApp ni BD."""

import logging
import re
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)

MAX_ITEMS_SHOWN = 5


@dataclass
class CartSavedDeps:
    find_instance: Callable[[str], str | None]  # storeName -> nombre de la instancia de WhatsApp
    send_text: Callable[[str, str, str], None]  # (instancia, telefono, texto)


def build_message(store_name: str, customer_name: str | None, items: list[dict], room_url: str) -> str:
    lines = [f"Hola {customer_name or ''}".rstrip() + " 👋",
             f"Terminó el live de {store_name}. Tu pedido quedó guardado ✅", ""]
    for item in items[:MAX_ITEMS_SHOWN]:
        lines.append(f"• {item.get('quantity', 1)} x {item.get('name', 'Producto')}")
    if len(items) > MAX_ITEMS_SHOWN:
        lines.append(f"• y {len(items) - MAX_ITEMS_SHOWN} más")
    lines += [
        "",
        "Ojo: el stock ya no está reservado. Si aún hay disponibilidad puedes pagarlo cuando quieras, "
        "o sumarlo en el próximo live.",
        "",
        f"Tu pedido 👉 {room_url}",
    ]
    return "\n".join(lines)


def _clean_phone(phone: str) -> str | None:
    digits = re.sub(r"[^0-9]", "", phone or "")
    return digits if 8 <= len(digits) <= 15 else None


def deliver(deps: CartSavedDeps, store_name: str, phone: str, customer_name: str | None,
            room_url: str, items: list[dict]) -> dict:
    number = _clean_phone(phone)
    if not number:
        return {"sent": False, "reason": "telefono_invalido"}
    if not room_url.startswith(("https://", "http://")):
        return {"sent": False, "reason": "link_invalido"}
    instance = deps.find_instance(store_name)
    if not instance:
        return {"sent": False, "reason": "tienda_sin_whatsapp"}
    try:
        deps.send_text(instance, number, build_message(store_name, customer_name, items, room_url))
    except Exception:
        # Un WhatsApp que falla no debe tumbar el aviso a los demas clientes
        logger.exception("No se pudo enviar el aviso de pedido guardado (store=%s)", store_name)
        return {"sent": False, "reason": "error_whatsapp"}
    return {"sent": True, "reason": None}
