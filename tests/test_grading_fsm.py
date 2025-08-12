# tests/test_grading_fsm.py
import types
import pytest
from pytest_mock import MockerFixture

from app.bot.handlers import grading as G

@pytest.mark.asyncio
async def test_grade_fsm_happy_flow(mocker: MockerFixture):
    # Разрешим доступ (преподаватель)
    mocker.patch("app.bot.handlers.grading.resolve_role", return_value="instructor")

    # Подменим поиск кандидатов: находим одного
    cand = G.Candidate(full_name="Иванов Иван", group="B1", student_code="S001", email="ivanov@u.edu", user_id=555555)
    mocker.patch.object(G, "_find_candidates_by_query", return_value=[cand])

    # Линковка студент-к-юзер_id
    mocker.patch("app.bot.handlers.grading.user_links.resolve_user_id_by_student_code", return_value=555555)

    # Заглушка записи оценки
    add_grade = mocker.patch("app.bot.handlers.grading.add_or_update_grade")

    # Моки сообщений/контекста
    msg = mocker.MagicMock()
    msg.answer = mocker.AsyncMock()

    state = mocker.AsyncMock()
    # FSMContext.get_state() мы будем проверять только в /skip, а здесь идём через текст комментария — ок.

    # 1) старт диалога
    await G.grade_start(msg, state)
    state.set_state.assert_awaited_with(G.GradeFSM.identify)
    msg.answer.assert_awaited()

    # 2) идентификация (пишем "Иванов B1")
    msg2 = mocker.MagicMock()
    msg2.text = "Иванов B1"
    msg2.answer = mocker.AsyncMock()
    await G.grade_identify(msg2, state)
    state.update_data.assert_awaited_with(student_code="S001", student_label="Иванов Иван (B1)")
    state.set_state.assert_awaited_with(G.GradeFSM.week)

    # 3) неделя
    msg3 = mocker.MagicMock()
    msg3.text = "5"
    msg3.answer = mocker.AsyncMock()
    await G.grade_week(msg3, state)
    state.update_data.assert_awaited_with(week="5")
    state.set_state.assert_awaited_with(G.GradeFSM.score)

    # 4) балл
    msg4 = mocker.MagicMock()
    msg4.text = "9.0"
    msg4.answer = mocker.AsyncMock()
    await G.grade_score(msg4, state)
    state.update_data.assert_awaited_with(score=pytest.approx(9.0))
    state.set_state.assert_awaited_with(G.GradeFSM.comment)

    # 5) комментарий → подтверждение
    # смоделируем state.get_data() для предпросмотра
    async def fake_get_data():
        return {"student_code":"S001","student_label":"Иванов Иван (B1)","week":"5","score":9.0,"comment":"Отлично"}
    state.get_data.side_effect = fake_get_data

    msg5 = mocker.MagicMock()
    msg5.text = "Отлично"
    msg5.answer = mocker.AsyncMock()
    await G.grade_comment(msg5, state)
    state.set_state.assert_awaited_with(G.GradeFSM.confirm)
    msg5.answer.assert_awaited()  # предпросмотр с кнопками

    # 6) нажатие "Записать"
    cb = types.SimpleNamespace()
    cb.data = "confirm::yes"
    cb.answer = mocker.AsyncMock()
    cb.message = mocker.MagicMock()
    cb.message.edit_text = mocker.AsyncMock()

    await G.grade_confirm(cb, state)

    add_grade.assert_called_once_with(555555, "5", 9.0, "Отлично")
    state.clear.assert_awaited()
    cb.message.edit_text.assert_awaited_with("✅ Оценка сохранена.")
