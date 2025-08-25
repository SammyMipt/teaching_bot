from __future__ import annotations
from aiogram import Router, F
from aiogram.types import Message
from app.services.materials_service import MaterialsService

router = Router(name="teacher_materials")

@router.message(F.text.startswith("/mat_get"))
async def get_material(message: Message, materials: MaterialsService):
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("Usage: /mat_get WEEK TYPE")
        return
    week, mtype = parts[1], parts[2]
    items = materials.list_active(week)
    rec = next((i for i in items if i["type"] == mtype), None)
    if not rec:
        await message.answer("Нет")
        return
    if rec.get("link"):
        await message.answer(rec["link"])
    else:
        await message.answer(rec.get("file_ref", ""))
