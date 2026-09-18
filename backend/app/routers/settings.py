import httpx
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_user
from app.settings_store import get_infra_settings, save_infra_settings
from app import chatwoot_client

router = APIRouter(prefix="/settings", tags=["settings"])


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "*" * len(value)
    return f"{'*' * (len(value) - 4)}{value[-4:]}"


class InfraSettingsOut(BaseModel):
    evolution_api_key: str
    chatwoot_base_url: str
    chatwoot_public_url: str
    chatwoot_platform_api_key: str
    chatwoot_admin_token: str
    chatwoot_owner_user_id: int | None


class InfraSettingsIn(BaseModel):
    evolution_api_key: str | None = None
    chatwoot_base_url: str | None = None
    chatwoot_public_url: str | None = None
    chatwoot_platform_api_key: str | None = None
    chatwoot_admin_token: str | None = None
    chatwoot_owner_user_id: int | None = None


def _out(cfg) -> InfraSettingsOut:
    return InfraSettingsOut(
        evolution_api_key=_mask(cfg.evolution_api_key),
        chatwoot_base_url=cfg.chatwoot_base_url,
        chatwoot_public_url=cfg.chatwoot_public_url,
        chatwoot_platform_api_key=_mask(cfg.chatwoot_platform_api_key),
        chatwoot_admin_token=_mask(cfg.chatwoot_admin_token),
        chatwoot_owner_user_id=cfg.chatwoot_owner_user_id,
    )


@router.get("", response_model=InfraSettingsOut)
def read_settings(_user: dict = Depends(get_current_user)):
    return _out(get_infra_settings())


@router.put("", response_model=InfraSettingsOut)
def update_settings(payload: InfraSettingsIn, _user: dict = Depends(get_current_user)):
    save_infra_settings(**payload.model_dump(exclude_unset=True))
    return _out(get_infra_settings())


@router.post("/chatwoot/create-automation-user", response_model=InfraSettingsOut)
def create_chatwoot_automation_user(_user: dict = Depends(get_current_user)):
    """Reemplaza el paso manual de 'Perfil -> Control de acceso a la API':
    crea un usuario dedicado via Platform API y guarda su token de una vez."""
    infra = get_infra_settings()
    if not infra.chatwoot_platform_api_key:
        raise HTTPException(status_code=400, detail="Configura primero el Platform API Key")
    try:
        _user_id, access_token = chatwoot_client.create_automation_user()
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502,
            detail=f"No se pudo crear el usuario de automatización en Chatwoot: {e.response.text}",
        )
    save_infra_settings(chatwoot_admin_token=access_token)
    return _out(get_infra_settings())
