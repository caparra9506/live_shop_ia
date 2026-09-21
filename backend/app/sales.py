"""Venta automatica por codigo de producto - puerto de la parte final del
workflow COMPRE_PUES_SISTEMA_N8N (buscar producto -> armar checkout URL ->
enviar imagen por WhatsApp), pero determinista: el producto se identifica por
su `code` en el comentario, sin depender de que un LLM lo encuentre.

Funciones puras (sin BD ni red) para poder probarlas aparte."""

import re
import unicodedata
from decimal import Decimal
from urllib.parse import quote


def normalize(text: str) -> str:
    """Minusculas, sin acentos y con espacios/puntuacion colapsados - asi
    'MÍO Trululu!!' y 'mio trululu' se comparan igual."""
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def match_product_by_code(products: list[dict], comment: str) -> dict | None:
    """Devuelve el producto cuyo `code` aparece en el comentario como palabra
    completa (ej. 'mio trululu', 'me interesa el 687721'). Si varios codigos
    aparecen, gana el mas largo (mas especifico). NO busca por id ni por
    nombre a proposito: un 'quiero 2' no debe disparar el producto con id 2,
    ni una pregunta ('cuanto cuesta la platera') debe mandar un link de pago."""
    haystack = f" {normalize(comment)} "
    best: dict | None = None
    best_len = 0
    for product in products:
        code = normalize(str(product.get("code") or ""))
        if not code:
            continue
        if f" {code} " in haystack and len(code) > best_len:
            best, best_len = product, len(code)
    return best


def build_checkout_url(base_url: str, store_name: str, product_id: int, user_id: int) -> str:
    """Mismo formato que el nodo 'armar url' de n8n."""
    return (
        f"{base_url.rstrip('/')}/tiktok/{quote(store_name, safe='')}/checkout"
        f"?productId={product_id}&userTikTokId={user_id}"
    )


def mentions_offer(body: str, product_id: int) -> bool:
    """True si el mensaje ya trae el link de ese producto, sea el de pago
    (?productId=12&...) o el de la sala (?p=12). 12 no coincide con 123."""
    return re.search(rf"[?&](?:productId|p)={int(product_id)}(?!\d)", body or "") is not None


def format_price(price) -> str:
    """4000 -> '$4.000' (separador de miles colombiano)."""
    value = int(Decimal(str(price or 0)))
    return "$" + f"{value:,}".replace(",", ".")


def build_offer_caption(customer_name: str, product_name: str, price, checkout_url: str) -> str:
    return (
        f"Hola {customer_name} 👋\n"
        f"Este es el producto que te interesa: *{product_name}*\n"
        f"Precio: {format_price(price)}\n\n"
        f"Finaliza tu compra aquí 👉 {checkout_url}"
    )


def is_available(product: dict) -> bool:
    return bool(product.get("inStock")) and (product.get("stock") or 0) > 0


def build_room_offer_caption(customer_name: str, product_name: str, price, room_url: str) -> str:
    return (
        f"Hola {customer_name} 👋\n"
        f"Este es el producto que te interesa: *{product_name}*\n"
        f"Precio: {format_price(price)}\n\n"
        f"Entra a tu sala del live para comprarlo y seguir el chat 👉 {room_url}"
    )
