"""Resuelve config editable desde el panel:
- get_infra_settings(): Evolution API key / Chatwoot URL - compartido, infra.
- get_store_ai_config(store_id) / save_store_ai_config(...): por tienda -
  proveedor/API key de IA, prompt del agente, cuenta de Chatwoot propia.
Todo cae de vuelta al .env (app.config) si no esta seteado en BD, salvo lo
que es inherentemente por tienda (ahi no hay fallback razonable)."""

import json
from dataclasses import dataclass

from app.config import settings as env_settings
from app.db import AiSessionLocal
from app.models import AppSettings, StoreAiConfig

DEFAULT_SYSTEM_PROMPT = (
    "Eres el asistente de ventas por WhatsApp de esta tienda de TikTok Live. "
    "Responde de forma breve, amable y directa, ayudando al cliente a encontrar "
    "el producto que busca o a resolver su duda."
)


@dataclass
class InfraSettings:
    evolution_api_key: str
    chatwoot_base_url: str
    chatwoot_public_url: str
    chatwoot_platform_api_key: str
    chatwoot_admin_token: str
    chatwoot_owner_user_id: int | None


def get_infra_settings() -> InfraSettings:
    db = AiSessionLocal()
    try:
        row = db.query(AppSettings).filter_by(id=1).first()
        base_url = row.chatwoot_base_url if row and row.chatwoot_base_url else env_settings.chatwoot_base_url
        return InfraSettings(
            evolution_api_key=(row.evolution_api_key if row and row.evolution_api_key else env_settings.evolution_api_key),
            chatwoot_base_url=base_url,
            chatwoot_public_url=(row.chatwoot_public_url if row and row.chatwoot_public_url else base_url),
            chatwoot_platform_api_key=(
                row.chatwoot_platform_api_key
                if row and row.chatwoot_platform_api_key
                else env_settings.chatwoot_platform_api_key
            ),
            chatwoot_admin_token=(
                row.chatwoot_admin_token if row and row.chatwoot_admin_token else env_settings.chatwoot_admin_token
            ),
            chatwoot_owner_user_id=(row.chatwoot_owner_user_id if row else None),
        )
    finally:
        db.close()


def save_infra_settings(**fields) -> None:
    db = AiSessionLocal()
    try:
        row = db.query(AppSettings).filter_by(id=1).first()
        if not row:
            row = AppSettings(id=1)
            db.add(row)
        for key, value in fields.items():
            if value is not None and value != "":
                setattr(row, key, value)
        db.commit()
    finally:
        db.close()


DEFAULT_LABELS = {
    "venta": "Venta",
    "queja": "Queja",
    "soporte": "Soporte",
    "no_registrado": "Nuevo contacto",
}


@dataclass
class StoreAiSettings:
    store_id: int
    ai_provider: str
    ai_api_key: str
    system_prompt: str
    chatwoot_account_id: int | None
    chatwoot_api_token: str
    chatwoot_inbox_id: int | None
    labels: dict[str, str]
    extra_labels: list[dict]  # [{"title": str, "color": str}]


def get_store_ai_config(store_id: int) -> StoreAiSettings:
    db = AiSessionLocal()
    try:
        row = db.query(StoreAiConfig).filter_by(store_id=store_id).first()
        extra_labels = []
        if row and row.extra_labels_json:
            try:
                raw = json.loads(row.extra_labels_json)
            except (ValueError, TypeError):
                raw = []
            # Compatibilidad: versión vieja guardaba solo strings, la nueva
            # guarda {title, color} para poder elegir color por etiqueta.
            extra_labels = [
                item if isinstance(item, dict) else {"title": item, "color": "#5c6bc0"}
                for item in raw
            ]
        # provider y api_key van SIEMPRE emparejados - si la tienda no puso su
        # propia key, se usan los dos del default juntos (nunca mezclar el
        # provider guardado, que puede ser solo el default de la columna en
        # BD ej. 'openai', con la key de otro proveedor).
        if row and row.ai_api_key:
            ai_provider = row.ai_provider or env_settings.default_ai_provider
            ai_api_key = row.ai_api_key
        else:
            ai_provider = env_settings.default_ai_provider
            ai_api_key = env_settings.default_ai_api_key

        return StoreAiSettings(
            store_id=store_id,
            ai_provider=ai_provider,
            ai_api_key=ai_api_key,
            system_prompt=(row.system_prompt if row and row.system_prompt else DEFAULT_SYSTEM_PROMPT),
            chatwoot_account_id=(row.chatwoot_account_id if row else None),
            chatwoot_api_token=(row.chatwoot_api_token if row and row.chatwoot_api_token else env_settings.chatwoot_api_token),
            chatwoot_inbox_id=(row.chatwoot_inbox_id if row else None),
            labels={
                "venta": (row.label_venta if row and row.label_venta else DEFAULT_LABELS["venta"]),
                "queja": (row.label_queja if row and row.label_queja else DEFAULT_LABELS["queja"]),
                "soporte": (row.label_soporte if row and row.label_soporte else DEFAULT_LABELS["soporte"]),
                "no_registrado": (
                    row.label_no_registrado if row and row.label_no_registrado else DEFAULT_LABELS["no_registrado"]
                ),
            },
            extra_labels=extra_labels,
        )
    finally:
        db.close()


def save_store_ai_config(store_id: int, **fields) -> StoreAiConfig:
    db = AiSessionLocal()
    try:
        row = db.query(StoreAiConfig).filter_by(store_id=store_id).first()
        if not row:
            row = StoreAiConfig(store_id=store_id)
            db.add(row)
        if "extra_labels" in fields:
            extra_labels = fields.pop("extra_labels")
            if extra_labels is not None:
                row.extra_labels_json = json.dumps(extra_labels)
        for key, value in fields.items():
            if value is not None and value != "":
                setattr(row, key, value)
        db.commit()
        db.refresh(row)
        return row
    finally:
        db.close()


def clear_chatwoot_config(store_id: int) -> None:
    """Borra la cuenta/token/inbox de Chatwoot guardados para esta tienda -
    se usa cuando se elimina la cuenta del lado de Chatwoot tambien."""
    db = AiSessionLocal()
    try:
        row = db.query(StoreAiConfig).filter_by(store_id=store_id).first()
        if row:
            row.chatwoot_account_id = None
            row.chatwoot_api_token = None
            row.chatwoot_inbox_id = None
            db.commit()
    finally:
        db.close()
