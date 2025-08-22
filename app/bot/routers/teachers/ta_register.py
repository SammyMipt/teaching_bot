# Замените содержимое app/bot/routers/teachers/ta_register.py

from __future__ import annotations
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from aiogram.utils.keyboard import InlineKeyboardBuilder
from app.services.users_service import UsersService
from app.services.roster_ta_service import RosterTaService
from app.services.audit_service import AuditService

router = Router(name="teachers_ta_register")

class TaRegFSM(StatesGroup):
    waiting_invite_code = State()
    waiting_ta_selection = State()
    waiting_confirmation = State()

@router.message(F.text == "/register_ta")
async def register_ta_start(message: Message, actor_tg_id: int, users: UsersService, state: FSMContext):
    """Начало регистрации преподавателя"""
    # Проверяем, не зарегистрирован ли уже как преподаватель
    user = users.get_by_tg(actor_tg_id)
    if user and user.get("role") in ("ta", "owner"):
        await message.answer("Вы уже зарегистрированы как преподаватель.")
        return
    
    await state.clear()
    await state.set_state(TaRegFSM.waiting_invite_code)
    await message.answer(
        "🔐 <b>Регистрация преподавателя</b>\n\n"
        "Введите код приглашения для преподавателей.\n"
        "Для отмены: /cancel",
        parse_mode="HTML"
    )

@router.message(TaRegFSM.waiting_invite_code, F.text)
async def ta_check_invite_code(message: Message, state: FSMContext, roster_ta: RosterTaService, 
                               audit: AuditService, ta_invite_code: str | None):
    """Проверка кода приглашения"""
    code = message.text.strip()
    
    # Проверяем на отмену
    if code.lower() in ["/cancel", "cancel"]:
        await state.clear()
        await message.answer("❌ Регистрация преподавателя отменена.")
        return
    
    if not ta_invite_code or code != ta_invite_code:
        audit.log(actor_tg_id=message.from_user.id, action="ta_register_bad_code",
                  target=str(message.from_user.id), meta={"code": code})
        await message.answer("❌ Код неверный. Попробуйте снова или обратитесь к владельцу курса.")
        return
    
    # Код верный, получаем список преподавателей из ростера
    tas = roster_ta.get_all_tas()
    if not tas:
        await message.answer("❌ Ростер преподавателей пуст. Обратитесь к владельцу курса.")
        await state.clear()
        return
    
    # Формируем клавиатуру с преподавателями
    kb = InlineKeyboardBuilder()
    for ta in tas:
        ta_id = ta["ta_id"]
        full_name = ta["full_name"]
        kb.button(text=f"{full_name} ({ta_id})", callback_data=f"ta_reg:select:{ta_id}")
    
    kb.button(text="❌ Отмена", callback_data="ta_reg:cancel")
    kb.adjust(1)  # По одной кнопке в ряд
    
    await state.set_state(TaRegFSM.waiting_ta_selection)
    await message.answer(
        "✅ <b>Код принят!</b>\n\n"
        "Выберите себя из списка преподавателей:",
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )

@router.callback_query(TaRegFSM.waiting_ta_selection, F.data.startswith("ta_reg:select:"))
async def ta_select_from_roster(cb: CallbackQuery, state: FSMContext, roster_ta: RosterTaService):
    """Выбор преподавателя из ростера"""
    ta_id = cb.data.split(":")[-1]
    
    # Получаем данные преподавателя
    ta_data = roster_ta.get_ta_by_id(ta_id)
    if not ta_data:
        await cb.answer("Преподаватель не найден в ростере", show_alert=True)
        return
    
    # Сохраняем выбор в состоянии
    await state.update_data(selected_ta=ta_data)
    
    # Формируем подтверждение
    full_name = ta_data["full_name"]
    ta_id = ta_data["ta_id"]
    
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подтвердить", callback_data="ta_reg:confirm")
    kb.button(text="⬅️ Назад к списку", callback_data="ta_reg:back")
    kb.button(text="❌ Отмена", callback_data="ta_reg:cancel")
    
    await state.set_state(TaRegFSM.waiting_confirmation)
    await cb.message.edit_text(
        f"📋 <b>Подтверждение регистрации</b>\n\n"
        f"<b>Выбран:</b> {full_name}\n"
        f"<b>ID:</b> {ta_id}\n\n"
        f"Подтвердить регистрацию?",
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )
    await cb.answer()

@router.callback_query(TaRegFSM.waiting_ta_selection, F.data == "ta_reg:back")
@router.callback_query(TaRegFSM.waiting_confirmation, F.data == "ta_reg:back")
async def ta_back_to_list(cb: CallbackQuery, state: FSMContext, roster_ta: RosterTaService):
    """Возврат к списку преподавателей"""
    tas = roster_ta.get_all_tas()
    if not tas:
        await cb.message.edit_text("❌ Ростер преподавателей пуст.")
        await state.clear()
        await cb.answer()
        return
    
    kb = InlineKeyboardBuilder()
    for ta in tas:
        ta_id = ta["ta_id"]
        full_name = ta["full_name"]
        kb.button(text=f"{full_name} ({ta_id})", callback_data=f"ta_reg:select:{ta_id}")
    
    kb.button(text="❌ Отмена", callback_data="ta_reg:cancel")
    kb.adjust(1)
    
    await state.set_state(TaRegFSM.waiting_ta_selection)
    await cb.message.edit_text(
        "✅ <b>Код принят!</b>\n\n"
        "Выберите себя из списка преподавателей:",
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )
    await cb.answer()

