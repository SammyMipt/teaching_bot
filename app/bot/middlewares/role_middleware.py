from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from app.services.roster_service import RosterService
from app.services.users_service import UsersService


class RoleMiddleware(BaseMiddleware):
    def __init__(self, users: UsersService, owner_id: int):
        super().__init__()
        self.users = users
        self.owner_id = owner_id

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        # Получаем actor_tg_id из ActorMiddleware (если есть)
        actor_tg_id = data.get("actor_tg_id")
        
        # Fallback к real tg_id если нет actor_tg_id
        if actor_tg_id is None:
            tg_id = None
            if hasattr(event, "from_user") and event.from_user:
                tg_id = event.from_user.id
            elif hasattr(event, "message") and event.message and event.message.from_user:
                tg_id = event.message.from_user.id
            actor_tg_id = tg_id

        role = "unknown"
        if actor_tg_id:
            if actor_tg_id == self.owner_id:
                role = "owner"
            else:
                role = self.users.get_role(actor_tg_id)

        data["role"] = role
        return await handler(event, data)