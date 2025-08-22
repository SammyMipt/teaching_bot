"""
Главный роутер для студентов с новым UX согласно спецификации.
Реализует главное меню и интеграцию с существующими функциями.

Структура:
1. Главное меню (/student)
2. WIC - Работа с неделями (интеграция с существующей системой)  
3. Мои записи на сдачу
4. Мои оценки (интеграция с /grades)
5. История сдач (заглушка)
6. Агрегированные статусы недель
7. Анти-дублирование записей
"""

from __future__ import annotations
import logging
from datetime import datetime, timezone
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

# Services
from app.services.users_service import UsersService
from app.services.weeks_service import WeeksService
from app.services.assignments_service import AssignmentsService
from app.services.slot_service import SlotService
from app.services.booking_service import BookingService
from app.services.grade_service import GradeService
from app.services.submission_service import SubmissionService

router = Router(name="students_main")
log = logging.getLogger(__name__)

# ================================================================================================
# FSM STATES
# ================================================================================================

class StudentFSM(StatesGroup):
    """FSM состояния для студентов"""
    # WIC States
    wic_week_selected = State()
    week_solution_upload_wait = State()
    
    # Booking States  
    booking_resign_pick_slot = State()

# ================================================================================================
# CALLBACK DATA HELPERS - единый формат r=s;a=action;...
# ================================================================================================

def build_callback(action: str, **kwargs) -> str:
    """Построить callback_data в едином формате r=s;a=action;w=week;..."""
    parts = [f"r=s", f"a={action}"]
    
    for key, value in kwargs.items():
        if value is not None:
            parts.append(f"{key}={value}")
    
    result = ";".join(parts)
    # Telegram ограничение 64 байта
    if len(result) > 63:
        log.warning(f"Callback data too long ({len(result)}): {result}")
    return result

def parse_callback(callback_data: str) -> dict:
    """Парсинг callback_data"""
    result = {}
    try:
        parts = callback_data.split(";")
        for part in parts:
            if "=" in part:
                key, value = part.split("=", 1)
                result[key] = value
    except Exception as e:
        log.error(f"Error parsing callback: {callback_data}, error: {e}")
    return result

# ================================================================================================
# АГРЕГИРОВАННЫЕ СТАТУСЫ НЕДЕЛЬ (по приоритету)
# ================================================================================================

def get_week_aggregated_status(
    week_number: int, 
    student_code: str, 
    weeks: WeeksService,
    bookings: BookingService, 
    grades: GradeService,
    submissions: SubmissionService
) -> dict:
    """
    Вычислить агрегированный статус недели для студента по приоритету:
    1) 🟣 Оценено (есть grade)
    2) 🟡 Ожидает проверки (есть загрузка, grade нет)
    3) 🟠 Слот идёт сейчас (запись есть, время «сейчас»)
    4) 🟢 Запись оформлена (будущее)
    5) ⚫ Слот прошёл, загрузки нет
    6) ⚪ Запись отменена (и нет другой актуальной на неделю)
    7) 🔵 Нет записи
    """
    week_info = weeks.get_week(week_number)
    now = datetime.now(timezone.utc)
    
    # Проверяем оценку (приоритет 1)
    try:
        # Пытаемся найти оценку через grades service
        grade_df = grades.table.read()
        if not grade_df.empty:
            student_grades = grade_df[
                (grade_df["student_code"].astype(str) == str(student_code)) &
                (grade_df["task_id"].asstr().str.contains(f"W{week_number:02d}", na=False))
            ]
            if not student_grades.empty:
                grade_value = student_grades.iloc[-1]["points"]
                return {
                    "status": "graded",
                    "emoji": "🟣",
                    "text": f"Оценено ({grade_value})",
                    "priority": 1
                }
    except Exception as e:
        log.debug(f"Error checking grades for week {week_number}: {e}")
    
    # Проверяем загрузки (приоритет 2)
    try:
        submissions_df = submissions.table.read()
        if not submissions_df.empty:
            student_submissions = submissions_df[
                (submissions_df["student_code"].astype(str) == str(student_code)) &
                (submissions_df["task_id"].asstr().str.contains(f"W{week_number:02d}", na=False))
            ]
            if not student_submissions.empty:
                return {
                    "status": "awaiting_review", 
                    "emoji": "🟡",
                    "text": "Ожидает проверки",
                    "priority": 2
                }
    except Exception as e:
        log.debug(f"Error checking submissions for week {week_number}: {e}")
    
    # Проверяем записи на слоты (приоритеты 3-6)
    try:
        bookings_df = bookings.table.read()
        if not bookings_df.empty:
            # Находим записи студента
            student_bookings = bookings_df[
                (bookings_df["student_tg_id"].astype(str) == str(student_code))  # Возможно нужно tg_id
            ]
            
            # TODO: Здесь нужна логика связи booking -> slot -> week
            # Пока упрощенная логика
            active_bookings = student_bookings[
                student_bookings["status"].str.lower().isin(["active", "confirmed"])
            ]
            
            if not active_bookings.empty:
                # Упрощенно считаем что есть активная запись
                return {
                    "status": "booked_future",
                    "emoji": "🟢", 
                    "text": "Запись оформлена",
                    "priority": 4
                }
    except Exception as e:
        log.debug(f"Error checking bookings for week {week_number}: {e}")
    
    # По умолчанию - нет записи (приоритет 7)
    return {
        "status": "no_booking",
        "emoji": "🔵",
        "text": "Нет записи",
        "priority": 7
    }

