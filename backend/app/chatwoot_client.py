"""Cliente HTTP para Chatwoot - puerto de los nodos HTTP Request que hoy usa
el workflow COMPRE_PUES_SISTEMA_N8N (CHATWOOT - PROFILE / CONVERSATIONS / LABEL).

Cada tienda tiene su propia cuenta (account) dentro del mismo Chatwoot y su
propio token de agente - se resuelven por store_id en cada llamada, no una
sola vez al importar, para que cambiarlos desde el panel aplique al instante."""

import httpx

from app.settings_store import get_infra_settings, get_store_ai_config


def _client(store_id: int) -> httpx.Client:
    """El token de un Agent Bot en Chatwoot no tiene permisos para el API
    general (contactos/conversaciones/labels) - solo sirve para su rol de bot
    en el inbox. Por eso se usa el token PERSONAL del admin (miembro de todas
    las cuentas via add_admin_to_account) para estas llamadas, scopeado por
    account_id. Si no hay admin token configurado, cae al token de la tienda
    (para el caso de pegar datos manuales sin pasar por el aprovisionamiento)."""
    infra = get_infra_settings()
    store_cfg = get_store_ai_config(store_id)
    token = infra.chatwoot_admin_token or store_cfg.chatwoot_api_token
    base = f"{infra.chatwoot_base_url}/api/v1/accounts/{store_cfg.chatwoot_account_id}"
    headers = {"api_access_token": token, "Content-Type": "application/json"}
    return httpx.Client(base_url=base, headers=headers, timeout=15.0)


def find_contact_by_phone(store_id: int, phone: str) -> dict | None:
    with _client(store_id) as client:
        resp = client.get("/contacts/search", params={"q": phone})
        resp.raise_for_status()
        results = resp.json().get("payload", [])
        return results[0] if results else None


def create_contact(store_id: int, phone: str, name: str | None = None) -> dict:
    """`phone` puede ser un telefono real (usuario registrado con WhatsApp) o
    un identificador generico tipo 'tiktok:usuario' (no registrado, sin
    telefono conocido) - Chatwoot valida phone_number como telefono real, asi
    que solo se manda ahi si de verdad parece un numero."""
    is_real_phone = phone.lstrip("+").isdigit()
    payload = {"name": name or phone}
    if is_real_phone:
        payload["phone_number"] = phone if phone.startswith("+") else f"+{phone}"
    else:
        payload["identifier"] = phone
    with _client(store_id) as client:
        resp = client.post("/contacts", json=payload)
        resp.raise_for_status()
        return resp.json().get("payload", {}).get("contact", {})


def find_open_conversation(store_id: int, contact_id: int, inbox_id: int) -> dict | None:
    with _client(store_id) as client:
        resp = client.get(f"/contacts/{contact_id}/conversations")
        resp.raise_for_status()
        conversations = resp.json().get("payload", [])
        for conv in conversations:
            if conv.get("inbox_id") == inbox_id and conv.get("status") != "resolved":
                return conv
        return None


def create_conversation(store_id: int, contact_id: int, inbox_id: int) -> dict:
    with _client(store_id) as client:
        resp = client.post(
            "/conversations",
            json={"contact_id": contact_id, "inbox_id": inbox_id},
        )
        resp.raise_for_status()
        conversation = resp.json()

        # Las conversaciones via API/bot nacen 'pending' en Chatwoot - el
        # 'status' en el body de creacion se ignora, hay que cambiarlo aparte
        # o quedan escondidas en la vista "Pending" (Camilo cree que no
        # existen). No debe tumbar la creacion si este paso extra falla.
        try:
            client.post(
                f"/conversations/{conversation['id']}/toggle_status",
                json={"status": "open"},
            ).raise_for_status()
        except httpx.HTTPError:
            pass

        return conversation


def create_message(store_id: int, conversation_id: int, content: str) -> None:
    """Deja registro en Chatwoot de una respuesta enviada a mano desde el
    panel - message_type 'outgoing' para que se vea como del agente, no del
    cliente."""
    with _client(store_id) as client:
        resp = client.post(
            f"/conversations/{conversation_id}/messages",
            json={"content": content, "message_type": "outgoing"},
        )
        resp.raise_for_status()


