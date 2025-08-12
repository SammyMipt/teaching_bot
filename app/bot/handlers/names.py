import logging
from aiogram import Router
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.types import Message

# from app.bot.main import resolve_role, require_roles, effective_user_id  # используем твои хелперы
from app.bot.auth import resolve_role, effective_user_id, require_roles
from app.storage import roster, user_links, instructor_map
from app.storage.grades import add_or_update_grade
from app.storage.yadisk import list_week_files, download_to_tmp
from aiogram.types import FSInputFile

router = Router()
log = logging.getLogger(__name__)

def _parse_who_args(args: str):
    # /who <last_name> [group] [email_part]
    parts = (args or "").split()
    last = parts[0] if parts else ""
    group = parts[1] if len(parts) >= 2 and "@" not in parts[1] else None
    email_part = None
    for p in parts[1:]:
        if "@" in p or "." in p:
            email_part = p
    return last, group, email_part

@router.message(Command("who"))
async def who(msg: Message, command: CommandObject):
    args = command.args or ""
    last, group, email_part = _parse_who_args(args)
    if not last:
        return await msg.answer("Использование: /who <фамилия> [группа] [часть_email]")
    cands = roster.find_candidates(last, group=group, email_part=email_part)
    if not cands:
        return await msg.answer("Никого не нашёл.")
    if len(cands) > 10:
        return await msg.answer(f"Найдено слишком много ({len(cands)}). Уточните группу или часть email.")
    lines = []
    for r in cands:
        link = user_links.get_link_by_email(r["external_email"])
        uid = link["user_id"] if link else "-"
        lines.append(f"{r['last_name_ru']} {r['first_name_ru']} ({r['group']}) — {r['student_code']} — {r['external_email']} — user_id={uid}")
    await msg.answer("\n".join(lines))

@router.message(Command("my_tutor"))
async def my_tutor(msg: Message, command: CommandObject):
    week = (command.args or "").strip()
    if not week:
        return await msg.answer("Использование: /my_tutor <неделя>")
    sc = user_links.resolve_student_code_by_user_id(effective_user_id(msg))
    if not sc:
        return await msg.answer("Вы ещё не привязаны к списку студентов. Пройдите регистрацию или используйте /link.")
    instr = instructor_map.get_instructor_for_student_code(week, sc)
    if not instr:
        return await msg.answer("Не нашёл преподавателя для этой недели.")
    await msg.answer(f"Ваш преподаватель на неделе {week}: {instr}")

@router.message(Command("grade_by_name"))
async def grade_by_name(msg: Message, command: CommandObject):
    # доступ
    if resolve_role(msg) not in {"instructor", "owner"}:
        return await msg.answer("Недостаточно прав.")
    args = (command.args or "").strip()
    if not args:
        return await msg.answer("Использование: /grade_by_name <фамилия> [группа|email] <неделя> <балл> [комментарий]")

    parts = args.split()
    # 1) Оценка — последний токен, который парсится как float
    score_idx = None
    for i in range(len(parts) - 1, -1, -1):
        try:
            float(parts[i])
            score_idx = i
            break
        except ValueError:
            continue
    if score_idx is None:
        return await msg.answer("Не найден балл. Пример: /grade_by_name Иванов B1 5 9.0 Отлично")

    # 2) Неделя — строго ЦИФРЫ перед оценкой
    week_idx = score_idx - 1
    if week_idx < 0 or not parts[week_idx].isdigit():
        return await msg.answer("Не найдена неделя (должна быть числом). Пример: /grade_by_name Иванов B1 5 9.0")

    week = parts[week_idx]
    score = float(parts[score_idx])
    comment = " ".join(parts[score_idx + 1:]) if score_idx + 1 < len(parts) else ""

    ident_tokens = parts[:week_idx]
    if not ident_tokens:
        return await msg.answer("Укажите фамилию. Пример: /grade_by_name Иванов B1 5 9.0")

    # 3) Идентификаторы: фамилия (обязательно), плюс либо группа, либо кусок email
    last = ident_tokens[0]
    group = None
    email_part = None
    for p in ident_tokens[1:]:
        if "@" in p or "." in p:
            email_part = p
        else:
            group = p

    # 4) Поиск кандидатов
    cands = roster.find_candidates(last, group=group, email_part=email_part)
    if not cands:
        return await msg.answer("Студент не найден, уточните группу или email.")
    if len(cands) > 1:
        listed = "\n".join(f"- {r['last_name_ru']} {r['first_name_ru']} ({r['group']}) {r['external_email']}" for r in cands[:10])
        return await msg.answer(f"Найдено несколько студентов ({len(cands)}). Уточните запрос.\n{listed}")

    r = cands[0]
    link = user_links.get_link_by_email(r["external_email"])
    if not link:
        return await msg.answer("Этот студент ещё не привязан к Telegram. Попросите пройти /register.")

    add_or_update_grade(int(link["user_id"]), week, score, comment)
    await msg.answer(
        f"Оценка сохранена: {r['last_name_ru']} {r['first_name_ru']} "
        f"(user_id={link['user_id']}), неделя={week}, балл={score}"
        + (f", комментарий: {comment}" if comment else "")
    )

@router.message(Command("pull_by_name"))
async def pull_by_name(msg: Message, command: CommandObject):
    if resolve_role(msg) not in {"instructor","owner"}:
        return await msg.answer("Недостаточно прав.")
    # /pull_by_name Фамилия [Группа|email] <неделя>
    parts = (command.args or "").split()
    if len(parts) < 2:
        return await msg.answer("Использование: /pull_by_name <фамилия> [группа|email] <неделя>")
    week = parts[-1]
    ident = parts[:-1]
    last = ident[0]
    group = None
    email_part = None
    for p in ident[1:]:
        if "@" in p or "." in p:
            email_part = p
        else:
            group = p
    cands = roster.find_candidates(last, group=group, email_part=email_part)
    if not cands:
        return await msg.answer("Студент не найден.")
    if len(cands) > 1:
        return await msg.answer(f"Найдено {len(cands)} студентов. Уточните запрос (группа/email).")
    r = cands[0]
    link = user_links.get_link_by_email(r["external_email"])
    if not link:
        return await msg.answer("Этот студент ещё не привязан к Telegram.")
    files = list_week_files(int(link["user_id"]), week)
    if not files:
        return await msg.answer("Файлов не найдено.")
    await msg.answer(f"Найдено файлов: {len(files)}. Отправляю…")
    sent = 0
    for rp in files[:10]:
        tmp_path = download_to_tmp(rp)
        await msg.answer_document(FSInputFile(tmp_path, filename=rp.rsplit("/",1)[-1]))
        sent += 1
    await msg.answer(f"Готово. Отправлено: {sent}/{len(files)}")

@router.message(Command("reload_config"))
async def reload_config(msg: Message):
    if resolve_role(msg) != "owner":
        return await msg.answer("Только для владельца курса.")
    roster.reload_roster_cache()
    await msg.answer("Таблицы перезагружены из CSV.")
