import secrets

import httpx
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_store_access
from app.db import get_ai_db, LiveshopSessionLocal
from app.models import WhatsappInstance
from app.mysql_tools import find_store
from app.schemas import WhatsappStatus
from app.settings_store import get_store_ai_config, save_store_ai_config, clear_chatwoot_config
from app import evolution_client, chatwoot_client

router = APIRouter(prefix="/stores", tags=["whatsapp"])


def _mask(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "*" * len(value)
    return f"{'*' * (len(value) - 4)}{value[-4:]}"


class StoreAiConfigOut(BaseModel):
    store_id: int
    ai_provider: str
    ai_api_key: str
    system_prompt: str
    chatwoot_account_id: int | None
    chatwoot_api_token: str
    chatwoot_inbox_id: int | None
    labels: dict[str, str]
    extra_labels: list[dict]
    missing_fixed_labels: list[str] = []


class StoreAiConfigIn(BaseModel):
    ai_provider: str | None = None
    ai_api_key: str | None = None
    system_prompt: str | None = None
    chatwoot_account_id: int | None = None
    chatwoot_api_token: str | None = None
    label_venta: str | None = None
    label_queja: str | None = None
    label_soporte: str | None = None
    label_no_registrado: str | None = None


def _config_out(cfg) -> StoreAiConfigOut:
    # Cuáles de las 4 fijas hoy NO existen como Label en Chatwoot - se
    # calcula contra el estado real (no algo que se guarde aparte), para que
    # "quitar" sea persistente entre recargas sin desincronizarse nunca de
    # lo que de verdad hay en Chatwoot.
    # Por defecto se asumen TODAS ausentes - las cuentas ya no arrancan con
    # las 4 creadas de una, asi que si Chatwoot no responde (o la cuenta ya
    # ni existe) lo mas seguro es ocultarlas, no mostrarlas como si ya
    # existieran.
    missing_fixed_labels = list(cfg.labels.keys())
    if cfg.chatwoot_account_id:
        try:
            existing_slugs = chatwoot_client.get_existing_label_slugs(cfg.store_id)
            missing_fixed_labels = [
                key for key, title in cfg.labels.items()
                if title and chatwoot_client._slugify(title) not in existing_slugs
            ]
        except httpx.HTTPError:
            pass

    return StoreAiConfigOut(
        store_id=cfg.store_id,
        ai_provider=cfg.ai_provider,
        ai_api_key=_mask(cfg.ai_api_key),
        system_prompt=cfg.system_prompt,
        chatwoot_account_id=cfg.chatwoot_account_id,
        chatwoot_api_token=_mask(cfg.chatwoot_api_token),
        chatwoot_inbox_id=cfg.chatwoot_inbox_id,
        labels=cfg.labels,
        extra_labels=cfg.extra_labels,
        missing_fixed_labels=missing_fixed_labels,
    )


@router.get("/{store_id}/ai-config", response_model=StoreAiConfigOut)
def get_ai_config(store_id: int, _user: dict = Depends(get_current_user)):
    require_store_access(store_id, _user)
    return _config_out(get_store_ai_config(store_id))


@router.put("/{store_id}/ai-config", response_model=StoreAiConfigOut)
def update_ai_config(store_id: int, payload: StoreAiConfigIn, _user: dict = Depends(get_current_user)):
    require_store_access(store_id, _user)
    fields = payload.model_dump(exclude_unset=True)
    if _user.get("role") != "admin":
        # El dueño de tienda (panel principal) solo puede renombrar las 4
        # etiquetas fijas - el proveedor/API key de IA y la cuenta de
        # Chatwoot son infraestructura que administra el equipo de LiveShop.
        fields = {k: v for k, v in fields.items() if k.startswith("label_")}
    save_store_ai_config(store_id, **fields)
    updated = get_store_ai_config(store_id)

    # Si se tocó alguna etiqueta (fija o libre) y la tienda ya tiene cuenta
    # de Chatwoot, se sincroniza de una vez - si no, quedan guardadas solo
    # aquí y nunca aparecen en Chatwoot -> Configuración -> Etiquetas.
    touched_labels = any(k.startswith("label_") for k in fields)
    if touched_labels and updated.chatwoot_account_id:
        try:
            chatwoot_client.sync_labels(store_id, updated.labels, updated.extra_labels)
        except httpx.HTTPError:
            pass  # no bloquea el guardado si Chatwoot no responde

    return _config_out(updated)


@router.post("/{store_id}/ai-config/extra-labels", response_model=StoreAiConfigOut)
def add_extra_label(store_id: int, payload: dict, _user: dict = Depends(get_current_user)):
    """Agrega una etiqueta LIBRE puntual - lee la lista actual del servidor
    (no confía en lo que tenga el navegador en pantalla) para no revivir por
    accidente una que se acabó de borrar justo antes. Queda de PRIMERA en la
    lista (la más reciente arriba, no al final)."""
    require_store_access(store_id, _user)
    title = (payload.get("title") or "").strip()
    color = (payload.get("color") or "#5c6bc0").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Falta el nombre de la etiqueta")
    cfg = get_store_ai_config(store_id)
    if any(t["title"] == title for t in cfg.extra_labels):
        return _config_out(cfg)
    updated_list = [{"title": title, "color": color}, *cfg.extra_labels]
    save_store_ai_config(store_id, extra_labels=updated_list)
    updated = get_store_ai_config(store_id)
    if updated.chatwoot_account_id:
        try:
            # Solo se crea la libre nueva - sin tocar las 4 fijas, si no cada
            # "+ Agregar" revive en Chatwoot las que el vendedor haya borrado.
            chatwoot_client.sync_labels(store_id, {}, updated.extra_labels)
        except httpx.HTTPError:
            pass
    return _config_out(updated)


@router.delete("/{store_id}/ai-config/extra-labels/{title}", response_model=StoreAiConfigOut)
def delete_extra_label(store_id: int, title: str, _user: dict = Depends(get_current_user)):
    """Quita una etiqueta LIBRE puntual - de nuestra lista y, si la tienda ya
    tiene cuenta de Chatwoot, también la borra allá."""
    require_store_access(store_id, _user)
    cfg = get_store_ai_config(store_id)
    remaining = [t for t in cfg.extra_labels if t["title"] != title]
    save_store_ai_config(store_id, extra_labels=remaining)
    if cfg.chatwoot_account_id:
        try:
            chatwoot_client.delete_label(store_id, title)
        except httpx.HTTPError:
            pass
    return _config_out(get_store_ai_config(store_id))


def _create_chatwoot_account(store_id: int, store_name: str) -> None:
    """Crea la cuenta de Chatwoot y su agent bot (con su propio access_token)
    para esta tienda, vía la Platform API - nadie tiene que entrar a la UI de
    Chatwoot ni copiar tokens a mano. Usada tanto por el botón manual como por
    el auto-aprovisionamiento al conectar WhatsApp."""
    account_id = chatwoot_client.provision_account(store_name)
    chatwoot_client.add_admin_to_account(account_id)
    inbox_id = chatwoot_client.create_inbox(account_id, f"{store_name} - WhatsApp IA")
    bot_id, token = chatwoot_client.provision_agent_bot(store_name, account_id)
    chatwoot_client.set_agent_bot(account_id, inbox_id, bot_id)

    save_store_ai_config(
        store_id, chatwoot_account_id=account_id, chatwoot_api_token=token, chatwoot_inbox_id=inbox_id
    )

    # OJO: a proposito NO se sincronizan etiquetas aca - la cuenta debe
    # arrancar en 0 y es la tienda quien las crea desde la pestaña
    # "Etiquetas" ("+ Agregar"), no algo que se le imponga de una.


def _auto_provision_chatwoot_if_needed(store_id: int) -> None:
    """Se llama cada vez que se confirma que el WhatsApp de una tienda quedo
    conectado - si todavia no tiene cuenta de Chatwoot, se la crea sola, para
    que el vendedor no tenga que ir al panel interno a darle "Crear cuenta
    automatica". Si falla (ej. Chatwoot caido), no revienta el estado de
    WhatsApp - se reintenta solo en la proxima consulta de estado."""
    if get_store_ai_config(store_id).chatwoot_account_id:
        return
    db = LiveshopSessionLocal()
    try:
        store = find_store(db, store_id)
    finally:
        db.close()
    if not store:
        return
    try:
        _create_chatwoot_account(store_id, store["name"])
    except httpx.HTTPError:
        pass


@router.post("/{store_id}/chatwoot/provision", response_model=StoreAiConfigOut)
def provision_chatwoot(store_id: int, _user: dict = Depends(get_current_user)):
    """Crea (o recrea) a mano la cuenta de Chatwoot de esta tienda - normalmente
    ya no hace falta, porque queda creada sola al conectar WhatsApp, pero sirve
    para forzar una cuenta nueva si algo salio mal con la automatica."""
    require_store_access(store_id, _user)
    db = LiveshopSessionLocal()
    try:
        store = find_store(db, store_id)
    finally:
        db.close()
    if not store:
        raise HTTPException(status_code=404, detail="Tienda no encontrada en LiveShop")

    # Si ya habia una cuenta de un intento anterior (ej. "Recrear automatico"),
    # se borra primero para no ir acumulando cuentas duplicadas en Chatwoot.
    existing = get_store_ai_config(store_id)
    if existing.chatwoot_account_id:
        try:
            chatwoot_client.delete_account(existing.chatwoot_account_id)
        except httpx.HTTPError:
            pass  # si ya no existia o fallo el borrado, seguimos igual con la creacion

    try:
        _create_chatwoot_account(store_id, store["name"])
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=502,
            detail=(
                "No se pudo aprovisionar en Chatwoot - revisa que el Platform API Key y tu "
                f"token personal de admin (Configuración) esten bien puestos. Detalle: {e}"
            ),
        )

    return _config_out(get_store_ai_config(store_id))


