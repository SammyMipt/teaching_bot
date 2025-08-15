import asyncio
import logging
import tempfile
import time

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import CommandStart, Command
from aiogram.filters.command import CommandObject
from aiogram.types import Message, FSInputFile
from aiogram.fsm.storage.memory import MemoryStorage

from app.core.config import settings
from app.storage.yadisk import (
    upload_async, build_remote_path,
    health_check_verbose, list_week_files, download_to_tmp
)
from app.storage.grades import add_or_update_grade, get_grade
from app.storage.users import get_user, upsert_user, list_pending_instructors
from app.bot.handlers import names as names_handlers
from app.bot.handlers import grading as grading_handlers  
from app.bot.handlers import registration_smart as smart_reg_handlers
from app.bot.auth import (
    resolve_role, resolve_role_for_id,
    effective_user_id, require_roles,
    set_impersonation, is_impersonating
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("teaching_bot")
router = Router()

# Словарь для отслеживания недель при загрузке файлов
user_week: dict[int, str] = {}

def is_active(user_id: int) -> bool:
    r = get_user(user_id)
    return bool(r and r.get("status") == "active")

# ---------- Команды ----------
@router.message(CommandStart())
async def start(msg: Message):
    await msg.answer(
        "Привет! Я учебный ассистент.\n"
        "Команды:\n"
        "/register — умная регистрация\n"
        "/whoami — кто я\n" 
        "/submit <неделя> — затем пришли файл/фото\n"
        "/mygrade <неделя> — моя оценка\n"
        "/ping_storage — проверка хранилища\n"
        "\n🔧 DEV команды:\n"
        "/impersonate <user_id> — имперсонация\n"
        "/unimpersonate — выключить имперсонацию\n"
        "\n👨‍🏫 Для владельца курса:\n"
        "/pending_students — проблемные регистрации\n"
        "/resolve_pending <user_id> — пометить решённой\n"
        "/ignore_pending <user_id> — игнорировать"
    )

@router.message(Command("ping_storage"))
async def ping_storage(msg: Message):
    ok, info = health_check_verbose()
    await msg.answer(f"Хранилище: {'✅ OK' if ok else '❌ FAIL'}\n{info}")

@router.message(Command("whoami"))
async def whoami(msg: Message):
    real_id = msg.from_user.id
    acting_id = effective_user_id(msg)
    is_impersonating_now = is_impersonating(msg)

    role = resolve_role(msg)
    rec = get_user(acting_id)

    status = "active (owner)" if role == "owner" else (rec.get("status") if rec else "-")
    
    # Формируем Telegram ID
    if is_impersonating_now:
        telegram_info = f"real_id={real_id}\nacting_id={acting_id}"
        impersonate_info = "\n🎭 ИМПЕРСОНАЦИЯ ВКЛЮЧЕНА"
    else:
        telegram_info = f"Telegram ID: {acting_id}"
        impersonate_info = ""
    
    # Пытаемся получить данные из ростера (если есть привязка)
    from app.storage import user_links, roster
    
    # Для студентов проверяем привязку к ростеру
    if role == "student":
        link = user_links.get_link_by_user(acting_id)
        if link and link.get("student_code"):
            # Пользователь привязан - показываем данные из ростера
            roster_data = roster.get_by_student_code(link["student_code"])
            if roster_data:
                # Приоритет русским именам
                if roster_data.get('last_name_ru') and roster_data.get('first_name_ru'):
                    full_name = f"{roster_data['last_name_ru']} {roster_data['first_name_ru']}"
                    if roster_data.get('middle_name_ru'):
                        full_name += f" {roster_data['middle_name_ru']}"
                else:
                    full_name = f"{roster_data.get('last_name_en', '')} {roster_data.get('first_name_en', '')}"
                    if roster_data.get('middle_name_en'):
                        full_name += f" {roster_data.get('middle_name_en', '')}"
                
                group = roster_data.get('group', '-')
                email = roster_data.get('external_email', '-')
                student_code = roster_data.get('student_code', '-')
                
                # Добавляем информацию о привязке
                link_info = f"\n🔗 Привязан к: {student_code}"
            else:
                # Привязка есть, но данных в ростере нет (странная ситуация)
                full_name = rec.get("full_name", "-") if rec else "-"
                group = rec.get("group", "-") if rec else "-"
                email = rec.get("email", "-") if rec else "-"
                link_info = f"\n⚠️ Привязка: {link['student_code']} (данные не найдены в ростере)"
        else:
            # Студент не привязан - показываем что ввел при регистрации
            full_name = rec.get("full_name", "-") if rec else "-"
            group = rec.get("group", "-") if rec else "-"
            email = rec.get("email", "-") if rec else "-"
            link_info = "\n❌ Не привязан к ростеру"
    else:
        # Для owner и instructor не показываем статус привязки
        full_name = rec.get("full_name", "-") if rec else "-"
        group = rec.get("group", "-") if rec else "-"
        email = rec.get("email", "-") if rec else "-"
        link_info = ""

    await msg.answer(
        f"{telegram_info}\n"
        f"role={role}\n"
        f"status={status}\n"
        f"ФИО: {full_name}\n"
        f"Группа: {group}\n"
        f"Email: {email}"
        f"{link_info}"
        f"{impersonate_info}"
    )

# ---------- DEV команды имперсонации ----------
@router.message(Command("impersonate"))
async def cmd_impersonate(msg: Message, command: CommandObject):
    # Разрешаем только владельцу и только если DEV_ALLOW_AS=True
    if not (getattr(settings, "DEV_ALLOW_AS", False) and msg.from_user.id in settings.owner_ids):
        return await msg.answer("Недоступно.")
    
    args = (command.args or "").strip()
    if not args.isdigit():
        return await msg.answer("Использование: /impersonate <user_id>")
    
    target = int(args)
    set_impersonation(msg.from_user.id, target)
    await msg.answer(f"🎭 Имперсонация включена. Теперь вы действуете как user_id={target}.\n"
                     f"Используйте /whoami для проверки и /unimpersonate для выключения.")

@router.message(Command("unimpersonate"))
async def cmd_unimpersonate(msg: Message):
    if not (getattr(settings, "DEV_ALLOW_AS", False) and msg.from_user.id in settings.owner_ids):
        return await msg.answer("Недоступно.")
    
    set_impersonation(msg.from_user.id, None)
    await msg.answer("🎭 Имперсонация выключена.")

# ---------- Загрузка файлов ----------
@router.message(Command("submit"))
async def submit(msg: Message, command: CommandObject):
    week = (command.args or "").strip()
    if not week:
        return await msg.answer("Использование: /submit <неделя>\nЗатем пришлите файл или фото.")
    
    uid = effective_user_id(msg)
    user_week[uid] = week
    await msg.answer(f"Неделя {week} выбрана. Теперь пришлите файл или фото.")

@router.message(F.document | F.photo)
async def handle_any(msg: Message):
    uid = effective_user_id(msg)
    week = user_week.get(uid)
    if not week:
        return  # неделя не выбрана — игнорим файл/фото

    file_id = None
    filename = None

    if msg.document:
        file_id = msg.document.file_id
        filename = msg.document.file_name or f"document_{msg.message_id}"
    elif msg.photo:
        largest = msg.photo[-1]
        file_id = largest.file_id
        filename = f"photo_{msg.message_id}.jpg"
    else:
        return

    try:
        tg_file = await msg.bot.get_file(file_id)
        file_bytes = await msg.bot.download_file(tg_file.file_path)
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(file_bytes.read())
            tmp_path = tmp.name
    except Exception as e:
        log.exception("Ошибка скачивания файла из Telegram")
        return await msg.answer(f"Не удалось получить файл из Telegram: {e}")

    remote_path = build_remote_path(uid, week, filename)
    try:
        await upload_async(tmp_path, remote_path)
        await msg.answer(
            "Файл сохранён на Я.Диске ✅\n"
            f"Путь: /submissions/{uid}/week_{week}/{filename}"
        )
        # Очищаем выбранную неделю после успешной загрузки
        user_week.pop(uid, None)
    except Exception as e:
        log.exception("Ошибка при загрузке на Я.Диск")
        await msg.answer(f"Ошибка при сохранении на Я.Диск: {e}")

# ---------- Просмотр оценок ----------
@router.message(Command("mygrade"))
async def mygrade(msg: Message, command: CommandObject):
    week = (command.args or "").strip()
    if not week:
        return await msg.answer("Использование: /mygrade <неделя>")
    
    uid = effective_user_id(msg)
    rec = get_grade(uid, week)
    if not rec:
        return await msg.answer("Оценка не найдена.")
    
    comment = f"\nКомментарий: {rec['comment']}" if rec.get("comment") else ""
    await msg.answer(f"Неделя {week}: {rec['score']}{comment}")

# ---------- Команды преподавателя ----------
@router.message(Command("pull"))
@require_roles({"instructor","owner"})
async def pull(msg: Message, command: CommandObject):
    parts = (command.args or "").split()
    if len(parts) != 2:
        return await msg.answer("Использование: /pull <user_id> <week>")
    try:
        student_id = int(parts[0])
    except ValueError:
        return await msg.answer("user_id должен быть числом.")
    
    week = parts[1]
    files = list_week_files(student_id, week)
    if not files:
        return await msg.answer("Файлов не найдено.")
    
    await msg.answer(f"Найдено файлов: {len(files)}. Отправляю…")
    sent = 0
    for rp in files[:10]:  # ограничим, чтобы не упереться в лимиты
        try:
            tmp_path = download_to_tmp(rp)
            name = rp.rsplit("/", 1)[-1]
            await msg.answer_document(FSInputFile(tmp_path, filename=name))
            sent += 1
        except Exception as e:
            await msg.answer(f"Не удалось отправить {rp}: {e}")
    await msg.answer(f"Готово. Отправлено: {sent}/{len(files)}")

@router.message(Command("grade"))
@require_roles({"instructor","owner"})
async def grade(msg: Message, command: CommandObject):
    parts = (command.args or "").split(None, 3)
    if len(parts) < 3:
        return await msg.answer("Использование: /grade <user_id> <week> <score> [comment]")
    
    try:
        student_id = int(parts[0])
        week = parts[1]
        score = float(parts[2])
        comment = parts[3] if len(parts) > 3 else ""
    except ValueError:
        return await msg.answer("Неверный формат. user_id - число, score - число.")
    
    add_or_update_grade(student_id, week, score, comment)
    await msg.answer(f"Оценка записана: {student_id} неделя {week} = {score}")

# ---------- Owner: модерация преподавателей ----------
@router.message(Command("pending"))
async def pending(msg: Message):
    if resolve_role(msg) != "owner":
        return await msg.answer("Только для владельца курса.")
    
    pend = list_pending_instructors()
    if not pend:
        return await msg.answer("Нет заявок.")
    
    txt = "\n".join(f"{p['user_id']} {p['full_name']} {p['email']}" for p in pend[:50])
    await msg.answer("Ожидают подтверждения:\n" + txt)

@router.message(Command("approve"))
async def approve(msg: Message, command: CommandObject):
    if resolve_role(msg) != "owner":
        return await msg.answer("Только для владельца курса.")
    
    uid = (command.args or "").strip()
    if not uid.isdigit():
        return await msg.answer("Использование: /approve <user_id>")
    
    rec = get_user(int(uid))
    if not rec:
        return await msg.answer("Пользователь не найден.")
    
    rec["status"] = "active"
    upsert_user(rec)
    await msg.answer(f"Подтверждён: {uid}")

@router.message(Command("deny"))
async def deny(msg: Message, command: CommandObject):
    if resolve_role(msg) != "owner":
        return await msg.answer("Только для владельца курса.")
    
    uid = (command.args or "").strip()
    if not uid.isdigit():
        return await msg.answer("Использование: /deny <user_id>")
    
    rec = get_user(int(uid))
    if not rec:
        return await msg.answer("Пользователь не найден.")
    
    # Можно либо удалить, либо поставить статус "denied"
    rec["status"] = "denied"
    upsert_user(rec)
    await msg.answer(f"Отклонён: {uid}")

# ---------- Инициализация бота ----------
async def main():
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    
    # Подключаем роутеры
    dp.include_router(router)
    dp.include_router(names_handlers.router)
    dp.include_router(grading_handlers.router)
    dp.include_router(smart_reg_handlers.router)  # Новая умная регистрация
    
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())