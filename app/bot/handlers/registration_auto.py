import logging
from typing import List, Literal

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

async def try_autolink_after_register(
    msg: Message, 
    state: FSMContext, 
    email: str, 
    last_name_ru: str | None, 
    group: str | None
) -> Literal["prompted", "not_found", "already_linked"]:
    """
    Пытаемся автопривязку. Возвращаем статус:
    - "prompted": показали пользователю диалог, ждём ответа
    - "not_found": никого не нашли
    - "already_linked": уже привязан
    """
    uid = effective_user_id(msg)
    
    # Проверяем, не привязан ли уже
    existing_link = user_links.get_link_by_user_id(uid)
    if existing_link:
        await msg.answer(f"Вы уже привязаны к {existing_link['student_code']}.")
        return "already_linked"
    
    # 1) Пытаемся по email (главный ключ)
    rec = roster.get_by_email(email)
    if rec:
        # Проверяем, не привязан ли этот student_code к другому user_id
        existing_user_link = user_links.get_link_by_email(rec["external_email"])
        if existing_user_link and existing_user_link["user_id"] != str(uid):
            await msg.answer(f"Этот email уже привязан к другому пользователю.")
            return "not_found"
        
        await state.update_data(
            student_code=rec["student_code"], 
            external_email=rec["external_email"]
        )
        text = (
            f"🎯 Нашёл вас в списке студентов:\n"
            f"👤 {rec.get('last_name_ru','')} {rec.get('first_name_ru','')}\n"
            f"🎓 Группа: {rec.get('group','')}\n" 
            f"📧 Email: {rec.get('external_email','')}\n"
            f"🆔 Код: {rec.get('student_code','')}\n\n"
            f"Это вы?"
        )
        await state.set_state(LinkFSM.confirm)
        await msg.answer(text, reply_markup=_kb_yes_no())
        return "prompted"

    # 2) Мягкий поиск: по фамилии + (опц.) группе, если email не нашли
    cands = []
    if last_name_ru:
        cands = roster.find_candidates(last_name_ru, group=group or None, email_part=None)

    if len(cands) == 1:
        rec = cands[0]
        # Проверяем привязку
        existing_user_link = user_links.get_link_by_email(rec["external_email"])
        if existing_user_link and existing_user_link["user_id"] != str(uid):
            await msg.answer(f"Найденный студент уже привязан к другому пользователю.")
            return "not_found"
            
        await state.update_data(
            student_code=rec["student_code"], 
            external_email=rec["external_email"]
        )
        text = (
            f"🔍 По фамилии/группе найден студент:\n"
            f"👤 {rec.get('last_name_ru','')} {rec.get('first_name_ru','')}\n"
            f"🎓 Группа: {rec.get('group','')}\n"
            f"📧 Email: {rec.get('external_email','')}\n" 
            f"🆔 Код: {rec.get('student_code','')}\n\n"
            f"Это вы?"
        )
        await state.set_state(LinkFSM.confirm)
        await msg.answer(text, reply_markup=_kb_yes_no())
        return "prompted"
    
    elif len(cands) > 1:
        # Фильтруем уже привязанных
        available_cands = []
        for c in cands:
            existing_user_link = user_links.get_link_by_email(c["external_email"])
            if not existing_user_link or existing_user_link["user_id"] == str(uid):
                available_cands.append(c)
        
        if len(available_cands) == 0:
            await msg.answer("Найдены кандидаты, но все уже привязаны к другим пользователям.")
            return "not_found"
        elif len(available_cands) == 1:
            # Единственный доступный кандидат
            rec = available_cands[0]
            await state.update_data(
                student_code=rec["student_code"], 
                external_email=rec["external_email"]
            )
            text = (
                f"🔍 Найден подходящий студент:\n"
                f"👤 {rec.get('last_name_ru','')} {rec.get('first_name_ru','')}\n"
                f"🎓 Группа: {rec.get('group','')}\n"
                f"📧 Email: {rec.get('external_email','')}\n"
                f"🆔 Код: {rec.get('student_code','')}\n\n"
                f"Это вы?"
            )
            await state.set_state(LinkFSM.confirm)
            await msg.answer(text, reply_markup=_kb_yes_no())
            return "prompted"
        else:
            # Несколько доступных кандидатов
            await state.update_data(candidates=[c for c in available_cands])
            await state.set_state(LinkFSM.disambiguate)
            await msg.answer(
                "🤔 Найдено несколько подходящих студентов. Выберите себя:",
                reply_markup=_kb_candidates(available_cands)
            )
            return "prompted"

    # Ничего не нашли
    return "not_found"

