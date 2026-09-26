"""Enlace WhatsApp <-> usuario de TikTok.

Durante el live (o poco despues) los clientes le escriben por su cuenta al
WhatsApp de la tienda. Si el numero no lo conocemos, se le pregunta su @ de
TikTok; al responderlo se une con la conversacion de sus comentarios del live
(que ya existe, agrupada por el usuario de TikTok), asi el vendedor ve en el
chat todo lo que esa persona pidio en el live. Detras del interruptor
WHATSAPP_TIKTOK_LINK_ENABLED."""

import logging
import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher

import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import evolution_client
from app.config import settings
from app.constants import REGISTERED_LABEL
from app.db import LiveshopSessionLocal
from app.models import Conversation, Message, StoreMessageTemplate, WhatsappInstance
from app.mysql_tools import (
    find_store_tiktok_user,
    find_tiktok_handles_by_name,
    find_tiktok_user_by_phone,
    store_live_info,
)

logger = logging.getLogger(__name__)

# contact_phone de una conversacion de WhatsApp que todavia no sabemos de que
# usuario de TikTok es (los comentarios del live usan el @ como llave).
PENDING_PREFIX = "wa:"

# Despues de terminar el live se sigue preguntando el @ este tiempo (la gente
# escribe al rato de ver el live).
LINK_WINDOW_HOURS = 12

# Mensajes automaticos maximos a un mismo numero sin enlazar dentro de
# BOT_WINDOW_MINUTES: la pregunta y un reintento. Pasado ese rato, si vuelve a
# escribir, se le pregunta de nuevo (antes se quedaba callado para siempre).
MAX_BOT_MESSAGES = 2
BOT_WINDOW_MINUTES = 20

# Un @ mal escrito ("artesaniagenial" por "artesaniasgeniales") se acepta si se
# parece asi de mucho a uno solo de los que comentaron en el live reciente.
SIMILAR_MIN_RATIO = 0.85
SIMILAR_MARGIN = 0.05
RECENT_COMMENTS_HOURS = 36

ASK_TEXT = (
    "¡Hola! 👋 Gracias por escribirnos. Para ayudarte con lo que viste en el live, "
    "¿nos compartes tu usuario de TikTok (ej: @tuusuario) o el nombre con el que "
    "apareces en el live?"
)
FOUND_TEXT = "¡Listo, @{username}! Ya te encontramos 🙌 En un momento te ayudamos con lo que pediste en el live."
NOT_FOUND_TEXT = (
    "No te encontramos entre los comentarios del live 🤔 "
    "¿Nos confirmas tu usuario de TikTok tal cual aparece en tu perfil? (ej: @tuusuario)"
)
CONFIRM_TEXT = (
    "¿Eres tú? 👉 https://www.tiktok.com/@{username}\n"
    "Respóndenos *SÍ* para confirmar, o escríbenos tu usuario correcto."
)
CONFIRM_NEW_TEXT = (
    "Todavía no te vemos en los comentarios del live 👀 ¿Este es tu perfil? 👉 "
    "https://www.tiktok.com/@{username}\n"
    "Respóndenos *SÍ* y lo guardamos para reconocerte en los próximos lives."
)
SAVED_TEXT = (
    "¡Listo, @{username}! Guardamos tu usuario 🙌 Si estás viendo el live, escríbenos "
    "un comentario allá con lo que te gustó y te atendemos por aquí. "
    "En los próximos lives ya te reconocemos."
)


def ask_text(db: Session, store_id: int, name: str | None = None) -> str:
    """Primer mensaje al número desconocido: el que armó la tienda en su panel
    (WhatsApp → mensaje para pedir el @) o ASK_TEXT. {nombre} = nombre del
    perfil de WhatsApp; si no hay, se quita sin dejar espacios raros."""
    row = db.get(StoreMessageTemplate, store_id)
    template = row.retention_copy if row and row.retention_copy else ASK_TEXT
    name = (name or "").strip()
    if name:
        return template.replace("{nombre}", name)
    return re.sub(r"[ \t]*\{nombre\}", "", template)


RETRY_TEXT = "Entonces, ¿cuál es tu usuario de TikTok? (ej: @tuusuario)"
AMBIGUOUS_TEXT = (
    "Hay varias personas con ese nombre en el live 😅 "
    "¿Nos compartes tu usuario de TikTok? (ej: @tuusuario)"
)

