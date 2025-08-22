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
    real_tg_id = message.from_user.id
    actor_tg_id = _resolve_actor_tg_id(message)
    is_impersonation = (actor_tg_id != real_tg_id)
    
    # Получаем данные реального пользователя
    real_user = users.get_by_tg(real_tg_id)
    real_role = _role_of(real_user)
    real_name = _full_name(real_user)
    real_id = _s(real_user.get("id") if real_user else "")
    
    lines = [
        f"👤 <b>RealID:</b> {real_tg_id} | role={real_role} | name={real_name}"
    ]
    
    # Добавляем ID только если он есть
    if real_id:
        lines.append(f"    ID: {real_id}")
    
    if is_impersonation:
        # Получаем данные имперсонируемого пользователя
        actor_user = users.get_by_tg(actor_tg_id)
        actor_role = _role_of(actor_user)
        actor_name = _full_name(actor_user)
        actor_id = _s(actor_user.get("id") if actor_user else "")
        
        lines.append(f"🎭 <b>ActingID:</b> {actor_tg_id} | role={actor_role} | name={actor_name}")
        
        # Добавляем ID только если он есть
        if actor_id:
            lines.append(f"    ID: {actor_id}")
        else:
            lines.append(f"    ID: —")
    else:
        lines.append("🎭 <b>ActingID:</b> —")
    
    await message.answer("\n".join(lines), parse_mode="HTML")