# ================================================================================================
# ГЛАВНОЕ МЕНЮ СТУДЕНТА
# ================================================================================================

@router.message(F.text == "/student")
async def student_main_menu(
    message: Message, 
    actor_tg_id: int, 
    users: UsersService
):
    """Главное меню студента согласно UX спецификации"""
    # Проверяем роль
    user = users.get_by_tg(actor_tg_id)
    if not user or user.get("role") != "student":
        await message.answer(
            "❌ Команда доступна только зарегистрированным студентам.\n"
            "Пройдите регистрацию: /register"
        )
        return
    
    # Создаем главное меню
    kb = InlineKeyboardBuilder()
    
    kb.button(
        text="📘 WIC — Работа с неделями",
        callback_data=build_callback("wic_main")
    )
    
    kb.button(
        text="📅 Мои записи на сдачу", 
        callback_data=build_callback("my_bookings_list")
    )
    
    kb.button(
        text="📊 Мои оценки",
        callback_data=build_callback("my_grades_list")
    )
    
    kb.button(
        text="📜 История сдач",
        callback_data=build_callback("history_weeks_list")
    )
    
    kb.adjust(1)  # По одной кнопке в ряд
    
    # Персонализированное приветствие
    student_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
    if not student_name:
        student_name = "Студент"
    
    text = f"👋 <b>Добро пожаловать, {student_name}!</b>\n\n" \
           f"📚 Выберите нужный раздел:"
    
    await message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")

# ================================================================================================
# WIC - РАБОТА С НЕДЕЛЯМИ (интеграция с существующей системой)
# ================================================================================================