@router.delete("/{store_id}/chatwoot", response_model=StoreAiConfigOut)
def delete_chatwoot(store_id: int, _user: dict = Depends(get_current_user)):
    """Elimina la cuenta de Chatwoot de esta tienda (creada por nosotros o no)
    y limpia los datos guardados localmente."""
    require_store_access(store_id, _user)
    cfg = get_store_ai_config(store_id)
    if cfg.chatwoot_account_id:
        try:
            chatwoot_client.delete_account(cfg.chatwoot_account_id)
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"No se pudo borrar la cuenta en Chatwoot: {e}")
    clear_chatwoot_config(store_id)
    return _config_out(get_store_ai_config(store_id))


def _evolution_error(e: httpx.HTTPError) -> HTTPException:
    detail = f"Evolution API no respondio como se esperaba: {e}"
    return HTTPException(status_code=502, detail=detail)


@router.post("/{store_id}/whatsapp/connect", response_model=WhatsappStatus)
def connect_whatsapp(
    store_id: int,
    db: Session = Depends(get_ai_db),
    _user: dict = Depends(get_current_user),
):
    require_store_access(store_id, _user)
    instance = db.query(WhatsappInstance).filter_by(store_id=store_id).first()
    if not instance:
        instance_name = f"store-{store_id}-{secrets.token_hex(3)}"
        try:
            evolution_client.create_instance(instance_name)
        except httpx.HTTPError as e:
            raise _evolution_error(e)
        # Solo se guarda en nuestra BD si Evolution realmente creo la instancia.
        instance = WhatsappInstance(store_id=store_id, instance_name=instance_name, status="connecting")
        db.add(instance)
        db.commit()
        db.refresh(instance)

    try:
        qr_data = evolution_client.get_connect_qr(instance.instance_name)
    except httpx.HTTPError as e:
        raise _evolution_error(e)

    instance.qr_code = qr_data.get("base64") or qr_data.get("code")
    instance.status = "connecting"
    db.commit()
    db.refresh(instance)
    return instance


