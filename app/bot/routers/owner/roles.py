from aiogram import Router, F
from aiogram.types import Message
from app.services.users_service import UsersService

router = Router(name="owner_roles")

@router.message(F.text.startswith("/setrole"))
async def setrole(message: Message, users: UsersService, owner_id: int):
    if message.from_user.id != owner_id:
        await message.answer("Только для владельца курса.")
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Формат: /setrole [tg_id] [owner|ta|student]")
        return
    tg_id = int(parts[1]); role = parts[2].strip().lower()
    users.upsert_basic(tg_id=tg_id, role=role)
    await message.answer("OK")