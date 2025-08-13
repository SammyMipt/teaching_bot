import asyncio
import logging
import tempfile
import time

from functools import wraps

from aiogram import Bot, Dispatcher, Router, types, F
from aiogram.filters import CommandStart, Command
from aiogram.filters.command import CommandObject
from aiogram.types import Message, FSInputFile
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
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
from app.bot.handlers import registration_auto as reg_auto_handlers
from app.bot.handlers.registration_auto import try_autolink_after_register
from app.bot.auth import (
    resolve_role, resolve_role_for_id,
    effective_user_id, require_roles,
    set_impersonation,
)
from app.bot.auth import is_impersonating


logging.basicConfig(level=logging.INFO)
log = logging.getLogger("teaching_bot")
router = Router()

# ---------- DEV: имперсонация ----------
impersonate_map: dict[int, int] = {}  # real_owner_id -> acting_user_id

# def effective_user_id(msg: Message) -> int:
#     real_id = msg.from_user.id
#     if settings.DEV_ALLOW_AS and real_id in settings.owner_ids and real_id in impersonate_map:
#         return impersonate_map[real_id]
#     return real_id

# ---------- Роли ----------
# def resolve_role_for_id(user_id: int) -> str:
#     if user_id in settings.owner_ids:
#         return "owner"
#     r = get_user(user_id)
#     return r["role"] if r else "guest"

# def resolve_role(msg_or_id) -> str:
#     if hasattr(msg_or_id, "from_user"):
#         uid = effective_user_id(msg_or_id)
#     else:
#         uid = int(msg_or_id)
#     return resolve_role_for_id(uid)

def is_active(user_id: int) -> bool:
    r = get_user(user_id)
    return bool(r and r.get("status") == "active")

# def require_roles(roles: set[str]):
#     def decorator(handler):
#         @wraps(handler)
#         async def wrapper(msg: Message, *args, **kwargs):
#             # используем твою функцию определения роли
#             uid = effective_user_id(msg)
#             role = resolve_role(uid)
#             if role not in roles:
#                 await msg.answer("Недостаточно прав.")
#                 return
#             if role != "owner" and not is_active(uid):
#                 await msg.answer("Ваш профиль ожидает подтверждения или неактивен.")
#                 return
#             return await handler(msg, *args, **kwargs)
#         return wrapper
#     return decorator

# ---------- Регистрация (FSM) ----------
class Reg(StatesGroup):
    full_name = State()
    group = State()
    email = State()
    code = State()

# ---------- Команды ----------
@router.message(CommandStart())
async def start(msg: Message):
    await msg.answer(
        "Привет! Я учебный ассистент.\n"
        "Команды:\n"
        "/register — регистрация\n"
        "/whoami — кто я\n"
        "/tasks — задачи (заглушка)\n"
        "/submit <неделя> — затем пришли файл/фото\n"
        "/mygrade <неделя> — моя оценка\n"
        "/ping_storage — проверка хранилища"
    )

@router.message(Command("ping_storage"))
async def ping_storage(msg: Message):
    ok, info = health_check_verbose()
    await msg.answer(f"Хранилище: {'✅ OK' if ok else '❌ FAIL'}\n{info}")

@router.message(Command("whoami"))
async def whoami(msg: Message):
    real_id = msg.from_user.id
    acting_id = effective_user_id(msg)

    # роль можно получить либо от сообщения, либо по acting_id
    role = resolve_role(msg)  # или: resolve_role_for_id(acting_id)
    rec  = get_user(acting_id)

    status = "active (owner)" if role == "owner" else (rec.get("status") if rec else "-")
    full_name = rec.get("full_name", "-") if rec else "-"
    group = rec.get("group", "-") if rec else "-"
    email = rec.get("email", "-") if rec else "-"

    await msg.answer(
        f"real_id={real_id}\n"
        f"acting_id={acting_id}\n"
        f"role={role}\n"
        f"status={status}\n"
        f"ФИО: {full_name}\n"
        f"Группа: {group}\n"
        f"Email: {email}"
    )

@router.message(Command("as"))
async def as_role(msg: Message, command: CommandObject):
    if not (settings.DEV_ALLOW_AS and msg.from_user.id in settings.owner_ids):
        return
    role = (command.args or "").strip()
    if role not in {"student","instructor","owner","guest"}:
        return await msg.answer("Роли: student | instructor | owner | guest")
    # для роли достаточно имперсонации id + регистрации (если нужно)
    await msg.answer(f"Роль выставляется через имперсонацию. Используйте /impersonate <id> для полного сценария.")

@router.message(Command("impersonate"))
async def cmd_impersonate(msg: Message, command: CommandObject):
    # Разрешаем только владельцу и только если DEV_ALLOW_AS=True
    if not (getattr(settings, "DEV_ALLOW_AS", False) and msg.from_user.id in settings.owner_ids):
        return await msg.answer("Недоступно.")
    args = (command.args or "").strip()
    if not args.isdigit():
        return await msg.answer("Использование: /impersonate <user_id>")
    target = int(args)

    # включаем имперсонацию через общий стор
    set_impersonation(msg.from_user.id, target)
    return await msg.answer(f"Имперсонация включена. Теперь вы действуете как user_id={target}.")