_AT_USERNAME = re.compile(r"@([A-Za-z0-9_.]{2,24})")
_BARE_USERNAME = re.compile(r"[A-Za-z0-9_.]{2,24}")
_PROPOSED = re.compile(r"tiktok\.com/@([A-Za-z0-9_.]+)")
_YES = re.compile(
    r"^(s[ií]+|yes|correcto|exacto|claro|dale|ok|okay|as[ií] es|soy yo|es correcto|ese|esa|esa soy yo|👍|✅)\b",
    re.IGNORECASE,
)
_YES_EMOJI = ("👍", "✅")
_NO = re.compile(r"^(no|nop|nel|negativo|ese no|esa no)\b", re.IGNORECASE)
_NAME_PREFIX = re.compile(r"^(hola[,!.\s]*)?(yo\s+)?(soy|me\s+llamo|mi\s+nombre\s+es|es)\s+", re.IGNORECASE)


def parse_username(text: str, allow_bare: bool) -> str | None:
    """Saca el usuario de TikTok de un mensaje: "@fulana", "soy @fulana.23", o
    (allow_bare, cuando ya se le pregunto) una sola palabra como "fulana"."""
    match = _AT_USERNAME.search(text)
    if match:
        return match.group(1).rstrip(".") or None
    candidate = text.strip()
    if allow_bare and _BARE_USERNAME.fullmatch(candidate) and any(ch.isalpha() for ch in candidate):
        return candidate.rstrip(".")
    return None


def parse_name(text: str) -> str | None:
    """Nombre visible de TikTok escrito a mano: "Camilo Ochoa", "soy Niqui 🌸".
    Solo frases cortas; un mensaje largo no es un nombre."""
    candidate = _NAME_PREFIX.sub("", text.strip())
    candidate = re.sub(r"[%_\\]", "", candidate)  # comodines de LIKE
    candidate = candidate.strip(" \t\n.,;:!¡?¿\"'")
    if not 3 <= len(candidate) <= 60 or len(candidate.split()) > 5:
        return None
    return candidate if any(ch.isalpha() for ch in candidate) else None


def live_recently_active(store_id: int) -> bool:
    db = LiveshopSessionLocal()
    try:
        info = store_live_info(db, store_id)
    finally:
        db.close()
    if not info:
        return False
    if info.get("liveStatus") in ("connected", "connecting"):
        return True
    ended = info.get("liveDisconnectedAt")
    # MySQL devuelve fecha sin zona; la ventana es amplia, unas horas de
    # diferencia de zona no cambian la decision.
    return bool(ended) and datetime.utcnow() - ended < timedelta(hours=LINK_WINDOW_HOURS)


def _find_tiktok_conversation(db: Session, store_id: int, username: str) -> Conversation | None:
    return (
        db.query(Conversation)
        .filter(
            Conversation.store_id == store_id,
            func.lower(Conversation.contact_phone) == username.lower(),
        )
        .order_by(Conversation.created_at.desc())
        .first()
    )


def _find_similar_conversation(db: Session, store_id: int, username: str) -> Conversation | None:
    """Conversacion de comentarios reciente cuyo @ se parece al que escribio la
    persona. Solo si hay un unico parecido claro; si hay dos cerca, ninguno."""
    since = datetime.utcnow() - timedelta(hours=RECENT_COMMENTS_HOURS)
    candidates = (
        db.query(Conversation)
        .join(Message, Message.conversation_id == Conversation.id)
        .filter(
            Conversation.store_id == store_id,
            ~Conversation.contact_phone.startswith(PENDING_PREFIX),
            Message.direction == "in",
            Message.created_at >= since,
        )
        .distinct()
        .all()
    )
    wanted = username.lower()
    scored = sorted(
        ((SequenceMatcher(None, wanted, c.contact_phone.lower()).ratio(), c) for c in candidates),
        key=lambda pair: pair[0],
        reverse=True,
    )
    if not scored or scored[0][0] < SIMILAR_MIN_RATIO:
        return None
    if len(scored) > 1 and scored[1][0] > scored[0][0] - SIMILAR_MARGIN:
        return None
    return scored[0][1]


