from __future__ import annotations
from aiogram import Router, F, Bot
from aiogram.types import Message, Document
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

from app.services.users_service import UsersService
from app.services.submission_service import SubmissionService

router = Router(name="students_submissions")

class SubmitFSM(StatesGroup):
    waiting_file = State()
    task_id = State()

@router.message(F.text.startswith("/submit"))
async def submit_cmd(message: Message, state: FSMContext):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /submit [task_id], затем пришлите файл документом.")
        return
    await state.set_state(SubmitFSM.waiting_file)
    await state.update_data(task_id=parts[1].strip())
    await message.answer("Ок! Теперь пришлите файл (документом, не фото).")

@router.message(SubmitFSM.waiting_file, F.document)
async def handle_document(message: Message, state: FSMContext,
                          users: UsersService, submissions: SubmissionService, bot: Bot):
    data = await state.get_data()
    task_id = data.get("task_id")
    doc: Document = message.document
    file = await bot.get_file(doc.file_id)
    file_bytes = await bot.download(file.file_path)
    file_bytes = file_bytes.read()
    user = users.get_by_tg(message.from_user.id)
    student_code = (user or {}).get("student_code", None)
    saved = await submissions.save_submission(
        tg_id=message.from_user.id,
        student_code=student_code or "",
        task_id=task_id,
        file_name=doc.file_name or "submission.bin",
        file_bytes=file_bytes,
    )
    await message.answer(f"Принято! submission_id={saved['submission_id']} путь={saved['file_path']}")
    await state.clear()

@router.message(SubmitFSM.waiting_file)
async def submit_waiting_file_hint(message: Message):
    await message.answer("Жду файл в ответ на команду /submit [task_id].")