@router.callback_query(F.data == build_callback("wic_main"))
async def wic_main_handler(
    cb: CallbackQuery,
    actor_tg_id: int,
    weeks: WeeksService,
    users: UsersService
):
    """WIC главный экран - выбор недели (интеграция с существующим /week)"""
    await cb.answer()
    
    user = users.get_by_tg(actor_tg_id) 
    if not user or user.get("role") != "student":
        await cb.message.edit_text("❌ Доступно только студентам")
        return
    
    # Получаем недели (используем существующую логику)
    current_weeks = weeks.get_current_weeks()
    if not current_weeks:
        await cb.message.edit_text(
            "📚 Информация о неделях пока не загружена.\n\n"
            f"{build_back_to_main_menu()}"
        )
        return
    
    # Создаем список недель с агрегированными статусами
    kb = InlineKeyboardBuilder()
    
    # Получаем student_code для статусов
    student_code = user.get("id") or user.get("student_code")
    
    for week_dict in current_weeks:
        week_num = week_dict["week"]
        week_title = week_dict["title"]
        
        # Агрегированный статус
        if student_code:
            # TODO: передать нужные сервисы для полного статуса
            status_info = {"emoji": "🔵", "text": "Нет записи"}  # Заглушка пока
        else:
            status_info = {"emoji": "❓", "text": "Статус неизвестен"}
        
        button_text = f"{status_info['emoji']} W{week_num:02d} — {week_title}"
        callback_data = build_callback("week_menu", w=week_num)
        
        kb.button(text=button_text, callback_data=callback_data)
    
    # Кнопка "Показать все недели"  
    kb.button(
        text="📋 Показать все недели",
        callback_data=build_callback("wic_show_all")
    )
    
    # Кнопка назад
    kb.button(
        text="⬅️ Назад в главное меню",
        callback_data=build_callback("back_to_main")
    )
    
    kb.adjust(1)
    
    text = "📘 <b>WIC — Работа с неделями</b>\n\n" \
           "📚 Выберите неделю для работы:"
    
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data == build_callback("wic_show_all"))
async def wic_show_all_weeks(
    cb: CallbackQuery,
    weeks: WeeksService,
    users: UsersService,
    actor_tg_id: int
):
    """Показать все недели курса"""
    await cb.answer()
    
    all_weeks = weeks.get_all_weeks() 
    if not all_weeks:
        await cb.message.edit_text("📚 Недели не загружены")
        return
    
    kb = InlineKeyboardBuilder()
    
    user = users.get_by_tg(actor_tg_id)
    student_code = user.get("id") or user.get("student_code") if user else None
    
    for week_dict in all_weeks:
        week_num = week_dict["week"]
        week_title = week_dict["title"]
        
        # Агрегированный статус (заглушка)
        status_emoji = "🔵"  # TODO: полный расчет статуса
        
        button_text = f"{status_emoji} W{week_num:02d} — {week_title}"
        callback_data = build_callback("week_menu", w=week_num)
        
        kb.button(text=button_text, callback_data=callback_data)
    
    # Назад к основному списку
    kb.button(
        text="⬅️ К основному списку", 
        callback_data=build_callback("wic_main")
    )
    
    kb.adjust(1)
    
    text = "📚 <b>Все недели курса:</b>"
    
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

# ================================================================================================
# МЕНЮ НЕДЕЛИ (интеграция с существующей week_master логикой)
# ================================================================================================

@router.callback_query(F.data.regexp(r"r=s;a=week_menu;w=\d+"))
async def week_menu_handler(
    cb: CallbackQuery,
    actor_tg_id: int,
    weeks: WeeksService,
    assignments: AssignmentsService,
    users: UsersService
):
    """Меню действий для выбранной недели"""
    await cb.answer()
    
    # Парсим callback
    data = parse_callback(cb.data)
    try:
        week_number = int(data.get("w", 0))
    except ValueError:
        await cb.message.edit_text("❌ Некорректные данные")
        return
    
    # Получаем информацию о неделе
    week_info = weeks.get_week(week_number)
    if not week_info:
        await cb.message.edit_text("❌ Неделя не найдена")
        return
    
    # Получаем пользователя и назначенного TA
    user = users.get_by_tg(actor_tg_id)
    student_code = user.get("id") or user.get("student_code") if user else None
    
    ta_code = None
    if student_code:
        ta_code = assignments.get_assignment_for_student_code(str(student_code), week_number)
    
    # Агрегированный статус недели
    # TODO: полный расчет с передачей всех сервисов
    status_emoji = "🔵"
    status_text = "Нет записи"
    
    # Создаем меню действий
    kb = InlineKeyboardBuilder()
    
    # 1. Описание и дедлайн
    kb.button(
        text="ℹ️ Описание и дедлайн",
        callback_data=build_callback("week_info", w=week_number)
    )
    
    # 2. Получить задачи и вопросы
    kb.button(
        text="📝 Получить задачи и вопросы", 
        callback_data=build_callback("week_tasks_download", w=week_number)
    )
    
    # 3. Загрузить решение
    kb.button(
        text="📤 Загрузить решение",
        callback_data=build_callback("week_solution_upload_wait", w=week_number)
    )
    
    # 4. Записаться на сдачу (только если есть TA)
    if ta_code:
        kb.button(
            text="⏰ Записаться на сдачу",
            callback_data=build_callback("week_signup_pick_teacher", w=week_number, ta=ta_code)
        )
        
        # 5. Отменить запись (если есть активная)
        kb.button(
            text="❌ Отменить запись на сдачу", 
            callback_data=build_callback("week_unsign_list", w=week_number)
        )
    
    # 6. Узнать оценку
    kb.button(
        text="✅ Узнать оценку",
        callback_data=build_callback("week_grade_view", w=week_number)
    )
    
    # Кнопка назад
    kb.button(
        text="⬅️ Назад",
        callback_data=build_callback("wic_main")
    )
    
    kb.adjust(1)
    
    # Формируем заголовок
    deadline_str = week_info.get("deadline_str", "Не указан")
    is_overdue = week_info.get("is_overdue", False)
    deadline_emoji = "🔴" if is_overdue else "🟢"
    
    text = f"<b>W{week_number:02d} — {week_info['title']}</b>\n\n" \
           f"📊 <b>Статус:</b> {status_emoji} {status_text}\n" \
           f"📅 <b>Дедлайн:</b> {deadline_str} {deadline_emoji}\n\n" \
           f"Выберите действие:"
    
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

