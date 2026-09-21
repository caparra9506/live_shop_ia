"""Flujo del agente de la sala del live: pregunta -> respuesta (o silencio).
Todo lo que toca BD, LLM o logs entra por `RoomAgentDeps`, asi el flujo se
prueba con datos falsos (ver tests/) y el router solo cablea lo real."""

import logging
from dataclasses import dataclass
from typing import Any, Callable

from app import room

logger = logging.getLogger(__name__)

MAX_INPUT_CHARS = 500


@dataclass
class RoomAgentDeps:
    find_store: Callable[[str], dict | None]
    list_catalog: Callable[[int], list[dict]]
    list_variants: Callable[[list[int]], dict[int, list[dict]]]
    get_config: Callable[[int], Any]  # objeto con .system_prompt y .ai_api_key
    invoke: Callable[[Any, str, str], tuple[str, int, int]]  # (texto, tokens_in, tokens_out)
    log: Callable[..., None]


def _result(reply: str | None, visibility: str, skipped: str | None = None) -> dict:
    return {"reply": reply, "visibility": visibility, "skipped": skipped}


def answer(deps: RoomAgentDeps, store_name: str, username: str,
           customer_name: str | None, message: str) -> dict:
    message = (message or "").strip()[:MAX_INPUT_CHARS]
    visibility = room.classify_visibility(message)
    if not message:
        return _result(None, visibility, "vacio")
    if room.should_skip(message):
        return _result(None, visibility, "sin_respuesta_necesaria")

    store = deps.find_store(store_name)
    if not store:
        return _result(None, visibility, "tienda_desconocida")

    cfg = deps.get_config(store["id"])
    if not getattr(cfg, "ai_api_key", ""):
        return _result(None, visibility, "sin_ia")

    catalog = deps.list_catalog(store["id"])
    matched = room.match_products(catalog, message)
    try:
        variants = deps.list_variants([p["id"] for p in matched])
    except Exception:
        # Sin variantes igual se puede contestar precio/disponibilidad
        logger.exception("No se pudieron leer las variantes (store_id=%s)", store["id"])
        variants = {}

    context = room.build_context(store["name"], customer_name, message, matched, variants, catalog, visibility)
    system = room.build_system_prompt(getattr(cfg, "system_prompt", None), store["name"])

    try:
        raw, prompt_tokens, completion_tokens = deps.invoke(cfg, system, context)
    except Exception as exc:
        logger.exception("La IA fallo al responder en la sala (store_id=%s)", store["id"])
        deps.log(store, username, message, cfg, False, 0, 0, str(exc))
        return _result(None, visibility, "error_ia")

    reply = room.parse_reply(raw)
    deps.log(store, username, message, cfg, True, prompt_tokens, completion_tokens, None)
    return _result(reply, visibility, None if reply else "sin_respuesta_necesaria")
