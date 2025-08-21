from __future__ import annotations
from aiogram import Router, F
from aiogram.types import Message
from app.bot.middlewares.actor_middleware import set_impersonation, clear_impersonation
from app.services.users_service import UsersService

router = Router(name="owner_dev_impersonate")

def _is_owner(message: Message, owner_id: int) -> bool:
    return message.from_user.id == owner_id

@router.message(F.text.startswith("/impersonate_off"))
async def impersonate_off(message: Message, owner_id: int):
    if not _is_owner(message, owner_id):
        await message.answer("Только для владельца курса.")
        return
    clear_impersonation(message.from_user.id)
    await message.answer("🟦 Имперсонация отключена. Теперь вы действуете от своего имени.")

@router.message(F.text.startswith("/impersonate"))
async def impersonate(message: Message, users: UsersService, owner_id: int):
    """
    Унифицированная имперсонация:
      /impersonate 123456789            — действовать как tg_id (если нет в users.csv — ок, будете 'unknown' до /register)
      /impersonate student_code=IU-001  — найти пользователя по student_code
    """
    if not _is_owner(message, owner_id):
        await message.answer("Только для владельца курса.")
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Формат: /impersonate <tg_id | student_code=...>")
        return
    arg = parts[1].strip()

    target_row = None
    target_tg_id = None

    if arg.isdigit():
        target_tg_id = int(arg)
        target_row = users.get_by_tg(target_tg_id)  # может быть None — это нормально
    elif arg.lower().startswith("student_code="):
        code = arg.split("=", 1)[1].strip()
        # попробуем найти по student_code
        if hasattr(users, "get_by_student_code"):
            target_row = users.get_by_student_code(code)
            if target_row:
                target_tg_id = int(target_row["tg_id"])
        if target_tg_id is None:
            await message.answer("Не нашёл пользователя с таким student_code.")
            return
    else:
        await message.answer("Формат: /impersonate <tg_id | student_code=...>")
        return

    set_impersonation(message.from_user.id, target_tg_id)
    if target_row:
        await message.answer(
            "🟩 Имперсонация включена.\n"
            f"Теперь вы действуете как: {target_row.get('first_name','')} {target_row.get('last_name','')} "
            f"(role={target_row.get('role','unknown')}, tg_id={target_tg_id}).\n"
            "Отключить: /impersonate_off"
        )
    else:
        await message.answer(
            "🟩 Имперсонация включена.\n"
            f"Действуете как tg_id={target_tg_id}. Пользователь пока не зарегистрирован (role=unknown).\n"
            "Выполните /register для привязки к ростеру."
        )

@router.message(F.text.startswith("/dev_user_role"))
async def dev_user_role(message: Message, users: UsersService, owner_id: int):
    if message.from_user.id != owner_id:
        await message.answer("Только для владельца курса.")
        return
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("Формат: /dev_user_role <tg_id> <role>")
        return
    try:
        tg_id = int(parts[1])
    except Exception:
        await message.answer("tg_id должен быть числом.")
        return
    role = parts[2]
    users.upsert_basic(tg_id=tg_id, role=role)
    await message.answer(f"✅ Роль обновлена: tg_id={tg_id}, role={role}")

@router.message(F.text.startswith("/dev_user_del"))
async def dev_user_del(message: Message, users: UsersService, owner_id: int):
    if message.from_user.id != owner_id:
        await message.answer("Только для владельца курса.")
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Формат: /dev_user_del <tg_id>")
        return
    try:
        tg_id = int(parts[1])
    except Exception:
        await message.answer("tg_id должен быть числом.")
        return

    # Прямой доступ к CSV через pandas (CsvTable не раскрывает delete явным методом).
    table = users.table
    df = table.read()
    if not df.empty:
        df = df[df["tg_id"].astype(str) != str(tg_id)]
        with table.lock:
            df.to_csv(table.path, index=False)
        await message.answer(f"🗑️ Удалена запись с tg_id={tg_id} из users.csv")
    else:
        await message.answer("В users.csv пока пусто — удалять нечего.")
