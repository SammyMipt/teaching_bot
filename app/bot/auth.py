# app/bot/auth.py
from functools import wraps
from aiogram.types import Message
from app.core.config import settings
from app.storage.users import get_user

# хранение имперсонации (как у тебя было)
_user_impersonation: dict[int, int] = {}  # real_id -> acting_id

def effective_user_id(msg: Message) -> int:
    real = msg.from_user.id
    return _user_impersonation.get(real, real)

def resolve_role_for_id(user_id: int) -> str:
    if user_id in settings.owner_ids:
        return "owner"
    rec = get_user(user_id)
    if not rec:
        return "guest"
    return rec.get("role", "guest")

def resolve_role(msg: Message) -> str:
    return resolve_role_for_id(effective_user_id(msg))

def require_roles(roles: set[str]):
    def decorator(handler):
        @wraps(handler)
        async def wrapper(msg: Message, *args, **kwargs):
            role = resolve_role(msg)
            if role not in roles:
                await msg.answer("Недостаточно прав.")
                return
            return await handler(msg, *args, **kwargs)
        return wrapper
    return decorator

# (если у тебя есть команды /impersonate и /unimpersonate — оставь их в main,
#  но пусть они используют _user_impersonation из этого модуля)
def set_impersonation(real_id: int, acting_id: int | None):
    if acting_id is None:
        _user_impersonation.pop(real_id, None)
    else:
        _user_impersonation[real_id] = acting_id
