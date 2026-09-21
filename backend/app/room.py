"""Preguntas que la gente escribe en la SALA del live (chat de la pagina del
cliente), no comentarios de TikTok. Aqui va lo que se puede decidir sin BD ni
red - si la respuesta es publica o privada, que productos nombra la pregunta,
el contexto y el prompt para el LLM - para probarlo aparte (ver tests/)."""

import re

from app import sales

# El agente puede decidir que un mensaje no merece respuesta (un saludo, una
# risa...). En un chat publico contestarle a todo es ruido.
NO_REPLY_TOKEN = "NO_RESPONDER"

MAX_REPLY_CHARS = 300

# Frases que hablan del pedido/pago/envio/datos personales DE ESA PERSONA: la
# respuesta le llega solo a ella (nunca a toda la sala). Se comparan sin
# acentos ni mayusculas.
_PRIVATE_PHRASES = [
    "mi pedido", "mi orden", "mi compra", "mi pago", "mi envio", "mi guia",
    "mi paquete", "mi factura", "mi direccion", "mi numero", "mi telefono",
    "mi cedula", "mi cuenta", "mi reclamo", "mi queja",
    "ya pague", "pague", "pago", "transferencia", "comprobante", "reembolso",
    "devolucion", "devolver", "cancelar", "rastreo", "seguimiento",
    "numero de guia", "cuando llega", "donde esta mi", "no me ha llegado",
    "no me llego", "factura", "queja", "reclamo",
]
_PRIVATE_NORMALIZED = [sales.normalize(p) for p in _PRIVATE_PHRASES]

# Mensajes que no necesitan respuesta y no valen una llamada al LLM.
_SKIP_WORDS = {
    "hola", "holaa", "buenas", "buenos", "buenas noches", "buenas tardes", "buenos dias",
    "jaja", "jajaja", "jajajaja", "jeje", "ok", "okey", "listo", "gracias", "vale",
    "si", "no", "bien", "genial", "wow", "lindo", "hermoso", "bravo",
}

_STOPWORDS = {
    "hola", "buenas", "buenos", "para", "como", "cuanto", "cuesta", "cuanta", "tienen",
    "tiene", "tienes", "hay", "estan", "esta", "esto", "eso", "ese", "esa", "esos",
    "quiero", "quisiera", "puedo", "puede", "pueden", "favor", "precio", "valor",
    "color", "colores", "talla", "tallas", "disponible", "disponibles", "envian",
    "mandan", "del", "los", "las", "una", "uno", "unos", "unas", "con", "por", "que",
    "cual", "cuales", "donde", "cuando", "tambien", "todavia", "aun", "gracias",
}


def classify_visibility(message: str) -> str:
    """'private' si habla del pedido/pago/envio/datos de la persona; 'public'
    para preguntas de producto (que ven todos y sirven como venta social)."""
    haystack = f" {sales.normalize(message)} "
    for phrase in _PRIVATE_NORMALIZED:
        if phrase and f" {phrase} " in haystack:
            return "private"
    return "public"


def should_skip(message: str) -> bool:
    """Saludos sueltos, risas, emojis solos: no se le pregunta al LLM."""
    norm = sales.normalize(message)
    return len(norm) < 3 or norm in _SKIP_WORDS


def _words(text: str) -> set[str]:
    out = set()
    for word in sales.normalize(text).split():
        if len(word) >= 4 and word not in _STOPWORDS:
            out.add(word[:-1] if word.endswith("s") else word)  # plural simple
    return out


def match_products(catalog: list[dict], message: str, limit: int = 3) -> list[dict]:
    """Productos que la pregunta nombra: primero por codigo exacto, luego por
    palabras del nombre/descripcion en comun ('la platera' -> 'Platera de
    ceramica'). Sin coincidencias devuelve []."""
    by_code = sales.match_product_by_code(catalog, message)
    words = _words(message)
    scored: list[tuple[int, dict]] = []
    for product in catalog:
        if by_code and product.get("id") == by_code.get("id"):
            continue
        name_words = _words(product.get("name") or "")
        desc_words = _words(product.get("description") or "")
        score = 2 * len(words & name_words) + len(words & desc_words)
        if score > 0:
            scored.append((score, product))
    scored.sort(key=lambda item: -item[0])
    found = ([by_code] if by_code else []) + [p for _, p in scored]
    return found[:limit]


def _availability(product: dict) -> str:
    in_stock = product.get("inStock", True) and (product.get("stock") or 0) > 0
    return "disponible" if in_stock else "agotado"


def build_context(store_name: str, customer_name: str | None, message: str,
                  matched: list[dict], variants: dict[int, list[dict]],
                  catalog: list[dict], visibility: str) -> str:
    lines = [f"Tienda: {store_name}", f"Cliente: {customer_name or 'cliente'}"]
    if matched:
        lines.append("Productos a los que se refiere la pregunta:")
        for p in matched:
            lines.append(f"- {p['name']} (codigo {p.get('code') or 'sin codigo'}): "
                         f"{sales.format_price(p.get('price'))}, {_availability(p)}")
            if p.get("description"):
                lines.append(f"  Descripcion: {str(p['description'])[:200]}")
            for v in variants.get(p["id"], []):
                parts = [x for x in (v.get("color"), v.get("size")) if x]
                if parts:
                    stock = v.get("stock") or 0
                    lines.append(f"  Variante {' / '.join(parts)}: {'disponible' if stock > 0 else 'agotada'}")
    else:
        lines.append("La pregunta no nombra un producto concreto.")
    sample = [p for p in catalog if _availability(p) == "disponible"][:12]
    if sample:
        lines.append("Otros productos disponibles ahora: " + ", ".join(
            f"{p['name']} ({sales.format_price(p.get('price'))})" for p in sample))
    lines.append(f"La respuesta la vera: {'solo este cliente' if visibility == 'private' else 'toda la sala del live'}.")
    lines.append(f"\nMensaje del cliente: {message}")
    return "\n".join(lines)


def build_system_prompt(base_prompt: str | None, store_name: str) -> str:
    rules = (
        f"\n\nEstas respondiendo en el chat de la sala del live de {store_name}. Reglas:\n"
        "- Responde en espanol, cordial y en maximo 2 frases cortas.\n"
        "- Usa SOLO el contexto dado (precios, disponibilidad, variantes). Si no lo sabes, "
        "di que el vendedor le respondera pronto. No inventes precios, descuentos ni stock.\n"
        "- Para comprar, indica que puede tocar el producto en la sala y agregarlo a su pedido.\n"
        "- Nunca des ni pidas datos personales (telefono, direccion, cedula, pagos).\n"
        f"- Si el mensaje no necesita respuesta (saludo, risa, comentario), responde exactamente {NO_REPLY_TOKEN}."
    )
    return (base_prompt or f"Eres el asistente de ventas de {store_name}.") + rules


def parse_reply(raw: str | None) -> str | None:
    """Limpia lo que devolvio el LLM; None si no hay nada que publicar."""
    text = (raw or "").strip().strip('"').strip()
    if not text or NO_REPLY_TOKEN in text.upper().replace(" ", "_"):
        return None
    if len(text) > MAX_REPLY_CHARS:
        cut = text[:MAX_REPLY_CHARS]
        text = (cut[: cut.rfind(" ")] if " " in cut else cut).rstrip(" ,;:.") + "…"
    return re.sub(r"\s+\n", "\n", text)