@router.post("/{store_id}/whatsapp/rehook")
def rehook_whatsapp(
    store_id: int,
    db: Session = Depends(get_ai_db),
    _user: dict = Depends(get_current_user),
):
    """Reconfigura el webhook de una instancia ya existente - util para
    instancias creadas antes de que create_instance mandara el webhook
    (ej. niqui_fashion)."""
    require_store_access(store_id, _user)
    instance = db.query(WhatsappInstance).filter_by(store_id=store_id).first()
    if not instance:
        raise HTTPException(status_code=404, detail="Esta tienda no tiene instancia de WhatsApp")
    try:
        evolution_client.set_webhook(instance.instance_name)
    except httpx.HTTPError as e:
        raise _evolution_error(e)
    return {"ok": True, "instance_name": instance.instance_name}


@router.post("/{store_id}/whatsapp/disconnect", response_model=WhatsappStatus)
def disconnect_whatsapp(
    store_id: int,
    db: Session = Depends(get_ai_db),
    _user: dict = Depends(get_current_user),
):
    """Cierra la sesion de WhatsApp (hay que volver a escanear QR para
    reconectar) - no borra la instancia, solo la desconecta."""
    require_store_access(store_id, _user)
    instance = db.query(WhatsappInstance).filter_by(store_id=store_id).first()
    if not instance:
        return WhatsappStatus(store_id=store_id, status="disconnected")
    try:
        evolution_client.logout_instance(instance.instance_name)
    except httpx.HTTPError as e:
        raise _evolution_error(e)
    instance.status = "disconnected"
    instance.qr_code = None
    db.commit()
    db.refresh(instance)
    return instance


@router.get("/{store_id}/whatsapp/status", response_model=WhatsappStatus)
def whatsapp_status(
    store_id: int,
    db: Session = Depends(get_ai_db),
    _user: dict = Depends(get_current_user),
):
    require_store_access(store_id, _user)
    instance = db.query(WhatsappInstance).filter_by(store_id=store_id).first()
    if not instance:
        return WhatsappStatus(store_id=store_id, status="disconnected")

    try:
        state = evolution_client.get_connection_state(instance.instance_name)
        instance.status = "connected" if state == "open" else "connecting"
    except httpx.HTTPError:
        # La instancia quedo registrada aca pero Evolution no la reconoce
        # (ej. un intento anterior que fallo a mitad de camino) - se marca
        # como desconectada en vez de reventar el endpoint.
        instance.status = "disconnected"

    if instance.status == "connected":
        instance.qr_code = None
    db.commit()
    db.refresh(instance)

    if instance.status == "connected":
        _auto_provision_chatwoot_if_needed(store_id)

    return instance
