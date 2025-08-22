from __future__ import annotations
from aiogram import Router, F
from aiogram.types import Message
from app.services.assignments_service import AssignmentsService
from app.services.users_service import UsersService

router = Router(name="owner_assignments_admin")

@router.message(F.text.startswith("/assign_set"))
async def assign_set(message: Message, assignments: AssignmentsService, owner_id: int):
    if message.from_user.id != owner_id:
        await message.answer("Только для владельца курса.")
        return
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
async def assign_get(message: Message, assignments: AssignmentsService, users: UsersService, owner_id: int):
    if message.from_user.id != owner_id:
        await message.answer("Только для владельца курса.")
        return
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
        ta_user = users.get_by_id(ta_code)
        ta_name = f"{ta_user.get('last_name','')} {ta_user.get('first_name','')}".strip() if ta_user else ta_code
        lines.append(f"• неделя {w}: {ta_name} ({ta_code})")
    await message.answer("\n".join(lines))

@router.message(F.text.startswith("/assign_student"))
async def assign_student(message: Message, assignments: AssignmentsService, owner_id: int):
    """Создать назначение для конкретного студента: /assign_student [student_code] [week] [ta_code]"""
    if message.from_user.id != owner_id:
        await message.answer("Только для владельца курса.")
        return
        
    parts = message.text.split()
    if len(parts) < 4:
        await message.answer("Формат: /assign_student [student_code] [week] [ta_code]")
        return
        
    try:
        student_code = parts[1]
        week = int(parts[2])
        ta_code = parts[3]
    except ValueError:
        await message.answer("Неделя должна быть числом.")
        return
    
    assignments.set(student_code, week, ta_code)
    await message.answer(f"✅ Назначено: студент {student_code}, неделя {week} → {ta_code}")

@router.message(F.text.startswith("/assign_check"))
async def assign_check(message: Message, assignments: AssignmentsService, users: UsersService, owner_id: int):
    """Проверить назначение студента: /assign_check [student_code] [week]"""
    if message.from_user.id != owner_id:
        await message.answer("Только для владельца курса.")
        return
        
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("Формат: /assign_check [student_code] [week]")
        return
        
    try:
        student_code = parts[1]
        week = int(parts[2])
    except ValueError:
        await message.answer("Неделя должна быть числом.")
        return
    
    ta_code = assignments.get_assignment_for_student_code(student_code, week)
    if ta_code:
        # Попробуем получить имя TA
        ta_user = users.get_by_id(ta_code)
        ta_name = f"{ta_user.get('last_name','')} {ta_user.get('first_name','')}".strip() if ta_user else ta_code
        await message.answer(f"Студент {student_code}, неделя {week}: назначен {ta_name} ({ta_code})")
    else:
        await message.answer(f"Для студента {student_code} на неделю {week} назначений нет.")