# --- Обработчики callback кнопок ---
@router.callback_query(LinkFSM.confirm, F.data == "link::yes")
async def cb_link_confirm_yes(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    student_code = data.get("student_code")
    external_email = data.get("external_email")
    
    if not student_code or not external_email:
        await callback.message.edit_text("Ошибка: данные для привязки не найдены.")
        await state.clear()
        return
    
    uid = effective_user_id(callback.message)
    
    # Создаём привязку
    user_links.create_link(uid, student_code, external_email)
    
    await callback.message.edit_text(
        "✅ Отлично! Привязка завершена.\n"
        "🎉 Регистрация полностью завершена!\n\n"
        "Теперь вы можете использовать все функции бота."
    )
    await state.clear()
    await callback.answer()

@router.callback_query(LinkFSM.confirm, F.data == "link::no")
async def cb_link_confirm_no(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "❌ Привязка отменена.\n\n"
        "Вы можете попробовать ручную привязку позже командой:\n"
        "/link <email или код студента>\n\n"
        "🎉 Регистрация в системе завершена, но для полного доступа "
        "к функциям нужна привязка к списку студентов."
    )
    await state.clear()
    await callback.answer()

@router.callback_query(LinkFSM.disambiguate, F.data.startswith("linkchoose::"))
async def cb_link_choose(callback: CallbackQuery, state: FSMContext):
    _, student_code = callback.data.split("::", 1)
    
    # Получаем данные студента
    rec = roster.get_by_student_code(student_code)
    if not rec:
        await callback.message.edit_text("Ошибка: студент не найден.")
        await state.clear()
        return
    
    # Проверяем, не привязан ли уже
    existing_user_link = user_links.get_link_by_email(rec["external_email"])
    uid = effective_user_id(callback.message)
    if existing_user_link and existing_user_link["user_id"] != str(uid):
        await callback.message.edit_text("Этот студент уже привязан к другому пользователю.")
        await state.clear()
        return
    
    # Создаём привязку
    user_links.create_link(uid, student_code, rec["external_email"])
    
    await callback.message.edit_text(
        f"✅ Привязка успешна!\n"
        f"👤 {rec.get('last_name_ru','')} {rec.get('first_name_ru','')}\n"
        f"🎓 Группа: {rec.get('group','')}\n"
        f"🆔 Код: {student_code}\n\n"
        f"🎉 Регистрация полностью завершена!\n"
        f"Теперь вы можете использовать все функции бота."
    )
    await state.clear()
    await callback.answer()

# --- Ручная привязка ---
@router.message(Command("link"))
async def manual_link(msg: Message, command: CommandObject):
    """Ручная привязка к студенту по email или коду"""
    uid = effective_user_id(msg)
    
    # Проверяем, что пользователь зарегистрирован
    user_rec = get_user(uid)
    if not user_rec:
        return await msg.answer("Сначала пройдите регистрацию командой /register")
    
    # Проверяем, не привязан ли уже
    existing_link = user_links.get_link_by_user_id(uid)
    if existing_link:
        return await msg.answer(f"Вы уже привязаны к {existing_link['student_code']}.")
    
    query = (command.args or "").strip()
    if not query:
        return await msg.answer("Использование: /link <email или код студента>\nПример: /link ivanov@u.edu или /link S001")
    
    # Ищем студента
    rec = None
    if "@" in query:
        rec = roster.get_by_email(query)
    elif query.upper().startswith("S"):
        rec = roster.get_by_student_code(query.upper())
    else:
        return await msg.answer("Введите email (содержит @) или код студента (начинается с S)")
    
    if not rec:
        return await msg.answer("Студент не найден в списке.")
    
    # Проверяем, не привязан ли этот студент к другому пользователю
    existing_user_link = user_links.get_link_by_email(rec["external_email"])
    if existing_user_link and existing_user_link["user_id"] != str(uid):
        return await msg.answer("Этот студент уже привязан к другому пользователю.")
    
    # Создаём привязку
    user_links.create_link(uid, rec["student_code"], rec["external_email"])
    
    await msg.answer(
        f"✅ Привязка успешна!\n"
        f"👤 {rec.get('last_name_ru','')} {rec.get('first_name_ru','')}\n"
        f"🎓 Группа: {rec.get('group','')}\n"
        f"📧 Email: {rec.get('external_email','')}\n"
        f"🆔 Код: {rec.get('student_code','')}"
    )