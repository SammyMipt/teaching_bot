from __future__ import annotations
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from app.services.weeks_service import WeeksService
from app.services.assignments_service import AssignmentsService
from app.services.users_service import UsersService
from app.services.slot_service import SlotService
from app.services.booking_service import BookingService
from app.services.grade_service import GradeService

router = Router(name="students_week_master")

@router.message(F.text == "/week")
async def week_master_start(
    message: Message, 
    actor_tg_id: int,
    weeks: WeeksService,
    users: UsersService
):
    """
    Главное меню мастера недель - показывает 3 ближайшие недели + кнопку "показать все"
    """
    # Проверяем роль студента
    user = users.get_by_tg(actor_tg_id)
    if not user or user.get("role") != "student":
        await message.answer("Команда доступна только студентам. Пройдите регистрацию: /register")
        return
    
    # Получаем 3 ближайшие недели
    current_weeks = weeks.get_current_weeks()
    if not current_weeks:
        await message.answer("📚 Информация о неделях пока не загружена.")
        return
    
    # Создаем клавиатуру с неделями (без индикаторов актуальности)
    kb = InlineKeyboardBuilder()
    
    for week_dict in current_weeks:
        button_text = weeks.format_week_button_text(week_dict)
        callback_data = f"week:select:{week_dict['week']}"
        kb.button(text=button_text, callback_data=callback_data)
    
    # Кнопка "Показать все недели"
    kb.button(text="📋 Показать все недели", callback_data="week:show_all")
    
    # Располагаем кнопки по 1 в ряд
    kb.adjust(1)
    
    text = "📚 <b>Выберите неделю:</b>"
    
    await message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")


