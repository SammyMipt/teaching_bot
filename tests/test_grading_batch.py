# tests/test_grading_batch.py
import types
import pytest
from pytest_mock import MockerFixture

from app.bot.handlers import grading as G

@pytest.mark.asyncio
async def test_grade_batch_preview_and_commit(mocker: MockerFixture):
    mocker.patch("app.bot.handlers.grading.resolve_role", return_value="instructor")

    # Резолвер идентификаторов: одна строка ок, одна unlinked, одна not_found
    def fake_resolve(ident: str):
        if ident == "Иванов B1":
            return ("ok", ident, {"user_id": 555555, "label": "Иванов Иван B1", "student_code":"S001"})
        if ident == "S777":
            return ("unlinked", ident, "Петров П П (B1) [S777]")
        return ("not_found", ident, None)
    mocker.patch.object(G, "_resolve_ident", side_effect=fake_resolve)

    add_grade = mocker.patch("app.bot.handlers.grading.add_or_update_grade")

    # старт
    msg_start = mocker.MagicMock()
    msg_start.answer = mocker.AsyncMock()
    state = mocker.AsyncMock()

    await G.batch_start(msg_start, state)
    state.set_state.assert_awaited_with(G.BatchFSM.paste)

    # паста из 3 строк
    paste = """Иванов B1;5;9.0;Молодец
S777;5;8.0;
НеИзвестен;5;7.5;"""
    msg = mocker.MagicMock()
    msg.text = paste
    msg.answer = mocker.AsyncMock()
    await G.batch_paste(msg, state)

    # после предпросмотра мы должны перейти в preview и показать кнопки
    state.set_state.assert_awaited_with(G.BatchFSM.preview)
    msg.answer.assert_awaited()
    # имитируем нажатие "Записать"
    data = {
        "batch": [
            {"ident":"Иванов B1","week":"5","score":9.0,"comment":"Молодец","status":"ok","info":{"user_id":555555,"label":"...","student_code":"S001"}},
            {"ident":"S777","week":"5","score":8.0,"comment":"","status":"unlinked","info":"..."},
            {"ident":"НеИзвестен","week":"5","score":7.5,"comment":"","status":"not_found","info":None},
        ]
    }
    state.get_data.return_value = data

    cb = types.SimpleNamespace()
    cb.data = "batch::commit"
    cb.answer = mocker.AsyncMock()
    cb.message = mocker.MagicMock()
    cb.message.edit_text = mocker.AsyncMock()

    await G.batch_commit(cb, state)

    add_grade.assert_called_once_with(555555, "5", 9.0, "Молодец")
    state.clear.assert_awaited()
    cb.message.edit_text.assert_awaited()  # «Записано: 1»