@router.callback_query(TaRegFSM.waiting_confirmation, F.data == "ta_reg:confirm")
async def ta_confirm_registration(cb: CallbackQuery, actor_tg_id: int, state: FSMContext, 
                                  users: UsersService, audit: AuditService):
    """Подтверждение регистрации преподавателя"""
    data = await state.get_data()
    selected_ta = data.get("selected_ta")
    
    if not selected_ta:
        await cb.answer("Ошибка: данные преподавателя не найдены", show_alert=True)
        return
    
    ta_id = selected_ta["ta_id"]
    first_name = selected_ta.get("first_name_ru", "")
    last_name = selected_ta.get("last_name_ru", "")
    full_name = selected_ta["full_name"]
    
    # Проверяем, не занят ли этот ta_id другим пользователем
    existing_user = users.get_by_id(ta_id)
    if existing_user and str(existing_user.get("tg_id")) != str(actor_tg_id):
        await cb.message.edit_text(
            f"❌ Преподаватель {full_name} ({ta_id}) уже привязан к другому аккаунту.\n"
            f"Обратитесь к владельцу курса."
        )
        await state.clear()
        await cb.answer()
        return
    
    # Регистрируем преподавателя
    try:
        users.upsert_basic(
            tg_id=actor_tg_id,
            role="ta",
            first_name=first_name,
            last_name=last_name,
            username=cb.from_user.username or "",
            email="",
            id=ta_id
        )
        
        audit.log(
            actor_tg_id=actor_tg_id, 
            action="ta_register_success",
            target=ta_id, 
            meta=selected_ta
        )
        
        await cb.message.edit_text(
            f"🎉 <b>Регистрация завершена!</b>\n\n"
            f"<b>Добро пожаловать:</b> {full_name}\n"
            f"<b>Ваша роль:</b> преподаватель\n"
            f"<b>ID:</b> {ta_id}\n\n"
            f"📅 Создайте расписание: /schedule\n"
            f"🔍 Посмотрите слоты: /myslots",
            parse_mode="HTML"
        )
        await state.clear()
        await cb.answer("Регистрация успешна! 🎉")
        
    except Exception as e:
        audit.log(
            actor_tg_id=actor_tg_id,
            action="ta_register_error", 
            target=ta_id,
            meta={"error": str(e)}
        )
        await cb.message.edit_text(
            f"❌ Ошибка регистрации: {str(e)}\n"
            f"Обратитесь к владельцу курса."
        )
        await state.clear()
        await cb.answer()

@router.callback_query(TaRegFSM.waiting_ta_selection, F.data == "ta_reg:cancel")
@router.callback_query(TaRegFSM.waiting_confirmation, F.data == "ta_reg:cancel")
async def ta_cancel_registration(cb: CallbackQuery, state: FSMContext):
    """Отмена регистрации"""
    await state.clear()
    await cb.message.edit_text("❌ Регистрация отменена.")
    await cb.answer()

# Обработчик текстовой отмены - УПРОЩЕННАЯ ВЕРСИЯ
@router.message(F.text.in_(["/cancel", "cancel"]))
async def ta_cancel_text(message: Message, state: FSMContext):
    """Отмена регистрации через текстовую команду"""
    current_state = await state.get_state()
    
    # Проверяем, что мы в процессе регистрации TA
    if current_state and "TaRegFSM" in current_state:
        await state.clear()
        await message.answer("❌ Регистрация преподавателя отменена.")
    else:
        # Если не в процессе TA регистрации, просто сообщаем
        await message.answer("Нечего отменять.")

# Отладочные команды
@router.message(F.text == "/debug_ta_state")
async def debug_ta_state(message: Message, state: FSMContext):
    """Отладка состояния FSM для TA регистрации"""
    current_state = await state.get_state()
    data = await state.get_data()
    
    await message.answer(
        f"🔍 <b>Отладка состояния TA FSM:</b>\n\n"
        f"• Текущее состояние: {current_state or 'None'}\n"
        f"• Данные состояния: {data}\n"
        f"• User ID: {message.from_user.id}",
        parse_mode="HTML"
    )

@router.message(F.text == "/debug_roster_ta")
async def debug_roster_ta(message: Message, roster_ta: RosterTaService):
    """Отладка ростера преподавателей"""
    try:
        tas = roster_ta.get_all_tas()
        if not tas:
            await message.answer("❌ Ростер преподавателей пуст")
            return
        
        lines = ["🔍 <b>Ростер преподавателей:</b>\n"]
        for ta in tas[:5]:  # Показываем первых 5
            lines.append(f"• {ta['full_name']} ({ta['ta_id']})")
        
        if len(tas) > 5:
            lines.append(f"... и еще {len(tas) - 5}")
        
        await message.answer("\n".join(lines), parse_mode="HTML")
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")