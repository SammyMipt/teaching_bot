from __future__ import annotations
from aiogram import Router, F
from aiogram.types import Message
from app.services.assignments_service import AssignmentsService
from app.services.users_service import UsersService

router = Router(name="owner_assignments_admin")

@router.message(F.text.startswith("/assign_set"))
async def assign_set(message: Message, assignments: AssignmentsService):
    parts = message.text.split()
    if len(parts) < 4:
        await message.answer("Формат: /assign_set <student_code> <week> <ta_code>")
        return
    student_code, week_str, ta_code = parts[1], parts[2], parts[3]
    try:
        week = int(week_str)
    except Exception:
        await message.answer("Неделя должна быть числом.")
        return
    assignments.set(student_code, week, ta_code)
    await message.answer(f"✅ Назначено: {student_code} неделя {week} → {ta_code}")

@router.message(F.text.startswith("/assign_get"))
async def assign_get(message: Message, assignments: AssignmentsService, users: UsersService):
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Формат: /assign_get <student_code>")
        return
    student_code = parts[1]
    rows = assignments.get_all_for_student(student_code)
    if not rows:
        await message.answer("Назначений не найдено.")
        return
    # pretty print with names
    lines = ["Назначения:"]
    for w, ta_code in sorted(rows, key=lambda x: x[0]):
        ta_user = users.get_by_student_code(ta_code)
        ta_name = f"{ta_user.get('last_name','')} {ta_user.get('first_name','')}".strip() if ta_user else ta_code
        lines.append(f"• неделя {w}: {ta_name} ({ta_code})")
    await message.answer("\n".join(lines))
