"""Etiqueta local de una conversacion (la que agrupa el tablero de Prospeccion)."""

from app.constants import INTERNAL_LABELS


def fill_empty_label(conversation, label: str | None) -> bool:
    """Pone la etiqueta SOLO si la conversacion no tiene ninguna, sin pisar una
    ya existente (ni las manuales como "En captura de cliente"). Devuelve True
    si cambio algo."""
    if conversation is None or not label or conversation.current_label:
        return False
    conversation.current_label = label
    return True


def apply_classified_label(conversation, label: str | None, fallback_label: str) -> bool:
    """Etiqueta que eligio la IA para el ultimo comentario - se aplica en CADA
    comentario, tenga la tienda Chatwoot/WhatsApp o no (antes, sin Chatwoot,
    solo contaba el primer comentario: quien abria con "hola" quedaba para
    siempre en "Nuevo contacto" aunque despues pidiera algo).
    - Nunca pisa una etiqueta interna/manual ("En captura de cliente"...).
    - Un comentario que no encaja (fallback) no baja a "Nuevo contacto" a
      alguien que ya estaba en una etiqueta real; solo llena si esta vacia.
    Devuelve True si cambio algo."""
    if conversation is None or not label:
        return False
    if conversation.current_label in INTERNAL_LABELS:
        return False
    if label == fallback_label:
        return fill_empty_label(conversation, label)
    if conversation.current_label == label:
        return False
    conversation.current_label = label
    return True