# ================================================================================================
# ДЕЙСТВИЯ ДЛЯ НЕДЕЛИ
# ================================================================================================

@router.callback_query(F.data.regexp(r"r=s;a=week_info;w=\d+"))
async def week_info_handler(
    cb: CallbackQuery,
    weeks: WeeksService,
    assignments: AssignmentsService,
    users: UsersService,
    actor_tg_id: int
):
    """Показать описание и дедлайн недели с информацией о TA"""
    await cb.answer()
    
    data = parse_callback(cb.data)
    try:
        week_number = int(data.get("w", 0))
    except ValueError:
        await cb.message.edit_text("❌ Некорректные данные")
        return
    
    week_info = weeks.get_week(week_number)
    if not week_info:
        await cb.message.edit_text("❌ Неделя не найдена")
        return
    
    # Получаем информацию о назначенном TA
    user = users.get_by_tg(actor_tg_id)
    student_code = user.get("id") or user.get("student_code") if user else None
    
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
    
    status_emoji = "🔴" if week_info.get("is_overdue", False) else "🟢"
    
    text = f"ℹ️ <b>W{week_number:02d}: {week_info['title']}</b>\n\n" \
           f"📝 <b>Описание:</b>\n{week_info['description']}\n\n" \
           f"📅 <b>Дедлайн:</b> {week_info['deadline_str']} {status_emoji}\n\n" \
           f"👨‍🏫 <b>Принимает:</b> {ta_info}"
    
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data=build_callback("week_menu", w=week_number))
    
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.regexp(r"r=s;a=week_tasks_download;w=\d+"))
async def week_tasks_download_handler(cb: CallbackQuery):
    """Получить задачи и вопросы - заглушка"""
    await cb.answer()
    
    data = parse_callback(cb.data)
    week_number = data.get("w", "?")
    
    text = f"📝 <b>Задачи и вопросы для W{week_number}</b>\n\n" \
           f"🚧 Функция в разработке\n\n" \
           f"Пока вы можете найти задания на сайте курса:\n" \
           f"📖 <a href='https://example.com/course'>Программа курса</a>"
    
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data=build_callback("week_menu", w=week_number))
    
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.regexp(r"r=s;a=week_solution_upload_wait;w=\d+"))
async def week_solution_upload_start(
    cb: CallbackQuery, 
    state: FSMContext
):
    """Начать загрузку решения - интеграция с существующим /submit"""
    await cb.answer()
    
    data = parse_callback(cb.data)
    week_number = data.get("w", "?")
    
    # TODO: интеграция с существующей логикой /submit
    text = f"📤 <b>Загрузка решения для W{week_number}</b>\n\n" \
           f"🚧 Функция в разработке\n\n" \
           f"Пока используйте команду /submit для отправки решений."
    
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data=build_callback("week_menu", w=week_number))
    
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.regexp(r"r=s;a=week_grade_view;w=\d+"))
async def week_grade_view_handler(cb: CallbackQuery):
    """Показать оценку за неделю - интеграция с /grades"""
    await cb.answer()
    
    data = parse_callback(cb.data)
    week_number = data.get("w", "?")
    
    # TODO: интеграция с существующей логикой grades
    text = f"🎯 <b>Оценка за W{week_number}</b>\n\n" \
           f"🚧 Функция в разработке\n\n" \
           f"Пока используйте команду /grades для просмотра всех оценок."
    
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data=build_callback("week_menu", w=week_number))
    
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