def _register_in_liveshop(store_id: int, tiktok: str, phone: str, name: str | None) -> None:
    """Deja el telefono en tik_tok_user (via NestJS, nunca directo a MySQL)
    para que el agente del live ya pueda mandarle ofertas por WhatsApp."""
    if not settings.internal_api_key:
        logger.warning("Sin INTERNAL_API_KEY: @%s quedo enlazado solo en el panel", tiktok)
        return
    digits = "".join(ch for ch in phone if ch.isdigit())
    short = digits[2:] if len(digits) == 12 and digits.startswith("57") else digits
    try:
        resp = httpx.post(
            f"{settings.liveshop_backend_url}/api/tiktokuser/internal/link-whatsapp",
            json={"storeId": store_id, "tiktok": tiktok, "phone": short, "name": name or None},
            headers={"X-Internal-Key": settings.internal_api_key},
            timeout=10.0,
        )
        resp.raise_for_status()
    except httpx.HTTPError:
        logger.exception("No se pudo registrar el WhatsApp de @%s en LiveShop (store_id=%s)", tiktok, store_id)


def _mark_registered(conversation: Conversation) -> None:
    # Import local: el router importa medio backend y este modulo lo usa el webhook.
    from app.routers.conversations import _apply_internal_label

    db = Session.object_session(conversation)
    _apply_internal_label(db, conversation, REGISTERED_LABEL, "#22c55e")


def _send(db: Session, instance: WhatsappInstance, conversation: Conversation, text: str) -> None:
    try:
        evolution_client.send_text(instance.instance_name, conversation.whatsapp_phone, text)
    except httpx.HTTPError:
        logger.exception("No se pudo enviar el mensaje de enlace a %s", conversation.whatsapp_phone)
        return
    db.add(Message(conversation_id=conversation.id, direction="out", body=text))
    db.commit()


def _link(db: Session, pending: Conversation, target: Conversation) -> Conversation:
    """Pasa los mensajes de WhatsApp de la conversacion temporal a la del
    usuario de TikTok (donde ya estan sus comentarios del live) y borra la
    temporal."""
    db.query(Message).filter(Message.conversation_id == pending.id).update(
        {Message.conversation_id: target.id}, synchronize_session=False
    )
    target.whatsapp_phone = pending.whatsapp_phone
    target.contact_name = target.contact_name or pending.contact_name
    db.delete(pending)
    db.commit()
    db.refresh(target)
    return target


def _linkable_target(db: Session, pending: Conversation, username: str, similar: bool) -> Conversation | None:
    target = _find_tiktok_conversation(db, pending.store_id, username)
    if not target and similar:
        target = _find_similar_conversation(db, pending.store_id, username)
        # Si ya se le propuso ese parecido y dijo que no, no se insiste.
        if target and target.contact_phone.lower() in _proposed_before(db, pending):
            target = None
    if not target or target.contact_phone.startswith(PENDING_PREFIX):
        return None
    if target.whatsapp_phone and target.whatsapp_phone != pending.whatsapp_phone:
        # Ya enlazado a otro numero: no se le quita a nadie su conversacion,
        # lo resuelve el vendedor.
        logger.warning("@%s ya esta enlazado a otro WhatsApp (store_id=%s)", username, pending.store_id)
        return None
    return target


def _proposed_username(db: Session, pending: Conversation) -> str | None:
    """@ que se le propuso en el ultimo mensaje automatico, si ese fue una
    confirmacion ("¿Eres tu? tiktok.com/@...")."""
    last_out = (
        db.query(Message.body)
        .filter(Message.conversation_id == pending.id, Message.direction == "out")
        .order_by(Message.id.desc())
        .first()
    )
    match = _PROPOSED.search(last_out[0]) if last_out else None
    return match.group(1) if match else None


def _proposed_before(db: Session, pending: Conversation) -> set[str]:
    bodies = (
        db.query(Message.body)
        .filter(Message.conversation_id == pending.id, Message.direction == "out")
        .all()
    )
    return {m.group(1).lower() for (body,) in bodies for m in _PROPOSED.finditer(body)}


def _taken_by_other_phone(store_id: int, username: str, whatsapp_phone: str) -> bool:
    """El @ ya esta registrado en la tienda con otro WhatsApp."""
    ls_db = LiveshopSessionLocal()
    try:
        user = find_store_tiktok_user(ls_db, store_id, username)
    finally:
        ls_db.close()
    if not user or not user.get("phone"):
        return False
    return evolution_client.normalize_phone(user["phone"]) != whatsapp_phone


