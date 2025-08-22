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
    Главное меню мастера недель - показывает список всех недель с кнопками
    """
    # Проверяем роль студента
    user = users.get_by_tg(actor_tg_id)
    if not user or user.get("role") != "student":
        await message.answer("Команда доступна только студентам. Пройдите регистрацию: /register")
        return
    
    # Получаем список недель
    current_weeks = weeks.get_current_weeks()
    if not current_weeks:
        await message.answer("📚 Информация о неделях пока не загружена.")
        return
    
    # Создаем клавиатуру с неделями
    kb = InlineKeyboardBuilder()
    
    for week_dict in current_weeks:
        button_text = weeks.format_week_button_text(week_dict)
        callback_data = f"week:select:{week_dict['week']}"
        kb.button(text=button_text, callback_data=callback_data)
    
    # Располагаем кнопки по 2 в ряд
    kb.adjust(2)
    
    text = "📚 **Выберите неделю:**\n\n" \
           "🟢 — в срок  \n" \
           "🔴 — просрочено"
    
    await message.answer(text, reply_markup=kb.as_markup())


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
    student_code = user.get("id") if user else None
    
    ta_code = None
    if student_code:
        ta_code = assignments.get_assignment_for_student_code(student_code, week_number)
    
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
    
    # Заголовок с информацией о недели
    status_text = "🔴 ПРОСРОЧЕНО" if week_info["is_overdue"] else "🟢 В СРОК"
    text = f"**Неделя {week_number}: {week_info['title']}**\n\n" \
           f"📅 Дедлайн: {week_info['deadline_str']} ({status_text})\n\n" \
           f"Выберите действие:"
    
    await cb.message.edit_text(text, reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("week:info:"))
async def week_show_info(cb: CallbackQuery, weeks: WeeksService, assignments: AssignmentsService, users: UsersService):
    """Показать описание и дедлайн недели"""
    try:
        week_number = int(cb.data.split(":")[-1])
    except ValueError:
        await cb.answer("Некорректные данные", show_alert=True)
        return
    
    week_info = weeks.get_week(week_number)
    if not week_info:
        await cb.answer("Неделя не найдена", show_alert=True)
        return
    
    # Получаем информацию о назначенном TA
    user = users.get_by_tg(cb.from_user.id)  # Здесь используем real tg_id для поиска
    student_code = user.get("id") if user else None
    
    ta_info = "Не назначен"
    if student_code:
        ta_code = assignments.get_assignment_for_student_code(student_code, week_number)
        if ta_code:
            ta_user = users.get_by_id(ta_code)
            if ta_user:
                ta_name = f"{ta_user.get('last_name', '')} {ta_user.get('first_name', '')}".strip()
                ta_info = f"{ta_name} ({ta_code})"
            else:
                ta_info = ta_code
    
    status_text = "🔴 ПРОСРОЧЕНО" if week_info["is_overdue"] else "🟢 В СРОК"
    
    text = f"📋 **Неделя {week_number}: {week_info['title']}**\n\n" \
           f"📝 **Описание:**\n{week_info['description']}\n\n" \
           f"📅 **Дедлайн:** {week_info['deadline_str']} ({status_text})\n\n" \
           f"👨‍🏫 **Принимает:** {ta_info}"
    
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data=f"week:select:{week_number}")
    
    await cb.message.edit_text(text, reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("week:download:"))
async def week_download_tasks(cb: CallbackQuery):
    """Заглушка для скачивания заданий"""
    week_number = cb.data.split(":")[-1]
    
    text = f"📥 **Скачивание заданий для недели {week_number}**\n\n" \
           f"🚧 Функция в разработке\n\n" \
           f"Пока вы можете найти задания на сайте курса:\n" \
           f"📖 [Программа курса](https://example.com/course)"
    
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data=f"week:select:{week_number}")
    
    await cb.message.edit_text(text, reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("week:upload:"))
async def week_upload_solutions(cb: CallbackQuery):
    """Заглушка для загрузки решений"""
    week_number = cb.data.split(":")[-1]
    
    text = f"📤 **Загрузка решений для недели {week_number}**\n\n" \
           f"🚧 Функция в разработке\n\n" \
           f"Пока отправляйте решения преподавателю напрямую или через другие каналы."
    
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data=f"week:select:{week_number}")
    
    await cb.message.edit_text(text, reply_markup=kb.as_markup())
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
        text = f"📅 **Запись на сдачу недели {week_number}**\n\n" \
               f"🚫 У преподавателя {ta_code} пока нет доступных слотов для записи.\n\n" \
               f"Обратитесь к преподавателю для уточнения расписания."
    else:
        # Подсчитываем доступные слоты
        available_count = 0
        for _, slot_row in ta_slots.iterrows():
            slot_dict = slot_row.to_dict()
            current_bookings = 0
            
            # Считаем текущие бронирования
            try:
                slot_bookings = bookings.list_for_slot(slot_dict["slot_id"])
                if not slot_bookings.empty:
                    active_bookings = slot_bookings
                    if "status" in slot_bookings.columns:
                        active_bookings = slot_bookings[slot_bookings["status"].str.lower().isin(["active", "confirmed"])]
                    current_bookings = len(active_bookings)
            except:
                pass
            
            # Проверяем доступность
            computed_status = slots.get_computed_status(slot_dict, current_bookings)
            if computed_status in ("free_full", "free_partial"):
                available_count += 1
        
        if available_count > 0:
            text = f"📅 **Запись на сдачу недели {week_number}**\n\n" \
                   f"👨‍🏫 Преподаватель: {ta_code}\n" \
                   f"🟢 Доступно слотов: {available_count}\n\n" \
                   f"Для записи используйте старую команду:\n" \
                   f"`/week {week_number}`\n\n" \
                   f"*(В следующей версии будет встроенная запись)*"
        else:
            text = f"📅 **Запись на сдачу недели {week_number}**\n\n" \
                   f"👨‍🏫 Преподаватель: {ta_code}\n" \
                   f"🔴 Все слоты заняты или закрыты\n\n" \
                   f"Обратитесь к преподавателю для добавления новых слотов."
    
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data=f"week:select:{week_number}")
    
    await cb.message.edit_text(text, reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("week:grade:"))
async def week_show_grade(cb: CallbackQuery, weeks: WeeksService, grades: GradeService, users: UsersService):
    """Показать оценку за неделю"""
    try:
        week_number = int(cb.data.split(":")[-1])
    except ValueError:
        await cb.answer("Некорректные данные", show_alert=True)
        return
    
    # Получаем информацию о студенте
    user = users.get_by_tg(cb.from_user.id)  # Используем real tg_id
    student_code = user.get("id") if user else None
    
    if not student_code:
        await cb.answer("Не удалось определить ваш student_code", show_alert=True)
        return
    
    # Ищем оценки по week (предполагаем что task_id = week или есть связь)
    # Пока сделаем заглушку, так как нужно адаптировать GradeService
    
    week_info = weeks.get_week(week_number)
    week_title = week_info["title"] if week_info else f"Неделя {week_number}"
    
    text = f"🎯 **Оценка за {week_title}**\n\n" \
           f"🚧 Функция в разработке\n\n" \
           f"Для просмотра оценок пока используйте команду `/grades`"
    
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data=f"week:select:{week_number}")
    
    await cb.message.edit_text(text, reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data == "week:back")
async def week_back_to_list(cb: CallbackQuery, actor_tg_id: int, weeks: WeeksService, users: UsersService):
    """Возврат к списку недель"""
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
    
    kb.adjust(2)
    
    text = "📚 **Выберите неделю:**\n\n" \
           "🟢 — в срок  \n" \
           "🔴 — просрочено"
    
    await cb.message.edit_text(text, reply_markup=kb.as_markup())
    await cb.answer()