# ================================================================================================
# ЗАПИСЬ НА СДАЧУ (интеграция с booking system)
# ================================================================================================

@router.callback_query(F.data.regexp(r"r=s;a=week_signup_pick_teacher;w=\d+;ta=.+"))
async def week_signup_pick_teacher_handler(cb: CallbackQuery):
    """Записаться на сдачу - перенаправление к слотам TA"""
    await cb.answer()
    
    data = parse_callback(cb.data)
    week_number = data.get("w", "?")
    ta_code = data.get("ta", "?")
    
    # TODO: интеграция с существующей booking системой
    text = f"⏰ <b>Запись на сдачу W{week_number}</b>\n\n" \
           f"👨‍🏫 <b>Преподаватель:</b> {ta_code}\n\n" \
           f"🚧 Функция записи в разработке\n\n" \
           f"Пока обратитесь к преподавателю напрямую или используйте /slots"
    
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data=build_callback("week_menu", w=week_number))
    
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.regexp(r"r=s;a=week_unsign_list;w=\d+"))
async def week_unsign_list_handler(cb: CallbackQuery):
    """Отменить запись на сдачу - показать список активных записей"""
    await cb.answer()
    
    data = parse_callback(cb.data)
    week_number = data.get("w", "?")
    
    # TODO: найти активные записи студента на эту неделю
    text = f"❌ <b>Отмена записи на W{week_number}</b>\n\n" \
           f"🚧 Функция в разработке\n\n" \
           f"Пока используйте /slots для управления записями."
    
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data=build_callback("week_menu", w=week_number))
    
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

# ================================================================================================
# МОИ ЗАПИСИ НА СДАЧУ (замена проблемного /slots)
# ================================================================================================

@router.callback_query(F.data == build_callback("my_bookings_list"))
async def my_bookings_list_handler(cb: CallbackQuery):
    """Мои записи на сдачу - список будущих/текущих записей"""
    await cb.answer()
    
    # TODO: реализация списка записей студента
    text = f"📅 <b>Мои записи на сдачу</b>\n\n" \
           f"🚧 Функция в разработке\n\n" \
           f"Здесь будет список ваших активных записей на сдачи с возможностью отмены и перезаписи."
    
    kb = InlineKeyboardBuilder()
    kb.button(
        text="⬅️ Назад в главное меню",
        callback_data=build_callback("back_to_main")
    )
    
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

# ================================================================================================
# МОИ ОЦЕНКИ (интеграция с существующим /grades)
# ================================================================================================

@router.callback_query(F.data == build_callback("my_grades_list"))
async def my_grades_list_handler(cb: CallbackQuery):
    """Мои оценки - интеграция с существующим /grades"""
    await cb.answer()
    
    # TODO: интеграция с существующей логикой /grades
    text = f"📊 <b>Мои оценки</b>\n\n" \
           f"🚧 Функция в разработке\n\n" \
           f"Пока используйте команду /grades для просмотра оценок."
    
    kb = InlineKeyboardBuilder()
    kb.button(
        text="⬅️ Назад в главное меню",
        callback_data=build_callback("back_to_main")
    )
    
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

# ================================================================================================  
# ИСТОРИЯ СДАЧ (заглушка)
# ================================================================================================

@router.callback_query(F.data == build_callback("history_weeks_list"))
async def history_weeks_list_handler(cb: CallbackQuery):
    """История сдач - заглушка"""
    await cb.answer()
    
    text = f"📜 <b>История сдач</b>\n\n" \
           f"🚧 Функция в разработке\n\n" \
           f"Здесь будет история всех ваших прошедших сдач с деталями по каждой неделе."
    
    kb = InlineKeyboardBuilder()
    kb.button(
        text="⬅️ Назад в главное меню", 
        callback_data=build_callback("back_to_main")
    )
    
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

