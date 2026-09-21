"""Etiqueta local de una conversacion (la que agrupa el tablero de Prospeccion)."""


def fill_empty_label(conversation, label: str | None) -> bool:
    """Pone la etiqueta SOLO si la conversacion no tiene ninguna, sin pisar una
    ya existente (ni las manuales como "En captura de cliente"). Devuelve True
    si cambio algo. Antes la etiqueta solo se ponia despues de hablar con
    Chatwoot, asi que las tiendas sin Chatwoot aprovisionado dejaban todas sus
    conversaciones sin etiqueta y el tablero salia vacio."""
    if conversation is None or not label or conversation.current_label:
        return False
    conversation.current_label = label
    return True
