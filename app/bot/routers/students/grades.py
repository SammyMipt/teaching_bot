from aiogram import Router, F
from aiogram.types import Message
from app.services.users_service import UsersService
from app.services.grade_service import GradeService

router = Router(name="students_grades")

@router.message(F.text == "/grades")
async def my_grades(message: Message, users: UsersService, grades: GradeService):
    user = users.get_by_tg(message.from_user.id)
    if not user or not user.get("student_code"):
        await message.answer("Сначала /register и подтвердите email")
        return
    df = grades.list_grades_for_student(user["student_code"])
    if df.empty:
        await message.answer("Оценок пока нет.")
        return
    out = ["Мои оценки:"]
    for _, r in df.iterrows():
        out.append(f"- task {r['task_id']}: {r['points']} б. ({r['comment']})")
    await message.answer("\n".join(out))