@router.callback_query(F.data == "week:show_all")
async def week_show_all(cb: CallbackQuery, weeks: WeeksService):
    """Показать все недели курса"""
    all_weeks = weeks.get_all_weeks()
    if not all_weeks:
        await cb.answer("Недели не загружены", show_alert=True)
        return
    
    kb = InlineKeyboardBuilder()
    
    for week_dict in all_weeks:
        button_text = weeks.format_week_button_text(week_dict)
        callback_data = f"week:select:{week_dict['week']}"
        kb.button(text=button_text, callback_data=callback_data)
    
    # Кнопка назад к основному списку
    kb.button(text="⬅️ Назад к основному списку", callback_data="week:back_to_main")
    
    # Располагаем кнопки по 1 в ряд
    kb.adjust(1)
    
    text = "📚 <b>Все недели курса:</b>"
    
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data == "week:back_to_main")
async def week_back_to_main(cb: CallbackQuery, weeks: WeeksService):
    """Возврат к основному списку (3 ближайшие недели)"""
    current_weeks = weeks.get_current_weeks()
    if not current_weeks:
        await cb.message.edit_text("📚 Информация о неделях пока не загружена.")
        await cb.answer()
        return
    
    kb = InlineKeyboardBuilder()
    
    for week_dict in current_weeks:
        button_text = weeks.format_week_button_text(week_dict)
        callback_data = f"week:select:{week_dict['week']}"
        kb.button(text=button_text, callback_data=callback_data)
    
    # Кнопка "Показать все недели"
    kb.button(text="📋 Показать все недели", callback_data="week:show_all")
    
    kb.adjust(1)
    
    text = "📚 <b>Выберите неделю:</b>"
    
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.startswith("week:select:"))
async def week_select_menu(
    cb: CallbackQuery,
    actor_tg_id: int,
    weeks: WeeksService,
    assignments: AssignmentsService,
    users: UsersService
):
    """
    Меню действий для выбранной недели
    """
    try:
        week_number = int(cb.data.split(":")[-1])
    except ValueError:
        await cb.answer("Некорректные данные", show_alert=True)
        return
    
    # Получаем информацию о недели
    week_info = weeks.get_week(week_number)
    if not week_info:
        await cb.answer("Неделя не найдена", show_alert=True)
        return
    
    # Проверяем назначение TA для этой недели
    user = users.get_by_tg(actor_tg_id)
    # В зависимости от того, как регистрируется пользователь, student_code может быть в поле "id" или "student_code"
    student_code = user.get("id") if user else None
    if not student_code and user:
        student_code = user.get("student_code")
    
    ta_code = None
    if student_code:
        ta_code = assignments.get_assignment_for_student_code(str(student_code), week_number)
    
    # Формируем меню действий
    kb = InlineKeyboardBuilder()
    
    # 1. Описание и дедлайн
    kb.button(
        text="📋 Описание и дедлайн", 
        callback_data=f"week:info:{week_number}"
    )
    
    # 2. Получить задачи (пока заглушка)
    kb.button(
        text="📥 Получить задачи и вопросы", 
        callback_data=f"week:download:{week_number}"
    )
    
    # 3. Загрузить решения (пока заглушка)  
    kb.button(
        text="📤 Загрузить решения", 
        callback_data=f"week:upload:{week_number}"
    )
    
    # 4. Запись на сдачу (только если есть назначенный TA)
    if ta_code:
        kb.button(
            text="📅 Запись на сдачу", 
            callback_data=f"week:booking:{week_number}:{ta_code}"
        )
    
    # 5. Узнать оценку
    kb.button(
        text="🎯 Узнать оценку", 
        callback_data=f"week:grade:{week_number}"
    )
    
    # Кнопка назад
    kb.button(text="⬅️ Назад к списку недель", callback_data="week:back")
    
    # Располагаем по 1 кнопке в ряд для основных действий
    kb.adjust(1)
    
    # Заголовок с информацией о недели (обновленный формат дедлайна)
    status_emoji = "🔴" if week_info["is_overdue"] else "🟢"
    
    text = f"<b>Неделя {week_number}: {week_info['title']}</b>\n\n" \
           f"📅 Дедлайн: {week_info['deadline_str']} {status_emoji}\n\n" \
           f"Выберите действие:"
    
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.startswith("week:info:"))
async def week_show_info(cb: CallbackQuery, actor_tg_id: int, weeks: WeeksService, assignments: AssignmentsService, users: UsersService):
    """Показать описание и дедлайн недели С информацией о назначенном TA"""
    try:
        week_number = int(cb.data.split(":")[-1])
    except ValueError:
        await cb.answer("Некорректные данные", show_alert=True)
        return
    
    week_info = weeks.get_week(week_number)
    if not week_info:
        await cb.answer("Неделя не найдена", show_alert=True)
        return
    
    # ИСПРАВЛЕНО: используем actor_tg_id вместо cb.from_user.id
    user = users.get_by_tg(actor_tg_id)
    # В зависимости от того, как регистрируется пользователь, student_code может быть в поле "id" или "student_code"
    student_code = user.get("id") if user else None
    if not student_code and user:
        student_code = user.get("student_code")
    
    ta_info = "Не назначен"
    if student_code:
        ta_code = assignments.get_assignment_for_student_code(str(student_code), week_number)
        if ta_code:
            ta_user = users.get_by_id(ta_code)
            if ta_user:
                ta_name = f"{ta_user.get('last_name', '')} {ta_user.get('first_name', '')}".strip()
                ta_info = f"{ta_name} ({ta_code})"
            else:
                ta_info = ta_code
    
    status_emoji = "🔴" if week_info["is_overdue"] else "🟢"
    
    text = f"📋 <b>Неделя {week_number}: {week_info['title']}</b>\n\n" \
           f"📝 <b>Описание:</b>\n{week_info['description']}\n\n" \
           f"📅 <b>Дедлайн:</b> {week_info['deadline_str']} {status_emoji}\n\n" \
           f"👨‍🏫 <b>Принимает:</b> {ta_info}"
    
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data=f"week:select:{week_number}")
    
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.startswith("week:download:"))
async def week_download_tasks(cb: CallbackQuery):
    """Заглушка для скачивания заданий"""
    week_number = cb.data.split(":")[-1]
    
    text = f"📥 <b>Скачивание заданий для недели {week_number}</b>\n\n" \
           f"🚧 Функция в разработке\n\n" \
           f"Пока вы можете найти задания на сайте курса:\n" \
           f"📖 <a href='https://example.com/course'>Программа курса</a>"
    
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data=f"week:select:{week_number}")
    
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.startswith("week:upload:"))
async def week_upload_solutions(cb: CallbackQuery):
    """Заглушка для загрузки решений"""
    week_number = cb.data.split(":")[-1]
    
    text = f"📤 <b>Загрузка решений для недели {week_number}</b>\n\n" \
           f"🚧 Функция в разработке\n\n" \
           f"Пока отправляйте решения преподавателю напрямую или через другие каналы."
    
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data=f"week:select:{week_number}")
    
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.startswith("week:booking:"))
async def week_booking_redirect(cb: CallbackQuery, slots: SlotService, bookings: BookingService, users: UsersService):
    """Перенаправление на запись к назначенному TA"""
    try:
        parts = cb.data.split(":")
        week_number = int(parts[2])
        ta_code = parts[3]
    except (ValueError, IndexError):
        await cb.answer("Некорректные данные", show_alert=True)
        return
    
    # Получаем ID TA для поиска слотов
    ta_id = users.get_ta_id_by_code(ta_code)
    if not ta_id:
        await cb.answer("Преподаватель не найден", show_alert=True)
        return
    
    # Получаем доступные слоты TA
    slots_df = slots.table.read()
    ta_slots = slots_df[slots_df["ta_id"] == ta_id] if not slots_df.empty else pd.DataFrame()
    
    if ta_slots.empty:
        text = f"📅 <b>Запись на сдачу недели {week_number}</b>\n\n" \
               f"🚫 У преподавателя {ta_code} пока нет доступных слотов для записи.\n\n" \
               f"Обратитесь к преподавателю для уточнения расписания."
        
        kb = InlineKeyboardBuilder()
        kb.button(text="⬅️ Назад", callback_data=f"week:select:{week_number}")
        
        await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
        await cb.answer()
        return
    
    # Здесь можно добавить логику перенаправления к слотам TA
    # Пока делаем заглушку
    text = f"📅 <b>Запись на сдачу недели {week_number}</b>\n\n" \
           f"👨‍🏫 Принимает: {ta_code}\n\n" \
           f"🚧 Функция записи в разработке\n\n" \
           f"Пока обратитесь к преподавателю напрямую."
    
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data=f"week:select:{week_number}")
    
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.startswith("week:grade:"))
async def week_show_grade(cb: CallbackQuery, actor_tg_id: int, weeks: WeeksService, grades: GradeService, users: UsersService):
    """Показать оценку за неделю"""
    try:
        week_number = int(cb.data.split(":")[-1])
    except ValueError:
        await cb.answer("Некорректные данные", show_alert=True)
        return
    
    # ИСПРАВЛЕНО: используем actor_tg_id вместо cb.from_user.id
    user = users.get_by_tg(actor_tg_id)
    # В зависимости от того, как регистрируется пользователь, student_code может быть в поле "id" или "student_code"
    student_code = user.get("id") if user else None
    if not student_code and user:
        student_code = user.get("student_code")
    
    if not student_code:
        await cb.answer("Не удалось определить ваш student_code", show_alert=True)
        return
    
    # Ищем оценки по week (предполагаем что task_id = week или есть связь)
    # Пока сделаем заглушку, так как нужно адаптировать GradeService
    
    week_info = weeks.get_week(week_number)
    week_title = week_info["title"] if week_info else f"Неделя {week_number}"
    
    text = f"🎯 <b>Оценка за {week_title}</b>\n\n" \
           f"🚧 Функция в разработке\n\n" \
           f"Для просмотра оценок пока используйте команду /grades"
    
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data=f"week:select:{week_number}")
    
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data == "week:back")
async def week_back_to_list(cb: CallbackQuery, actor_tg_id: int, weeks: WeeksService, users: UsersService):
    """Возврат к списку недель (3 ближайшие)"""
    # Повторяем логику из week_master_start
    user = users.get_by_tg(actor_tg_id)
    if not user or user.get("role") != "student":
        await cb.answer("Доступно только студентам", show_alert=True)
        return
    
    current_weeks = weeks.get_current_weeks()
    if not current_weeks:
        await cb.message.edit_text("📚 Информация о неделях пока не загружена.")
        await cb.answer()
        return
    
    kb = InlineKeyboardBuilder()
    
    for week_dict in current_weeks:
        button_text = weeks.format_week_button_text(week_dict)
        callback_data = f"week:select:{week_dict['week']}"
        kb.button(text=button_text, callback_data=callback_data)
    
    # Кнопка "Показать все недели"
    kb.button(text="📋 Показать все недели", callback_data="week:show_all")
    
    kb.adjust(1)
    
    text = "📚 <b>Выберите неделю:</b>"
    
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    await cb.answer()