def _try_link(
    db: Session, instance: WhatsappInstance, pending: Conversation, username: str, allow_new: bool = False
) -> bool:
    """Encontro a quien podria ser: le manda su perfil de TikTok para que
    confirme. Todavia no enlaza ni registra nada. Con allow_new (escribio un
    @ explicito) se le pregunta aunque no haya comentado en el live: al
    confirmar se guarda su @ para reconocerlo en los proximos lives."""
    target = _linkable_target(db, pending, username, similar=True)
    if target:
        _send(db, instance, pending, CONFIRM_TEXT.format(username=target.contact_phone))
        return True
    if not allow_new or _find_tiktok_conversation(db, pending.store_id, username):
        return False
    _send(db, instance, pending, CONFIRM_NEW_TEXT.format(username=username.lower()))
    return True


def _save_new_username(db: Session, instance: WhatsappInstance, pending: Conversation, username: str) -> bool:
    """Confirmo un @ que todavia no comento en el live: la conversacion
    temporal pasa a ser la de ese @ (asi sus comentarios futuros caen aqui) y
    queda registrado en tik_tok_user con su WhatsApp."""
    username = username.lower()
    if _taken_by_other_phone(pending.store_id, username, pending.whatsapp_phone):
        logger.warning("@%s ya esta registrado con otro WhatsApp (store_id=%s)", username, pending.store_id)
        return False
    pending.contact_phone = username
    db.commit()
    _mark_registered(pending)
    _register_in_liveshop(pending.store_id, username, pending.whatsapp_phone, pending.contact_name)
    _send(db, instance, pending, SAVED_TEXT.format(username=username))
    return True


def _confirm_link(db: Session, instance: WhatsappInstance, pending: Conversation, username: str) -> bool:
    """La persona dijo que si es ella: se une y se registra."""
    target = _linkable_target(db, pending, username, similar=False)
    if not target:
        if _find_tiktok_conversation(db, pending.store_id, username):
            return False  # existe pero es de otro numero
        return _save_new_username(db, instance, pending, username)
    target = _link(db, pending, target)
    _mark_registered(target)
    _register_in_liveshop(target.store_id, target.contact_phone, target.whatsapp_phone, target.contact_name)
    _send(db, instance, target, FOUND_TEXT.format(username=target.contact_phone))
    return True


def _handles_by_name(db: Session, store_id: int, name: str) -> list[str]:
    """@ del live cuyo nombre visible coincide y que tienen conversacion de
    comentarios en esta tienda."""
    ls_db = LiveshopSessionLocal()
    try:
        handles = find_tiktok_handles_by_name(ls_db, store_id, name)
    except Exception:
        logger.exception("No se pudo buscar por nombre %r (store_id=%s)", name, store_id)
        return []
    finally:
        ls_db.close()
    return [h for h in handles if _find_tiktok_conversation(db, store_id, h)]


def handle_unknown_sender(
    db: Session, instance: WhatsappInstance, phone: str, text: str, push_name: str | None
) -> dict:
    """WhatsApp de un numero que no tiene conversacion todavia."""
    if not settings.whatsapp_tiktok_link_enabled:
        return {"ignored": "el numero no corresponde a ningun cliente registrado"}

    store_id = instance.store_id
    whatsapp_phone = evolution_client.normalize_phone(phone)

    # Cliente que ya dio su numero antes (registro o "Guardar cliente"): se
    # enlaza directo, sin preguntarle nada.
    ls_db = LiveshopSessionLocal()
    try:
        known = find_tiktok_user_by_phone(ls_db, store_id, phone)
    finally:
        ls_db.close()
    if known:
        target = _find_tiktok_conversation(db, store_id, known["tiktok"])
        if not target:
            target = Conversation(store_id=store_id, contact_phone=known["tiktok"])
            db.add(target)
        if not target.whatsapp_phone:
            target.whatsapp_phone = whatsapp_phone
        target.contact_name = target.contact_name or known.get("name") or push_name
        db.commit()
        db.add(Message(conversation_id=target.id, direction="in", body=text))
        db.commit()
        return {"ok": True, "linked": known["tiktok"]}

    if not live_recently_active(store_id):
        return {"ignored": "numero desconocido fuera del live"}

    pending = Conversation(
        store_id=store_id,
        contact_phone=f"{PENDING_PREFIX}{whatsapp_phone}",
        whatsapp_phone=whatsapp_phone,
        contact_name=(push_name or "")[:120] or None,
    )
    db.add(pending)
    db.commit()
    db.add(Message(conversation_id=pending.id, direction="in", body=text))
    db.commit()

    # "Hola, soy @fulana" en el primer mensaje: no hace falta preguntar.
    username = parse_username(text, allow_bare=False)
    if username and _try_link(db, instance, pending, username, allow_new=True):
        return {"ok": True, "confirming": username}

    _send(db, instance, pending, ask_text(db, store_id, push_name))
    return {"ok": True, "asked_tiktok": True}