# ================================================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ И НАВИГАЦИЯ
# ================================================================================================

@router.callback_query(F.data == build_callback("back_to_main"))
async def back_to_main_handler(
    cb: CallbackQuery,
    actor_tg_id: int, 
    users: UsersService
):
    """Возврат в главное меню студента"""
    await cb.answer()
    
    # Проверяем роль
    user = users.get_by_tg(actor_tg_id)
    if not user or user.get("role") != "student":
        await cb.message.edit_text("❌ Ошибка доступа")
        return
    
    # Воссоздаем главное меню
    kb = InlineKeyboardBuilder()
    
    kb.button(
        text="📘 WIC — Работа с неделями",
        callback_data=build_callback("wic_main")
    )
    
    kb.button(
        text="📅 Мои записи на сдачу",
        callback_data=build_callback("my_bookings_list")
    )
    
    kb.button(
        text="📊 Мои оценки", 
        callback_data=build_callback("my_grades_list")
    )
    
    kb.button(
        text="📜 История сдач",
        callback_data=build_callback("history_weeks_list")
    )
    
    kb.adjust(1)
    
    student_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
    if not student_name:
        student_name = "Студент"
    
    text = f"👋 <b>Добро пожаловать, {student_name}!</b>\n\n" \
           f"📚 Выберите нужный раздел:"
    
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

def build_back_to_main_menu() -> str:
    """Построить кнопку возврата в главное меню"""
    return "⬅️ /student - Вернуться в главное меню"

# ================================================================================================
# TODO: ДОРАБОТКА ФУНКЦИЙ
# ================================================================================================

"""
TODO для полной реализации:

1. АГРЕГИРОВАННЫЕ СТАТУСЫ:
   - Доработать get_week_aggregated_status() с передачей всех нужных сервисов
   - Реализовать полную логику приоритетов статусов
   - Добавить кэширование статусов для производительности

2. ИНТЕГРАЦИЯ С СУЩЕСТВУЮЩИМИ ФУНКЦИЯМИ:
   - week_solution_upload_wait: интеграция с логикой /submit
   - my_grades_list: интеграция с /grades  
   - week_signup_pick_teacher: интеграция с booking system
   - Анти-дублирование записей

3. ЗАПИСЬ НА СЛОТЫ:
   - week_signup_pick_teacher -> week_signup_slot_list -> week_signup_confirm
   - week_unsign_list -> week_unsign_confirm
   - Проверка конфликтов и ограничений

4. ДЕТАЛЬНЫЕ ЭКРАНЫ:
   - my_bookings_list с фильтрацией и пагинацией
   - booking_cancel_confirm | booking_resign_pick_slot | booking_info
   - my_grades_week_details с комментариями
   - history_week_details с полной информацией

5. FSM STATES:
   - Реализация всех состояний для загрузки файлов
   - Состояния для перезаписи на слоты
   - Валидация переходов между состояниями

6. ПОДТВЕРЖДЕНИЯ И СООБЩЕНИЯ:
   - "✅ Запись создана: {дата} {время}, преп. {ФИО}"  
   - "🗑️ Запись отменена"
   - "🔄 Перезапись выполнена: {новая дата/время}"
   - "📤 Файл загружен"
   - Анти-дублирование: "ℹ️ На эту неделю у вас уже есть запись. Хотите перезаписаться?"

7. ЛОГИРОВАНИЕ:
   - STUDENT_SIGNUP {student_id} {week} {slot_id}
   - STUDENT_UNSIGN {student_id} {week} {slot_id}  
   - STUDENT_UPLOAD {student_id} {week} {file_id}
   - STUDENT_VIEW_GRADE {student_id} {week}

8. РЕФАКТОРИНГ ГОТОВНОСТИ:
   - Разбить на модули: wic_handler.py, bookings_handler.py, grades_handler.py
   - Вынести статусы в отдельный сервис
   - Создать базовые классы для callback handling
"""