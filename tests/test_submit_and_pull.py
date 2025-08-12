import io
import os
import pytest
from pytest_mock import MockerFixture
from aiogram.types import Document

from app.bot.main import handle_any, submit, pull
from app.storage.users import upsert_user

@pytest.mark.asyncio
async def test_submit_photo_and_pull(mocker: MockerFixture, tmp_path):
    # in-memory «диск»
    saved = {}  # remote_path -> bytes

    # моки Я.Диска
    async def fake_upload_async(local_path: str, remote_path: str):
        with open(local_path, "rb") as f:
            saved[remote_path] = f.read()
    mocker.patch("app.bot.main.upload_async", side_effect=fake_upload_async)

    def fake_build_remote_path(uid: int, week: str, filename: str) -> str:
        return f"/submissions/{uid}/week_{week}/{filename}"
    mocker.patch("app.bot.main.build_remote_path", side_effect=fake_build_remote_path)

    def fake_list_week_files(user_id: int, week: str):
        pref = f"/submissions/{user_id}/week_{week}/"
        return [k for k in saved.keys() if k.startswith(pref)]
    mocker.patch("app.bot.main.list_week_files", side_effect=fake_list_week_files)

    def fake_download_to_tmp(remote_path: str) -> str:
        p = tmp_path / os.path.basename(remote_path)
        p.write_bytes(saved[remote_path])
        return str(p)
    mocker.patch("app.bot.main.download_to_tmp", side_effect=fake_download_to_tmp)

    # зарегистрируем участника как студента (активного)
    upsert_user({
        "user_id": "555555", "role": "student",
        "full_name": "Stud", "group": "B1", "email": "s@ex",
        "status": "active", "created_at": "1", "code_used": "PHYS-2025"
    })

    # --- шаг 1: студент вызвал /submit 5
    msg_submit = mocker.MagicMock()
    msg_submit.from_user.id = 555555
    msg_submit.answer = mocker.AsyncMock()
    msg_submit.text = "/submit 5"
    mocker.patch("app.bot.main.effective_user_id", return_value=555555)

    # CommandObject.args у тебя уже разбирается в хендлере, поэтому дадим command.args через сам объект:
    from aiogram.filters.command import CommandObject
    cmd_obj = CommandObject(prefix="/", command="submit", args="5", mention=None)
    await submit(msg_submit, cmd_obj)
    msg_submit.answer.assert_awaited()

    # --- шаг 2: студент прислал фото (largest)
    # Подделаем файл из Telegram
    fake_file = mocker.MagicMock()
    fake_file.file_path = "photos/file_1.jpg"
    # bot.get_file / bot.download_file
    bot = mocker.MagicMock()
    bot.get_file = mocker.AsyncMock(return_value=fake_file)
    bot.download_file = mocker.AsyncMock(return_value=io.BytesIO(b"JPEGDATA"))

    msg_photo = mocker.MagicMock()
    msg_photo.bot = bot
    msg_photo.from_user.id = 555555
    msg_photo.photo = [mocker.MagicMock(file_id="id_small"), mocker.MagicMock(file_id="id_big")]
    msg_photo.document = None
    msg_photo.message_id = 42
    msg_photo.answer = mocker.AsyncMock()

    await handle_any(msg_photo)

    # проверим, что «на Диске» появился файл
    assert any("/submissions/555555/week_5/" in k for k in saved.keys())

    # --- шаг 3: преподаватель тянет
    upsert_user({
        "user_id": "777777", "role": "instructor",
        "full_name": "TA", "group": "TA", "email": "t@ex",
        "status": "active", "created_at": "2", "code_used": "TA-2025"
    })

    msg_pull = mocker.MagicMock()
    msg_pull.from_user.id = 777777
    msg_pull.answer = mocker.AsyncMock()
    # emulate отправку документов
    msg_pull.answer_document = mocker.AsyncMock()

    from aiogram.filters.command import CommandObject
    cmd_pull = CommandObject(prefix="/", command="pull", args="555555 5", mention=None)

    # обойти декоратор require_roles проще так: вызвать функцию напрямую
    await pull(msg_pull, cmd_pull)

    msg_pull.answer.assert_any_await("Найдено файлов: 1. Отправляю…")
    msg_pull.answer_document.assert_awaited()
