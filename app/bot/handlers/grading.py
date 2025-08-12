import logging
from dataclasses import dataclass
from typing import Optional, List

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

# from app.bot.main import resolve_role, effective_user_id
from app.bot.auth import resolve_role, effective_user_id, require_roles
from app.storage import roster, user_links
from app.storage.grades import add_or_update_grade

log = logging.getLogger(__name__)
router = Router()

# ---------- FSM ----------
class GradeFSM(StatesGroup):
    identify = State()   # фамилия/email/Sxxx
    disambiguate = State()
    week = State()
    score = State()
    comment = State()
    confirm = State()

@dataclass
class Candidate:
    full_name: str
    group: str
    student_code: str
    email: str
    user_id: Optional[int]

def _find_candidates_by_query(q: str) -> List[Candidate]:
    q = (q or "").strip()
    cands: List[Candidate] = []
    # эвристика: email / student_code / last_name(+group)
    if "@" in q:
        row = roster.get_by_email(q)
        rows = [row] if row else []
    elif q.upper().startswith("S"):
        row = roster.get_by_student_code(q.upper())
        rows = [row] if row else []
    else:
        # поддержка формата "Иванов B1" или просто "Иванов"
        parts = q.split()
        last = parts[0]
        group = parts[1] if len(parts) >= 2 else None
        rows = roster.find_candidates(last, group=group, email_part=None)

    for r in rows:
        if not r:
            continue
        link = user_links.get_link_by_email(r["external_email"])
        uid = int(link["user_id"]) if link else None
        cands.append(Candidate(
            full_name=f"{r['last_name_ru']} {r['first_name_ru']}".strip(),
            group=r.get("group",""),
            student_code=r["student_code"],
            email=r["external_email"],
            user_id=uid
        ))
    return cands

def _kb_candidates(cands: List[Candidate]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(
            text=f"{c.full_name} ({c.group}) • {c.student_code}",
            callback_data=f"choose::{c.student_code}"
        )] for c in cands[:10]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def _kb_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Записать", callback_data="confirm::yes"),
         InlineKeyboardButton(text="❌ Отмена", callback_data="confirm::no")]
    ])

# ---------- /grade ----------
@router.message(Command("grade"))
async def grade_start(msg: Message, state: FSMContext):
    if resolve_role(msg) not in {"instructor", "owner"}:
        return await msg.answer("Недостаточно прав.")
    await state.clear()
    await state.set_state(GradeFSM.identify)
    await msg.answer("Кого оцениваем? Введите: фамилию (опц. группу), или email, или код студента (Sxxx).\nПримеры: `Иванов B1` / `ivanov@u.edu` / `S001`")

@router.message(GradeFSM.identify, F.text)
async def grade_identify(msg: Message, state: FSMContext):
    q = msg.text or ""
    cands = _find_candidates_by_query(q)
    if not cands:
        return await msg.answer("Не нашёл. Уточните: добавьте группу или email.")
    if len(cands) == 1:
        c = cands[0]
        await state.update_data(student_code=c.student_code, student_label=f"{c.full_name} ({c.group})")
        await state.set_state(GradeFSM.week)
        return await msg.answer(f"Ок: {c.full_name} ({c.group}). За какую неделю ставим? Введите номер (например, 5).")
    # неоднозначность
    await state.update_data(candidates=[c.__dict__ for c in cands])
    await state.set_state(GradeFSM.disambiguate)
    await msg.answer("Нашлось несколько студентов. Выберите:", reply_markup=_kb_candidates(cands))

@router.callback_query(GradeFSM.disambiguate, F.data.startswith("choose::"))
async def grade_choose(cb, state: FSMContext):
    _, code = cb.data.split("::", 1)
    r = roster.get_by_student_code(code)
    label = f"{r['last_name_ru']} {r['first_name_ru']} ({r.get('group','')})"
    await state.update_data(student_code=code, student_label=label)
    await state.set_state(GradeFSM.week)
    await cb.message.edit_text(f"Выбран: {label}\nТеперь введите номер недели (например, 5).")
    await cb.answer()

@router.message(GradeFSM.week, F.text)
async def grade_week(msg: Message, state: FSMContext):
    wk = (msg.text or "").strip()
    if not wk.isdigit():
        return await msg.answer("Неделя должна быть числом. Попробуйте ещё раз.")
    await state.update_data(week=wk)
    await state.set_state(GradeFSM.score)
    await msg.answer("Баллы? (например, 9.5)")

@router.message(GradeFSM.score, F.text)
async def grade_score(msg: Message, state: FSMContext):
    try:
        sc = float((msg.text or "").replace(",", "."))
    except ValueError:
        return await msg.answer("Балл должен быть числом. Пример: 9.0")
    await state.update_data(score=sc)
    await state.set_state(GradeFSM.comment)
    await msg.answer("Комментарий? (можно пропустить командой /skip)")

@router.message(Command("skip"))
async def grade_skip(msg: Message, state: FSMContext):
    cur = await state.get_state()
    if cur == GradeFSM.comment:
        await state.update_data(comment="")
        await state.set_state(GradeFSM.confirm)
        data = await state.get_data()
        return await msg.answer(
            f"Проверим:\nСтудент: {data['student_label']}\nНеделя: {data['week']}\nБалл: {data['score']}\nКомментарий: —",
            reply_markup=_kb_confirm()
        )

