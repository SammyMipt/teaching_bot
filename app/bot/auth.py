# app/bot/auth.py
from functools import wraps
from aiogram.types import Message
from app.core.config import settings
from app.storage.users import get_user

# хранение имперсонации 
_user_impersonation: dict[int, int] = {}  # real_id -> acting_id

def effective_user_id(msg_or_callback) -> int:
    """Возвращает ID пользователя с учётом имперсонации"""
    # Поддерживаем как Message, так и CallbackQuery
    if hasattr(msg_or_callback, 'from_user'):
        # Это Message или CallbackQuery
        real = msg_or_callback.from_user.id
    elif hasattr(msg_or_callback, 'message') and hasattr(msg_or_callback.message, 'from_user'):
        # Это что-то другое с вложенным message
        real = msg_or_callback.message.from_user.id  
    else:
        raise ValueError(f"Неподдерживаемый тип: {type(msg_or_callback)}")
    
    return _user_impersonation.get(real, real)

def resolve_role_for_id(user_id: int) -> str:
    """Определяет роль пользователя по ID"""
    if user_id in settings.owner_ids:
        return "owner"
    rec = get_user(user_id)
    if not rec:
        return "guest"
    return rec.get("role", "guest")

def resolve_role(msg_or_callback) -> str:
    """Определяет роль пользователя из сообщения или callback"""
    return resolve_role_for_id(effective_user_id(msg_or_callback))

def is_active(user_id: int) -> bool:
    """Проверяет, активен ли пользователь"""
    rec = get_user(user_id)
    return bool(rec and rec.get("status") == "active")

def require_roles(roles: set[str]):
    """Декоратор для проверки ролей"""
    def decorator(handler):
        @wraps(handler)
        async def wrapper(msg: Message, *args, **kwargs):
            uid = effective_user_id(msg)
            role = resolve_role_for_id(uid)
            if role not in roles:
                await msg.answer("Недостаточно прав.")
                return
            # Владелец курса всегда активен
            if role != "owner" and not is_active(uid):
                await msg.answer("Ваш профиль ожидает подтверждения или неактивен.")
                return
            return await handler(msg, *args, **kwargs)
        return wrapper
    return decorator

def set_impersonation(real_id: int, acting_id: int | None):
    """Установить или убрать имперсонацию"""
    if acting_id is None:
        _user_impersonation.pop(real_id, None)
    else:
        _user_impersonation[real_id] = acting_id

def is_impersonating(msg_or_callback) -> bool:
    """Проверяет, включена ли имперсонация"""
    if hasattr(msg_or_callback, 'from_user'):
        real = msg_or_callback.from_user.id
    elif hasattr(msg_or_callback, 'message'):
        real = msg_or_callback.message.from_user.id
    else:
        raise ValueError(f"Неподдерживаемый тип: {type(msg_or_callback)}")
    
    return effective_user_id(msg_or_callback) != real

def get_impersonation_info(msg_or_callback) -> dict:
    """Возвращает информацию об имперсонации"""
    if hasattr(msg_or_callback, 'from_user'):
        real_id = msg_or_callback.from_user.id
    elif hasattr(msg_or_callback, 'message'):
        real_id = msg_or_callback.message.from_user.id
    else:
        raise ValueError(f"Неподдерживаемый тип: {type(msg_or_callback)}")
        
    acting_id = effective_user_id(msg_or_callback)
    return {
        "real_id": real_id,
        "acting_id": acting_id,
        "is_impersonating": real_id != acting_id
    }