def handle_pending(db: Session, instance: WhatsappInstance, pending: Conversation, text: str) -> dict:
    """Respuesta de alguien a quien ya se le pregunto su @."""
    db.add(Message(conversation_id=pending.id, direction="in", body=text))
    db.commit()
    if not settings.whatsapp_tiktok_link_enabled:
        return {"ok": True, "pending": True}

    # Las confirmaciones no cuentan para el tope: son respuesta a lo que dijo.
    bot_messages = (
        db.query(func.count(Message.id))
        .filter(
            Message.conversation_id == pending.id,
            Message.direction == "out",
            ~Message.body.contains("tiktok.com/@"),
            Message.created_at >= datetime.utcnow() - timedelta(minutes=BOT_WINDOW_MINUTES),
        )
        .scalar()
    )

    proposed = _proposed_username(db, pending)
    answer = text.strip()
    if proposed and (_YES.match(answer) or answer.startswith(_YES_EMOJI)):
        if _confirm_link(db, instance, pending, proposed):
            return {"ok": True, "linked": proposed}
    elif proposed and _NO.match(answer) and "@" not in answer:
        if bot_messages < MAX_BOT_MESSAGES + 1:
            _send(db, instance, pending, RETRY_TEXT)
        return {"ok": True, "pending": True}

    username = parse_username(text, allow_bare=True)
    if username and _try_link(db, instance, pending, username, allow_new="@" in text):
        return {"ok": True, "confirming": username}

    # Sin @: puede ser el nombre con el que sale en el live.
    # Si hace rato no le escribimos, se arranca de nuevo con la pregunta.
    reply = NOT_FOUND_TEXT if bot_messages else ask_text(db, pending.store_id, pending.contact_name)
    name = None if "@" in text else parse_name(text)
    if name:
        handles = _handles_by_name(db, pending.store_id, name)
        if len(handles) == 1 and _try_link(db, instance, pending, handles[0]):
            return {"ok": True, "confirming": handles[0], "by_name": name}
        if len(handles) > 1:
            reply = AMBIGUOUS_TEXT

    if bot_messages < MAX_BOT_MESSAGES:
        _send(db, instance, pending, reply)
    return {"ok": True, "pending": True}


def link_pending_on_comment(db: Session, store_id: int, username: str) -> str | None:
    """Llega un comentario del live de @username: si alguien por WhatsApp dio
    ese @ (o uno muy parecido) antes de comentar y quedo sin enlazar, se le
    pide confirmar ahora. Devuelve el WhatsApp al que se le pregunto o None."""
    if not settings.whatsapp_tiktok_link_enabled:
        return None
    pendings = (
        db.query(Conversation)
        .filter(Conversation.store_id == store_id, Conversation.contact_phone.startswith(PENDING_PREFIX))
        .all()
    )
    if not pendings:
        return None
    instance = db.query(WhatsappInstance).filter_by(store_id=store_id).first()
    if not instance:
        return None
    wanted = username.lower()
    for pending in pendings:
        bodies = (
            db.query(Message.body)
            .filter(Message.conversation_id == pending.id, Message.direction == "in")
            .all()
        )
        for (body,) in bodies:
            given = parse_username(body, allow_bare=False)
            if not given:
                continue
            given = given.lower()
            if given != wanted and SequenceMatcher(None, given, wanted).ratio() < SIMILAR_MIN_RATIO:
                continue
            if (_proposed_username(db, pending) or "").lower() == wanted:
                break  # ya se le pregunto por este @
            phone = pending.whatsapp_phone
            if _try_link(db, instance, pending, username):
                return phone
            break
    return None


def merge_pending_into(db: Session, conversation: Conversation) -> bool:
    """El vendedor guardo a mano el WhatsApp de un usuario de TikTok: si ese
    numero ya tenia un chat temporal (escribio sin dar su @), se une a este."""
    if not conversation.whatsapp_phone or conversation.contact_phone.startswith(PENDING_PREFIX):
        return False
    pending = (
        db.query(Conversation)
        .filter(
            Conversation.store_id == conversation.store_id,
            Conversation.contact_phone == f"{PENDING_PREFIX}{conversation.whatsapp_phone}",
        )
        .first()
    )
    if not pending:
        return False
    _link(db, pending, conversation)
    return True