@router.message(GradeFSM.comment, F.text)
async def grade_comment(msg: Message, state: FSMContext):
    await state.update_data(comment=msg.text or "")
    await state.set_state(GradeFSM.confirm)
    data = await state.get_data()
    await msg.answer(
        f"Проверим:\nСтудент: {data['student_label']}\nНеделя: {data['week']}\nБалл: {data['score']}\nКомментарий: {data['comment'] or '—'}",
        reply_markup=_kb_confirm()
    )

@router.callback_query(GradeFSM.confirm, F.data.startswith("confirm::"))
async def grade_confirm(cb, state: FSMContext):
    _, yesno = cb.data.split("::", 1)
    if yesno == "no":
        await state.clear()
        await cb.message.edit_text("Отменено.")
        return await cb.answer()
    data = await state.get_data()
    code = data["student_code"]
    link = user_links.resolve_user_id_by_student_code(code)
    if not link:
        await cb.message.edit_text("Студент ещё не привязан к Telegram. Попросите пройти /register.")
        return await cb.answer()
    add_or_update_grade(int(link), data["week"], float(data["score"]), data["comment"] or "")
    await state.clear()
    await cb.message.edit_text("✅ Оценка сохранена.")
    await cb.answer()

# ---------- /grade_batch ----------
class BatchFSM(StatesGroup):
    paste = State()
    preview = State()

@router.message(Command("grade_batch"))
async def batch_start(msg: Message, state: FSMContext):
    if resolve_role(msg) not in {"instructor","owner"}:
        return await msg.answer("Недостаточно прав.")
    await state.clear()
    await state.set_state(BatchFSM.paste)
    await msg.answer(
        "Отправьте список строк в формате:\n"
        "`<идентификатор>;<неделя>;<балл>;[комментарий]`\n"
        "Идентификатор: `Иванов B1` ИЛИ `S001` ИЛИ `email`.\n"
        "Примеры:\n"
        "`Иванов B1;5;9.0;Хорошо`\n"
        "`S017;5;10;OK`\n"
        "`ivanov@u.edu;5;8.5;`"
    )

def _parse_batch_line(line: str):
    # возвращает (ident, week, score, comment) или None
    raw = [p.strip() for p in line.split(";")]
    if len(raw) < 3:
        return None
    ident, week, score = raw[0], raw[1], raw[2]
    comment = raw[3] if len(raw) >= 4 else ""
    if not week.isdigit():
        return None
    try:
        sc = float(score.replace(",", "."))
    except ValueError:
        return None
    return ident, week, sc, comment

def _resolve_ident(ident: str):
    # пробуем email/Sxxx/фамилия [группа]
    cands = _find_candidates_by_query(ident)
    if not cands:
        return ("not_found", ident, None)
    if len(cands) > 1:
        return ("ambiguous", ident, [f"{c.full_name} {c.group} [{c.student_code}]" for c in cands[:5]])
    c = cands[0]
    if not c.user_id:
        return ("unlinked", ident, f"{c.full_name} {c.group} [{c.student_code}]")
    return ("ok", ident, {"user_id": c.user_id, "label": f"{c.full_name} {c.group}", "student_code": c.student_code})

@router.message(BatchFSM.paste, F.text)
async def batch_paste(msg: Message, state: FSMContext):
    lines = [ln for ln in (msg.text or "").splitlines() if ln.strip()]
    parsed = []
    errors = []
    for ln in lines:
        p = _parse_batch_line(ln)
        if not p:
            errors.append(f"❌ формат: {ln}")
            continue
        ident, week, score, comment = p
        status, _ident, info = _resolve_ident(ident)
        parsed.append({"ident": ident, "week": week, "score": score, "comment": comment, "status": status, "info": info})
    oks = [x for x in parsed if x["status"] == "ok"]
    amb = [x for x in parsed if x["status"] == "ambiguous"]
    unf = [x for x in parsed if x["status"] == "unlinked"]
    nf  = [x for x in parsed if x["status"] == "not_found"]
    await state.update_data(batch=parsed)

    preview = [
        f"Итого строк: {len(parsed)}",
        f"Готово к записи: {len(oks)}",
        f"Требуют уточнения: {len(amb)}",
        f"Не привязаны к TG: {len(unf)}",
        f"Не найдены: {len(nf)}",
    ]
    if amb:
        preview.append("\nНеоднозначные примеры:")
        for x in amb[:5]:
            preview.append(f"- {x['ident']} → {', '.join(x['info'])}")
    if unf:
        preview.append("\nНужно /register (или /link):")
        for x in unf[:5]:
            preview.append(f"- {x['ident']} → {x['info']}")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Записать {len(oks)}", callback_data="batch::commit")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="batch::cancel")],
    ])
    await state.set_state(BatchFSM.preview)
    await msg.answer("\n".join(preview), reply_markup=kb)

@router.callback_query(BatchFSM.preview, F.data.startswith("batch::"))
async def batch_commit(cb, state: FSMContext):
    action = cb.data.split("::", 1)[1]
    if action == "cancel":
        await state.clear()
        await cb.message.edit_text("Отменено.")
        return await cb.answer()
    data = await state.get_data()
    parsed = data.get("batch", [])
    saved = 0
    for x in parsed:
        if x["status"] != "ok":
            continue
        uid = int(x["info"]["user_id"])
        add_or_update_grade(uid, x["week"], float(x["score"]), x["comment"] or "")
        saved += 1
    await state.clear()
    await cb.message.edit_text(f"✅ Записано: {saved}")
    await cb.answer()
