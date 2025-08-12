import pytest
from pytest_mock import MockerFixture
from aiogram.filters.command import CommandObject

from app.bot.main import pull, grade
from app.storage.users import upsert_user

@pytest.mark.asyncio
async def test_access_control_pull_forbidden_for_student(mocker: MockerFixture):
    upsert_user({"user_id":"555555","role":"student","full_name":"S","group":"G","email":"e","status":"active","created_at":"1","code_used":"PHYS"})
    msg = mocker.MagicMock()
    msg.from_user.id = 555555
    msg.answer = mocker.AsyncMock()

    # обмануть проверку ролей проще всего — временно подменим resolve_role, чтобы он вернул 'student'
    mocker.patch("app.bot.main.resolve_role", return_value="student")
    cmd = CommandObject(prefix="/", command="pull", args="555555 5", mention=None)

    # вызываем сам хендлер — он должен ответить «Недостаточно прав.» (или твой текст)
    resp = await pull(msg, cmd)
    msg.answer.assert_awaited_with("Недостаточно прав.")

@pytest.mark.asyncio
async def test_access_control_grade_allowed_for_instructor(mocker: MockerFixture):
    upsert_user({"user_id":"777777","role":"instructor","full_name":"TA","group":"TA","email":"t","status":"active","created_at":"2","code_used":"TA"})
    msg = mocker.MagicMock()
    msg.from_user.id = 777777
    msg.answer = mocker.AsyncMock()

    mocker.patch("app.bot.main.resolve_role", return_value="instructor")
    cmd = CommandObject(prefix="/", command="grade", args="555555 5 9.5 Отлично", mention=None)

    await grade(msg, cmd)
    # просто проверим, что что-то ответил (подробности — в тестах grades)
    msg.answer.assert_awaited()
