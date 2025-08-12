import pytest
from pytest_mock import MockerFixture

from app.bot.main import Reg, reg_code  # импортируй реальный хендлер
from app.storage.users import get_user, upsert_user

@pytest.mark.asyncio
async def test_register_student_ok(mocker: MockerFixture):
    # фейковый Message
    msg = mocker.MagicMock()
    msg.from_user.id = 555555
    msg.text = "PHYS-2025"  # код студента
    msg.answer = mocker.AsyncMock()

    # фейковый FSMContext
    state = mocker.AsyncMock()
    state.get_data.return_value = {
        "full_name": "Test Student",
        "group": "B1",
        "email": "s@example.com",
    }

    # важное: effective_user_id(msg) должен вернуть 555555
    mocker.patch("app.bot.main.effective_user_id", return_value=555555)

    await reg_code(msg, state)
    user = get_user(555555)
    assert user is not None
    assert user["role"] == "student"
    assert user["status"] == "active"
    msg.answer.assert_awaited()  # бот что-то ответил

@pytest.mark.asyncio
async def test_register_instructor_pending(mocker: MockerFixture):
    msg = mocker.MagicMock()
    msg.from_user.id = 777777
    msg.text = "TA-2025"  # код препода
    msg.answer = mocker.AsyncMock()
    state = mocker.AsyncMock()
    state.get_data.return_value = {
        "full_name": "TA Person",
        "group": "TA",
        "email": "ta@example.com",
    }
    mocker.patch("app.bot.main.effective_user_id", return_value=777777)

    await reg_code(msg, state)
    u = get_user(777777)
    assert u and u["role"] == "instructor" and u["status"] == "pending"

@pytest.mark.asyncio
async def test_register_bad_code(mocker: MockerFixture):
    msg = mocker.MagicMock()
    msg.from_user.id = 999001
    msg.text = "WRONG-CODE"
    msg.answer = mocker.AsyncMock()
    state = mocker.AsyncMock()
    state.get_data.return_value = {"full_name": "X", "group": "G", "email": "x@x"}

    mocker.patch("app.bot.main.effective_user_id", return_value=999001)

    await reg_code(msg, state)
    # записи не должно появиться
    assert get_user(999001) is None
    msg.answer.assert_awaited()  # бот сообщил про неправильный код
