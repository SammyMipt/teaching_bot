from __future__ import annotations
import logging
from typing import Any, Dict, List
from aiogram import Router, F
from aiogram.types import Message
from app.services.users_service import UsersService

try:
    from app.bot.middlewares.actor_middleware import get_actor_id_for  # type: ignore
except Exception:
    def get_actor_id_for(owner_tg_id: int):
        return None

router = Router(name="common")
log = logging.getLogger(__name__)

def _is_nan(v: Any) -> bool:
    try:
        return isinstance(v, float) and v != v
    except Exception:
        return False

def _s(v: Any) -> str:
    if v is None or _is_nan(v):
        return ""
    return str(v)

def _role_of(user: Dict | None) -> str:
    return (user or {}).get("role", "unknown")

def _full_name(user: Dict | None) -> str:
    if not user:
        return "—"
    first = _s(user.get("first_name"))
    last  = _s(user.get("last_name"))
    name = (first + " " + last).strip()
    if not name:
        return _s(user.get("username")) or "—"
    return name

def _help_for_role(role: str) -> List[str]:
    base = ["/start — приветствие", "/help — помощь", "/whoami — показать ваш ID/роль"]
    if role == "student":
        base += ["/register — привязка к ростеру", "/slots — свободные слоты и запись",
                 "/submit [task_id] — отправить решение", "/grades — мои оценки", "/feedback — отзыв"]
    if role in ("ta", "owner"):
        base += ["/register_ta — заявка TA", "/schedule — создать расписание",
                 "/myslots — мои слоты", "/myslots_manage — управление слотами"]
    if role == "owner":
        base += ["/setrole <tg_id> <role>", "/ta_pending — заявки TA",
                 "/impersonate <tg_id|student_code=...>", "/impersonate_off",
                 "/dev_user_role <tg_id> <role>", "/dev_user_del <tg_id>"]
    return base

def _resolve_actor_tg_id(message: Message) -> int:
    real_id = message.from_user.id
    try:
        target = get_actor_id_for(real_id)
    except Exception:
        target = None
    return target or real_id

@router.message(F.text == "/start")
async def start(message: Message, users: UsersService):
    actor_id = _resolve_actor_tg_id(message)
    actor_user = users.get_by_tg(actor_id)
    actor_role = _role_of(actor_user)
    is_imp = actor_id != message.from_user.id
    lines = ["👋 Привет! Это учебный ассистент курса.", f"Ваша роль: **{actor_role}**"]
    if is_imp:
        lines.append(f"(имперсонация активна; действуете как tg_id={actor_id})")
    if actor_role == "student":
        lines.append("Начните с /slots или отправьте решение через /submit [task_id].")
    elif actor_role == "ta":
        lines.append("Создайте расписание через /schedule или посмотрите /myslots.")
    elif actor_role == "owner":
        lines.append("Для тестов есть /impersonate. Управление — /ta_pending, /setrole.")
    else:
        lines.append("Если вы студент — используйте /register для привязки к ростеру.")
    await message.answer("\n".join(lines))

@router.message(F.text == "/help")
async def help_cmd(message: Message, users: UsersService):
    actor_id = _resolve_actor_tg_id(message)
    role = _role_of(users.get_by_tg(actor_id))
    text = "📖 Доступные команды:\n" + "\n".join(f"• {x}" for x in _help_for_role(role))
    await message.answer(text, parse_mode=None)  # <— добавили parse_mode=None

@router.message(F.text == "/whoami")
async def whoami(message: Message, users: UsersService):
    real = users.get_by_tg(message.from_user.id)
    actor_id = _resolve_actor_tg_id(message)
    actor = users.get_by_tg(actor_id)
    is_imp = (actor_id != message.from_user.id)
    lines = [f"👤 RealID: {message.from_user.id} | role={_role_of(real)} | name={_full_name(real)}"]
    if is_imp:
        sc = (actor or {}).get("student_code", "—")
        lines.append(f"🎭 ActingID: {actor_id} | role={_role_of(actor)} | name={_full_name(actor)} | student_code={_s(sc) or '—'}")
    else:
        lines.append("🎭 ActingID: —")
    await message.answer("\n".join(lines))
