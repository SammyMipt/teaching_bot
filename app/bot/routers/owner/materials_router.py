from __future__ import annotations
from aiogram import Router, F
from aiogram.types import Message
from app.services.materials_service import MaterialsService

router = Router(name="owner_materials")

@router.message(F.text.startswith("/mat_list"))
async def list_active(message: Message, materials: MaterialsService):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Usage: /mat_list WEEK")
        return
    week = parts[1].strip()
    items = materials.list_active(week)
    if not items:
        await message.answer("Пусто")
        return
    lines = [f"{i['material_id']} {i['type']}" for i in items]
    await message.answer("\n".join(lines))
