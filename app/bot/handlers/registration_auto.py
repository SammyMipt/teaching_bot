import logging
from typing import List
from dataclasses import dataclass

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from app.bot.auth import resolve_role, effective_user_id
from app.storage import roster, user_links
from app.storage.users import get_user, upsert_user
from app.core.config import settings

log = logging.getLogger(__name__)
router = Router()

# --- FSM для подтверждения привязки после регистрации ---
class LinkFSM(StatesGroup):
    confirm = State()
    disambiguate = State()

def _kb_yes_no() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да", callback_data="link::yes"),
         InlineKeyboardButton(text="❌ Нет", callback_data="link::no")]
    ])

def _kb_candidates(rows: List[dict]) -> InlineKeyboardMarkup:
    # rows: элементы roster (у каждого есть student_code)
    btns = []
    for r in rows[:10]:
        label = f"{r.get('last_name_ru','')} {r.get('first_name_ru','')} ({r.get('group','')}) • {r.get('student_code','')}"
        btns.append([InlineKeyboardButton(text=label, callback_data=f"linkchoose::{r['student_code']}")])
    return InlineKeyboardMarkup(inline_keyboard=btns)

async def try_autolink_after_register(msg: Message, state: FSMContext, email: str, last_name_ru: str | None, group: str | None):
    """
    Зовём это в конце твоего текущего /register (после upsert_user).
    """
    uid = effective_user_id(msg)
    # 1) Пытаемся по email (главный ключ)
    rec = roster.get_by_email(email)
    if rec:
        await state.update_data(student_code=rec["student_code"], external_email=rec["external_email"])
        text = (f"Нашёл вас в списке: {rec.get('last_name_ru','')} {rec.get('first_name_ru','')} "
                f"({rec.get('group','')}). Email: {rec.get('external_email','')}. Код: {rec.get('student_code','')}.\n"
                f"Это вы?")
        await state.set_state(LinkFSM.confirm)
        return await msg.answer(text, reply_markup=_kb_yes_no())

    # 2) Мягкий поиск: по фамилии + (опц.) группе, если email не нашли
    cands = []
    if last_name_ru:
        cands = roster.find_candidates(last_name_ru, group=group or None, email_part=None)

    if len(cands) == 1:
        rec = cands[0]
        await state.update_data(student_code=rec["student_code"], external_email=rec["external_email"])
        text = (f"По фамилии/группе найдено: {rec.get('last_name_ru','')} {rec.get('first_name_ru','')} "
                f"({rec.get('group','')}). Email: {rec.get('external_email','')}. Код: {rec.get('student_code','')}.\n"
                f"Это вы?")
        await state.set_state(LinkFSM.confirm)
        return await msg.answer(text, reply_markup=_kb_yes_no())

    if len(cands) > 1:
        await state.update_data(candidates=cands)
        await state.set_state(LinkFSM.disambiguate)
        return await msg.answer("Нашлось несколько студентов, выберите себя:", reply_markup=_kb_candidates(cands))

    # 3) Вообще не нашли — даём инструкции
    return await msg.answer(
        "Пока не нашёл вас в списке. Проверьте, что email совпадает с LMS.\n"
        "Можно привязаться вручную: пришлите `/link <email>` или `/link <Sxxx>`."
    )

@router.callback_query(LinkFSM.disambiguate, F.data.startswith("linkchoose::"))
async def cb_link_choose(cb: CallbackQuery, state: FSMContext):
    _, code = cb.data.split("::", 1)
    rec = roster.get_by_student_code(code)
    if not rec:
        await cb.answer("Не найдено.")
        return
    await state.update_data(student_code=rec["student_code"], external_email=rec["external_email"])
    await state.set_state(LinkFSM.confirm)
    await cb.message.edit_text(
        f"Вы выбрали: {rec.get('last_name_ru','')} {rec.get('first_name_ru','')} ({rec.get('group','')}). "
        f"Email: {rec.get('external_email','')}. Код: {rec.get('student_code','')}.\n"
        f"Это вы?",
        reply_markup=_kb_yes_no()
    )
    await cb.answer()

@router.callback_query(LinkFSM.confirm, F.data.startswith("link::"))
async def cb_link_confirm(cb: CallbackQuery, state: FSMContext):
    _, ans = cb.data.split("::", 1)
    if ans == "no":
        await state.clear()
        await cb.message.edit_text("Ок, привязку пропустили. Можно выполнить вручную: `/link <email|Sxxx>`.")
        return await cb.answer()

    data = await state.get_data()
    student_code = data.get("student_code")
    external_email = data.get("external_email")
    if not student_code or not external_email:
        await cb.message.edit_text("Что-то пошло не так. Попробуйте /link вручную.")
        await state.clear()
        return await cb.answer()

    try:
        user_links.upsert_link(effective_user_id(cb.message), student_code, external_email, linked_by="auto", status="active")
        await cb.message.edit_text(f"✅ Привязка выполнена: {student_code} ←→ {external_email}")
    except ValueError as e:
        await cb.message.edit_text(f"Не удалось привязать: {e}")
    finally:
        await state.clear()
        await cb.answer()

# --- Ручная привязка: /link <email|Sxxx> ---
@router.message(Command("link"))
async def cmd_link(msg: Message, command: CommandObject):
    ident = (command.args or "").strip()
    if not ident:
        return await msg.answer("Использование: /link <email|Sxxx>")

    # попробуем как email
    rec = roster.get_by_email(ident)
    if not rec and ident.upper().startswith("S"):
        rec = roster.get_by_student_code(ident.upper())

    if not rec:
        return await msg.answer("В roster не найдено. Проверьте email или код Sxxx.")

    try:
        user_links.upsert_link(effective_user_id(msg), rec["student_code"], rec["external_email"], linked_by="self", status="active")
        await msg.answer(f"✅ Привязка выполнена: {rec['student_code']} ←→ {rec['external_email']}")
    except ValueError as e:
        await msg.answer(f"Не удалось привязать: {e}")

# --- Жёсткое утверждение владельцем: /link_approve <user_id> <Sxxx> ---
@router.message(Command("link_approve"))
async def cmd_link_approve(msg: Message, command: CommandObject):
    if resolve_role(msg) != "owner":
        return await msg.answer("Только для владельца курса.")
    parts = (command.args or "").split()
    if len(parts) != 2 or not parts[0].isdigit():
        return await msg.answer("Использование: /link_approve <user_id> <Sxxx>")
    user_id = int(parts[0]); code = parts[1].upper()
    rec = roster.get_by_student_code(code)
    if not rec:
        return await msg.answer("Код Sxxx не найден в roster.")
    try:
        user_links.upsert_link(user_id, rec["student_code"], rec["external_email"], linked_by="owner", status="active")
        await msg.answer(f"✅ Привязка подтверждена: user_id={user_id} ←→ {rec['student_code']}")
    except ValueError as e:
        await msg.answer(f"Не удалось привязать: {e}")
