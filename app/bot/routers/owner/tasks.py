from aiogram import Router, F
from aiogram.types import Message
from app.services.task_service import TaskService

router = Router(name="owner_tasks")

@router.message(F.text.startswith("/addtask"))
async def addtask(message: Message, tasks: TaskService, owner_id: int):
    if message.from_user.id != owner_id:
        await message.answer("Только для владельца курса.")
        return
    # /addtask [week] | [title] | [deadline ISO] | [max_points]
    try:
        payload = message.text.split(" ", 1)[1]
        week, title, deadline, max_points = [p.strip() for p in payload.split("|")]
    except Exception:
        await message.answer("Формат: /addtask [week] | [title] | [deadline ISO] | [max_points]")
        return
    task = tasks.add_task(week=week, title=title, deadline_iso=deadline, max_points=float(max_points))
    await message.answer(f"Создано: {task['task_id']} — {task['title']} (неделя {week})")