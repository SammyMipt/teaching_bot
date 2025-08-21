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
        tg_id = None
        if hasattr(event, "from_user") and event.from_user:
            tg_id = event.from_user.id
        elif hasattr(event, "message") and event.message and event.message.from_user:
            tg_id = event.message.from_user.id

        role = "unknown"
        if tg_id:
            if tg_id == self.owner_id:
                role = "owner"
            else:
                role = self.users.get_role(tg_id)

        data["role"] = role
        return await handler(event, data)