import re
import unicodedata


def _slugify(text: str) -> str:
    """Chatwoot exige el 'title' de un Label sin espacios/mayúsculas/acentos
    (da 422 'Title is invalid' si no) - se usa el mismo slug tanto para crear
    el Label como para etiquetar conversaciones, para que ambos coincidan."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return text or "etiqueta"


def set_labels(store_id: int, conversation_id: int, labels: list[str]) -> None:
    with _client(store_id) as client:
        resp = client.post(
            f"/conversations/{conversation_id}/labels",
            json={"labels": [_slugify(label) for label in labels]},
        )
        resp.raise_for_status()


# Colores por defecto para las 4 etiquetas del agente - Chatwoot los pide en
# hex al crear el Label (si no, usa uno random y queda inconsistente con el
# puntico de color que se muestra en nuestro panel).
_LABEL_COLORS = {
    "venta": "#1f9e50",
    "queja": "#e53935",
    "soporte": "#5c6bc0",
    "no_registrado": "#9e9e9e",
}


def get_existing_label_slugs(store_id: int) -> set[str]:
    """Slugs de los Labels que hoy existen de verdad en Chatwoot - para saber
    cuáles de las 4 fijas fueron borradas ahí y mostrarlas como tal en el
    panel de forma persistente (no solo mientras dura la pestaña abierta)."""
    with _client(store_id) as client:
        resp = client.get("/labels")
        resp.raise_for_status()
        return {l["title"] for l in resp.json().get("payload", [])}


def sync_labels(store_id: int, labels: dict[str, str], extra_labels: list[dict] | None = None) -> None:
    """Crea en Chatwoot (como Label real, no solo como texto suelto en una
    conversación) cada una de las etiquetas configuradas para el agente, más
    las "otras etiquetas" libres que agregue el vendedor (cada una con su
    propio color elegido). Solo CREA - nunca borra nada aquí (para eso está
    delete_label, llamado explícitamente cuando el vendedor le da a "quitar"
    una etiqueta puntual), para no arriesgarse a borrar algo que Camilo haya
    creado directo en Chatwoot."""
    with _client(store_id) as client:
        resp = client.get("/labels")
        resp.raise_for_status()
        existing_slugs = {l["title"] for l in resp.json().get("payload", [])}

        def _create(title: str, color: str):
            slug = _slugify(title)
            if not title or slug in existing_slugs:
                return
            try:
                client.post(
                    "/labels",
                    json={
                        "title": slug,
                        "description": title,
                        "color": color,
                        "show_on_sidebar": True,
                    },
                ).raise_for_status()
                existing_slugs.add(slug)
            except httpx.HTTPError:
                # Si esta etiqueta puntual falla (ej. un hipo de Chatwoot), no
                # debe tumbar la creación de las demás - si no, un solo fallo
                # aborta el resto del lote silenciosamente y quedan a medias.
                pass

        for key, title in labels.items():
            _create(title, _LABEL_COLORS.get(key, "#5c6bc0"))
        for item in extra_labels or []:
            _create(item["title"], item.get("color") or "#5c6bc0")


def delete_label(store_id: int, title: str) -> None:
    """Borra una etiqueta LIBRE puntual de Chatwoot - se llama solo cuando el
    vendedor le da a "quitar" esa etiqueta específica en el panel, nunca de
    forma automática/masiva."""
    slug = _slugify(title)
    with _client(store_id) as client:
        resp = client.get("/labels")
        resp.raise_for_status()
        match = next((l for l in resp.json().get("payload", []) if l["title"] == slug), None)
        if match:
            client.delete(f"/labels/{match['id']}").raise_for_status()


# --- Platform API: aprovisionamiento automatico de cuenta + bot por tienda ---
# Requiere el token de un "Platform App" (Super Admin -> Platform Apps -> Access
# Tokens), configurado UNA sola vez como infraestructura, no por tienda. Con
# eso se puede crear la cuenta y su agent bot (con access_token propio) sin
# que nadie tenga que entrar a la UI de Chatwoot por cada tienda nueva.
def _platform_client() -> httpx.Client:
    infra = get_infra_settings()
    headers = {
        "api_access_token": infra.chatwoot_platform_api_key,
        "Content-Type": "application/json",
    }
    return httpx.Client(base_url=f"{infra.chatwoot_base_url}/platform/api/v1", headers=headers, timeout=15.0)


def provision_account(store_name: str) -> int:
    with _platform_client() as client:
        resp = client.post("/accounts", json={"name": store_name})
        resp.raise_for_status()
        return resp.json()["id"]


def delete_account(account_id: int) -> None:
    with _platform_client() as client:
        resp = client.delete(f"/accounts/{account_id}")
        resp.raise_for_status()


def provision_agent_bot(store_name: str, account_id: int) -> tuple[int, str]:
    """Devuelve (agent_bot_id, access_token)."""
    with _platform_client() as client:
        resp = client.post(
            "/agent_bots",
            json={"name": f"{store_name} - agente IA", "account_id": account_id},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["id"], data["access_token"]


def create_automation_user() -> tuple[int, str]:
    """Crea un usuario DEDICADO (no la cuenta personal de Camilo) via Platform
    API - es la unica forma confirmada de obtener un access_token sin entrar
    a la UI de Chatwoot a mano (el endpoint de creacion lo devuelve en la
    respuesta; leer el token de un usuario YA existente vía Platform API da
    401 "Non permissible resource" porque ese usuario no fue creado por este
    Platform App). Este usuario se usa luego como admin de cada cuenta nueva."""
    import secrets

    # Chatwoot exige mayúscula, minúscula, número y carácter especial -
    # token_urlsafe no garantiza un especial, por eso se fuerza uno al final.
    password = secrets.token_urlsafe(20) + "aA1!"
    with _platform_client() as client:
        resp = client.post(
            "/users",
            json={
                "name": "LiveShop Automation",
                "display_name": "LiveShop Automation",
                "email": "liveshop-automation@liveshop.com.co",
                "password": password,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["id"], data["access_token"]


def add_admin_to_account(account_id: int) -> None:
    """Le da rol de administrador, en la cuenta nueva, al usuario dueno del
    token de admin configurado en infra (el que crea el inbox despues, ya que
    el agent bot no tiene permisos de administrador) Y a Camilo
    (chatwoot_owner_user_id) - sin esto, la cuenta queda solo a nombre del
    usuario de automatización y nadie puede verla en la UI de Chatwoot."""
    infra = get_infra_settings()
    admin_user_id = _get_admin_user_id()
    user_ids = {admin_user_id}
    if infra.chatwoot_owner_user_id:
        user_ids.add(infra.chatwoot_owner_user_id)

    with _platform_client() as client:
        for user_id in user_ids:
            resp = client.post(
                f"/accounts/{account_id}/account_users",
                json={"user_id": user_id, "role": "administrator"},
            )
            resp.raise_for_status()


def _get_admin_user_id() -> int:
    infra = get_infra_settings()
    with httpx.Client(
        base_url=f"{infra.chatwoot_base_url}/api/v1",
        headers={"api_access_token": infra.chatwoot_admin_token},
        timeout=15.0,
    ) as client:
        resp = client.get("/profile")
        resp.raise_for_status()
        return resp.json()["id"]


def _admin_client(account_id: int) -> httpx.Client:
    infra = get_infra_settings()
    return httpx.Client(
        base_url=f"{infra.chatwoot_base_url}/api/v1/accounts/{account_id}",
        headers={"api_access_token": infra.chatwoot_admin_token, "Content-Type": "application/json"},
        timeout=15.0,
    )


def create_inbox(account_id: int, name: str) -> int:
    with _admin_client(account_id) as client:
        resp = client.post("/inboxes", json={"name": name, "channel": {"type": "api"}})
        resp.raise_for_status()
        return resp.json()["id"]


def set_agent_bot(account_id: int, inbox_id: int, agent_bot_id: int) -> None:
    with _admin_client(account_id) as client:
        resp = client.post(f"/inboxes/{inbox_id}/set_agent_bot", json={"agent_bot": agent_bot_id})
        resp.raise_for_status()
