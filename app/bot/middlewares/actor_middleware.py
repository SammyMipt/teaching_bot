from __future__ import annotations
import logging
from typing import Callable, Any, Dict, Optional
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

log = logging.getLogger(__name__)

# In-memory map: { owner_tg_id: target_actor_tg_id }
_IMPERSONATE_MAP: Dict[int, int] = {}

def set_impersonation(owner_tg_id: int, target_tg_id: int) -> None:
    _IMPERSONATE_MAP[owner_tg_id] = target_tg_id
    log.info("Impersonation ON: owner=%s -> actor=%s", owner_tg_id, target_tg_id)

def clear_impersonation(owner_tg_id: int) -> None:
    if owner_tg_id in _IMPERSONATE_MAP:
        del _IMPERSONATE_MAP[owner_tg_id]
        log.info("Impersonation OFF: owner=%s", owner_tg_id)

def get_actor_id_for(owner_tg_id: int) -> Optional[int]:
    return _IMPERSONATE_MAP.get(owner_tg_id, None)

class ActorMiddleware(BaseMiddleware):
    """Injects actor_tg_id / real_tg_id / is_impersonating into handler data."""
    async def __call__(self, handler: Callable[[TelegramObject, dict], Any], event: TelegramObject, data: dict) -> Any:
        from_user = getattr(event, "from_user", None)
        real_tg_id = getattr(from_user, "id", None)
        actor_tg_id = real_tg_id
        is_imp = False
        if real_tg_id is not None:
            target = get_actor_id_for(real_tg_id)
            if target is not None:
                actor_tg_id = target
                is_imp = True
        data["real_tg_id"] = real_tg_id
        data["actor_tg_id"] = actor_tg_id
        data["is_impersonating"] = is_imp
        return await handler(event, data)
