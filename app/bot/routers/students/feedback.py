from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from app.services.feedback_service import FeedbackService

router = Router(name="students_feedback")

class FeedbackFSM(StatesGroup):
    waiting_text = State()

@router.message(F.text == "/feedback")
async def feedback_start(message: Message, state: FSMContext):
    await state.set_state(FeedbackFSM.waiting_text)
    await message.answer("Напишите ваш отзыв одним сообщением.")

@router.message(FeedbackFSM.waiting_text, F.text)
async def feedback_save(message: Message, state: FSMContext, feedback: FeedbackService):
    feedback.add(student_tg_id=message.from_user.id, text=message.text)
    await message.answer("Спасибо за отзыв!")
    await state.clear()