@router.message(Command("unimpersonate"))
async def cmd_unimpersonate(msg: Message):
    # impersonate_map.pop(msg.from_user.id, None)
    set_impersonation(msg.from_user.id, None)
    await msg.answer("Имперсонация выключена.")

# ---------- Регистрация ----------
@router.message(Command("register"))
async def cmd_register(msg: Message, state: FSMContext):
    if is_impersonating(msg) and msg.from_user.id in settings.owner_ids:
        return await msg.answer(
            "⚠️ Внимание: сейчас включена имперсонация.\n"
            "Вы регистрируете *не свой* аккаунт, а acting_id="
            f"{effective_user_id(msg)}.\n"
            "Если это случайно — отправьте /unimpersonate и запустите /register снова."
        )
    uid = effective_user_id(msg)
    if get_user(uid):
        return await msg.answer("Вы уже зарегистрированы. Команда: /whoami")
    await state.set_state(Reg.full_name)
    await msg.answer("Введите ФИО:")

@router.message(Reg.full_name)
async def reg_full_name(msg: Message, state: FSMContext):
    await state.update_data(full_name=msg.text.strip())
    await state.set_state(Reg.group)
    await msg.answer("Введите группу (например, B1):")

@router.message(Reg.group)
async def reg_group(msg: Message, state: FSMContext):
    await state.update_data(group=msg.text.strip())
    await state.set_state(Reg.email)
    await msg.answer("Введите email:")

@router.message(Reg.email)
async def reg_email(msg: Message, state: FSMContext):
    await state.update_data(email=msg.text.strip())
    await state.set_state(Reg.code)
    await msg.answer("Введите код курса или код преподавателя:")

@router.message(Reg.code)
async def reg_code(msg: Message, state: FSMContext):
    from app.core.config import settings
    data = await state.get_data()
    uid = effective_user_id(msg)
    code = (msg.text or "").strip()
    if uid in settings.owner_ids:
        role, status = "owner", "active"
    else:
        if code == settings.COURSE_CODE:
            role, status = "student", "active"
        elif code == settings.INSTRUCTOR_CODE:
            role, status = "instructor", "pending"
        else:
            await msg.answer("Неверный код. Попробуйте ещё раз или свяжитесь с преподавателем.")
            return
    upsert_user({
        "user_id": str(uid),
        "role": role,
        "full_name": data["full_name"],
        "group": data["group"],
        "email": data["email"],
        "status": status,
        "created_at": str(int(time.time())),
        "code_used": code,
    })
    await try_autolink_after_register(
        msg,
        state,  # важен живой FSMContext — вызываем до state.clear()
        email=data["email"],
        last_name_ru=(data["full_name"].split()[0] if data.get("full_name") else None),
        group=data.get("group")
    )
    await state.clear()
    if role == "student":
        await msg.answer("Готово! Вы зарегистрированы как студент. Команда: /whoami")
    else:
        await msg.answer("Вы подали заявку как преподаватель. Ожидайте подтверждения владельцем курса. Команда: /whoami")

# ---------- Задачи (заглушка) ----------
@router.message(Command("tasks"))
async def tasks(msg: Message):
    await msg.answer("Неделя 1: задачи 1.1, 1.2; дедлайн: 2025-09-15")

# ---------- Сдача файлов ----------
user_week: dict[int, str] = {}

@router.message(Command("submit"))
async def submit(msg: Message, command: CommandObject):
    parts = (command.args or "").split()
    if len(parts) < 1:
        return await msg.answer("Укажи неделю: /submit <неделя>, например /submit 5")
    user_week[effective_user_id(msg)] = parts[0]
    await msg.answer(f"Ок, жду файл/фото для недели {parts[0]} (одним сообщением).")

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
    except Exception as e:
        log.exception("Ошибка при загрузке на Я.Диск")
        await msg.answer(f"Ошибка при сохранении на Я.Диск: {e}")

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

# ---------- Owner: модерация преподавателей ----------
@router.message(Command("pending"))
async def pending(msg: Message):
    logging.info("pending: real=%s acting=%s role=%s",
                 msg.from_user.id, effective_user_id(msg), resolve_role(msg))
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
    rec["status"] = "blocked"
    upsert_user(rec)
    await msg.answer(f"Отклонён/заблокирован: {uid}")

# ---------- bootstrap ----------
async def main():
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    await bot.delete_webhook(drop_pending_updates=True)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(reg_auto_handlers.router)   # <— новый роутер автопривязки
    dp.include_router(grading_handlers.router)
    dp.include_router(names_handlers.router)
    dp.include_router(router)


    # 🔧 нормализация владельцев в реестре
    now = str(int(time.time()))
    for oid in settings.owner_ids:
        rec = get_user(oid) or {
            "user_id": str(oid),
            "role": "owner",
            "full_name": "",
            "group": "",
            "email": "",
            "status": "active",
            "created_at": now,
            "code_used": "OWNER",
        }
        rec["role"] = "owner"
        rec["status"] = "active"
        upsert_user(rec)

    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        log.exception("Fatal error on startup")
