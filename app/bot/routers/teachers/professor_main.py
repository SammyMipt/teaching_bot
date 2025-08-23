"""
Главный роутер для преподавателей с исправленным UX согласно спецификации.
Исправления:
1. Единое управление расписанием вместо отдельных кнопок
2. Исправлена кнопка "Студенты" в карточке слота
"""

from __future__ import annotations
import logging
from datetime import datetime, timezone, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
import copy

# Services
from app.services.users_service import UsersService
from app.services.slot_service import SlotService
from app.services.booking_service import BookingService
from app.services.ta_prefs_service import TaPrefsService
from app.services.weeks_service import WeeksService
from app.services.grade_service import GradeService
from app.services.submission_service import SubmissionService
from app.services.audit_service import AuditService

router = Router(name="professors_main")
log = logging.getLogger(__name__)

# ================================================================================================
# FSM STATES
# ================================================================================================

class ProfessorFSM(StatesGroup):
    """FSM состояния для преподавателей"""
    sched_create_dates = State()
    sched_create_time = State() 
    sched_create_len = State()
    sched_create_cap = State()
    sched_create_confirm = State()
    material_upload_wait_file = State()

# ================================================================================================
# CALLBACK DATA HELPERS
# ================================================================================================

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
        log.error(f"Error parsing callback data: {callback_data}, error: {e}")
    return result

def get_slot_display_status(slot_dict: dict, current_bookings: int) -> dict:
    """Определение статуса слота для отображения"""
    capacity = int(slot_dict.get("capacity", 1))
    is_open = slot_dict.get("is_open", True)
    
    # Проверяем, прошёл ли слот
    try:
        slot_date = slot_dict.get("date")
        slot_time = slot_dict.get("time_to", slot_dict.get("time_from"))
        if slot_date and slot_time:
            slot_dt = datetime.fromisoformat(f"{slot_date}T{slot_time}:00+03:00")
            now = datetime.now(timezone(timedelta(hours=3)))
            if slot_dt < now:
                return {"emoji": "⚫", "status": "pasted", "text": "Прошёл"}
    except:
        pass
    
    if not is_open:
        return {"emoji": "⚪", "status": "closed", "text": "Закрыт"}
    elif current_bookings >= capacity:
        return {"emoji": "🔴", "status": "full", "text": "Занят"}
    elif current_bookings > 0:
        return {"emoji": "🟡", "status": "partial", "text": "Частично свободен"}
    else:
        return {"emoji": "🟢", "status": "free", "text": "Свободен"}

# ================================================================================================
# ГЛАВНОЕ МЕНЮ
# ================================================================================================

@router.message(F.text == "/professor") 
async def professor_main_menu(
    message: Message,
    actor_tg_id: int,
    users: UsersService
):
    """Главное меню преподавателя"""
    user = users.get_by_tg(actor_tg_id)
    if not user or user.get("role") not in ("ta", "owner"):
        await message.answer(
            "❌ Команда доступна только зарегистрированным преподавателям.\n"
            "Пройдите регистрацию: /register_ta"
        )
        return
    
    kb = InlineKeyboardBuilder()
    # ИСПРАВЛЕНИЕ 1: Единое управление расписанием согласно спецификации
    kb.button(text="➕ Создать расписание", callback_data="r=t;a=sched_create_start")
    kb.button(text="📅 Управление расписанием", callback_data="r=t;a=sched_manage_main")
    kb.button(text="📚 Методические материалы", callback_data="r=t;a=materials_main")
    kb.button(text="👨‍🎓 Сдачи студентов", callback_data="r=t;a=submissions_main")
    kb.adjust(1)
    
    teacher_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
    if not teacher_name:
        teacher_name = "Преподаватель"
    
    text = f"👨‍🏫 <b>Добро пожаловать, {teacher_name}!</b>\n\n📚 Выберите нужный раздел:"
    await message.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "r=t;a=back_to_main")
async def back_to_main_handler(cb: CallbackQuery, actor_tg_id: int, users: UsersService):
    """Возврат в главное меню"""
    await cb.answer()
    
    user = users.get_by_tg(actor_tg_id)
    if not user or user.get("role") not in ("ta", "owner"):
        await cb.message.edit_text("❌ Ошибка доступа")
        return
    
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Создать расписание", callback_data="r=t;a=sched_create_start")
    kb.button(text="📅 Управление расписанием", callback_data="r=t;a=sched_manage_main")
    kb.button(text="📚 Методические материалы", callback_data="r=t;a=materials_main")
    kb.button(text="👨‍🎓 Сдачи студентов", callback_data="r=t;a=submissions_main")
    kb.adjust(1)
    
    teacher_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
    if not teacher_name:
        teacher_name = "Преподаватель"
    
    text = f"👨‍🏫 <b>Добро пожаловать, {teacher_name}!</b>\n\n📚 Выберите нужный раздел:"
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

# ================================================================================================
# ➕ СОЗДАНИЕ РАСПИСАНИЯ
# ================================================================================================

@router.callback_query(F.data == "r=t;a=sched_create_start")
async def sched_create_start_handler(cb: CallbackQuery, state: FSMContext):
    """Создание расписания - начало мастера"""
    await cb.answer()
    
    kb = InlineKeyboardBuilder()
    kb.button(text="📅 Выбрать даты", callback_data="r=t;a=sched_pick_dates")
    kb.button(text="⬅️ Назад", callback_data="r=t;a=back_to_main")
    kb.adjust(1)
    
    text = (
        "➕ <b>Создание расписания</b>\n\n"
        "Мастер создания слотов поможет вам быстро создать расписание.\n\n"
        "Вы сможете указать:\n"
        "• Дату или диапазон дат\n"
        "• Время начала и конца приёма\n"
        "• Длительность одного слота\n"
        "• Количество студентов на слот\n\n"
        "Нажмите «Выбрать даты» для начала"
    )
    
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

# ================================================================================================
# 📅 УПРАВЛЕНИЕ РАСПИСАНИЕМ
# ================================================================================================

@router.callback_query(F.data == "r=t;a=sched_manage_main")
async def sched_manage_main_handler(
    cb: CallbackQuery,
    actor_tg_id: int,
    users: UsersService,
    slots: SlotService
):
    """Управление расписанием - выбор даты"""
    await cb.answer()
    
    ta_id = users.get_ta_id_by_tg(actor_tg_id)
    if not ta_id:
        await cb.message.edit_text("❌ Не удалось определить ваш TA ID")
        return
    
    try:
        slots_df = slots.table.read()
        if slots_df.empty:
            text = "📅 <b>Управление расписанием</b>\n\n❌ У вас пока нет созданных слотов.\nИспользуйте «Создать расписание» для добавления."
            kb = InlineKeyboardBuilder()
            kb.button(text="➕ Создать расписание", callback_data="r=t;a=sched_create_start")
            kb.button(text="⬅️ Назад", callback_data="r=t;a=back_to_main")
            kb.adjust(1)
            await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
            return
        
        teacher_slots = slots_df[slots_df["ta_id"] == ta_id]
        if teacher_slots.empty:
            text = "📅 <b>Управление расписанием</b>\n\n❌ У вас пока нет созданных слотов.\nИспользуйте «Создать расписание» для добавления."
            kb = InlineKeyboardBuilder()
            kb.button(text="➕ Создать расписание", callback_data="r=t;a=sched_create_start")
            kb.button(text="⬅️ Назад", callback_data="r=t;a=back_to_main")
            kb.adjust(1)
            await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
            return
        
        # Группируем по датам
        unique_dates = teacher_slots["date"].unique()
        unique_dates = sorted(unique_dates)
        
        kb = InlineKeyboardBuilder()
        for date_str in unique_dates[:10]:  # Показываем первые 10 дат
            try:
                date_obj = datetime.fromisoformat(date_str).date()
                formatted_date = date_obj.strftime("%d.%m.%Y")
                date_slots = teacher_slots[teacher_slots["date"] == date_str]
                slots_count = len(date_slots)
                
                kb.button(
                    text=f"📅 {formatted_date} ({slots_count} слотов)",
                    callback_data=f"r=t;a=slot_list;d={date_str.replace('-', '')}"
                )
            except Exception as e:
                log.error(f"Error processing date {date_str}: {e}")
        
        kb.button(text="⬅️ Назад", callback_data="r=t;a=back_to_main")
        kb.adjust(1)
        
        text = "📅 <b>Управление расписанием</b>\n\nВыберите дату для просмотра и управления слотами:"
        await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
        
    except Exception as e:
        log.error(f"Error in sched_manage_main: {e}")
        await cb.message.edit_text(f"❌ Ошибка при загрузке расписания: {str(e)}")

# ================================================================================================
# СПИСОК СЛОТОВ И КАРТОЧКА СЛОТА
# ================================================================================================

@router.callback_query(F.data.regexp(r"r=t;a=slot_list;d=\d{8}"))
async def slot_list_handler(
    cb: CallbackQuery,
    actor_tg_id: int,
    users: UsersService,
    slots: SlotService,
    bookings: BookingService
):
    """Список слотов на дату"""
    await cb.answer()
    
    # Парсим дату
    try:
        data = parse_callback(cb.data)
        date_str = data.get("d", "")
        
        if not date_str:
            await cb.message.edit_text("❌ Некорректные данные")
            return
    except Exception:
        await cb.message.edit_text("❌ Ошибка обработки данных")
        return
    
    # Преобразуем дату
    try:
        date_obj = datetime.strptime(date_str, "%Y%m%d").date()
        formatted_date = date_obj.strftime("%d.%m.%Y")
        iso_date = date_obj.isoformat()
    except ValueError:
        await cb.message.edit_text("❌ Некорректная дата")
        return
    
    ta_id = users.get_ta_id_by_tg(actor_tg_id)
    if not ta_id:
        await cb.message.edit_text("❌ Не удалось определить ваш TA ID")
        return
    
    try:
        slots_df = slots.table.read()
        if slots_df.empty:
            await cb.message.edit_text("❌ Слоты не найдены")
            return
        
        date_slots = slots_df[
            (slots_df["ta_id"] == ta_id) & 
            (slots_df["date"] == iso_date)
        ]
        
        if date_slots.empty:
            await cb.message.edit_text(f"📅 Нет слотов на {formatted_date}")
            return
        
        kb = InlineKeyboardBuilder()
        date_slots = date_slots.sort_values("time_from")
        
        for _, slot_row in date_slots.iterrows():
            slot_id = slot_row["slot_id"]
            time_from = slot_row["time_from"]
            time_to = slot_row["time_to"]
            capacity = int(slot_row.get("capacity", 1))
            
            # Считаем записи
            try:
                bookings_df = bookings.table.read()
                if not bookings_df.empty:
                    slot_bookings = bookings_df[bookings_df["slot_id"] == slot_id]
                    active_bookings = slot_bookings[
                        slot_bookings["status"].str.lower().isin(["active", "confirmed"])
                    ] if "status" in slot_bookings.columns else slot_bookings
                    current_bookings = len(active_bookings)
                else:
                    current_bookings = 0
            except Exception:
                current_bookings = 0
            
            slot_dict = slot_row.to_dict()
            status_info = get_slot_display_status(slot_dict, current_bookings)
            
            button_text = f"{status_info['emoji']} {time_from}–{time_to} | {current_bookings}/{capacity}"
            
            kb.button(
                text=button_text,
                callback_data=f"r=t;a=slot_card;s={slot_id}"
            )
        
        kb.button(text="⬅️ Назад", callback_data="r=t;a=sched_manage_main")
        kb.adjust(1)
        
        text = f"📅 <b>Слоты на {formatted_date}</b>\n\nВыберите слот для просмотра деталей:"
        await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
        
    except Exception as e:
        log.error(f"Error in slot_list: {e}")
        await cb.message.edit_text(f"❌ Ошибка: {str(e)}")

@router.callback_query(F.data.startswith("r=t;a=slot_card;s="))
async def slot_card_handler(
    cb: CallbackQuery,
    slots: SlotService,
    bookings: BookingService
):
    """Карточка слота с действиями"""
    await cb.answer()
    
    try:
        data = parse_callback(cb.data)
        slot_id = data.get("s", "")
        
        if not slot_id:
            await cb.message.edit_text("❌ Некорректные данные")
            return
        
        found, slot_dict = slots.get_slot_by_id(slot_id)
        if not found:
            await cb.message.edit_text("❌ Слот не найден")
            return
        
        # Считаем записи
        current_bookings = 0
        try:
            bookings_df = bookings.table.read()
            if not bookings_df.empty:
                slot_bookings = bookings_df[bookings_df["slot_id"] == slot_id]
                active_bookings = slot_bookings[
                    slot_bookings["status"].str.lower().isin(["active", "confirmed"])
                ] if "status" in slot_bookings.columns else slot_bookings
                current_bookings = len(active_bookings)
        except Exception:
            pass
        
        # Формируем информацию о слоте
        date = slot_dict.get("date", "")
        time_from = slot_dict.get("time_from", "")
        time_to = slot_dict.get("time_to", "")
        capacity = int(slot_dict.get("capacity", 1))
        location = slot_dict.get("location", "онлайн")
        
        status_info = get_slot_display_status(slot_dict, current_bookings)
        
        text = (
            f"<b>Карточка слота</b>\n\n"
            f"⏰ {time_from}–{time_to} | {date}\n"
            f"👥 {current_bookings}/{capacity} | Статус: {status_info['emoji']} {status_info['text']}\n"
            f"📍 {location}\n"
        )
        
        # Кнопки действий
        kb = InlineKeyboardBuilder()
        kb.button(text="👨‍🎓 Студенты", callback_data=f"r=t;a=slot_students;s={slot_id}")
        kb.button(text="✏️ Изменить", callback_data=f"r=t;a=slot_edit;s={slot_id}")
        
        if status_info["status"] == "closed":
            kb.button(text="🟢 Открыть", callback_data=f"r=t;a=slot_open;s={slot_id}")
        else:
            kb.button(text="🚫 Закрыть", callback_data=f"r=t;a=slot_close;s={slot_id}")
        
        kb.button(text="❌ Удалить", callback_data=f"r=t;a=slot_delete;s={slot_id}")
        kb.button(text="⬅️ Назад", callback_data=f"r=t;a=slot_list;d={date.replace('-', '')}")
        
        kb.adjust(2, 2, 1, 1)
        
        await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
        
    except Exception as e:
        log.error(f"Error in slot_card: {e}")
        await cb.message.edit_text(f"❌ Ошибка: {str(e)}")

# ================================================================================================
# ИСПРАВЛЕНИЕ 2: Кнопка "Студенты" - полноценное отображение списка
# ================================================================================================

@router.callback_query(F.data.startswith("r=t;a=slot_students;s="))
async def slot_students_handler(
    cb: CallbackQuery,
    bookings: BookingService,
    users: UsersService
):
    """Список записанных студентов - ИСПРАВЛЕНО"""
    await cb.answer()
    
    # Извлекаем slot_id
    try:
        data = parse_callback(cb.data)
        slot_id = data.get("s", "")
        
        log.info(f"slot_students_handler: callback_data={cb.data}, slot_id={slot_id}")
        
        if not slot_id:
            log.error(f"slot_students_handler: slot_id not found in callback_data={cb.data}")
            await cb.message.edit_text("❌ Не удалось определить ID слота")
            return
            
    except Exception as e:
        log.error(f"Error parsing slot_students callback: {cb.data}, error: {e}")
        await cb.message.edit_text("❌ Ошибка обработки данных")
        return
    
    try:
        bookings_df = bookings.table.read()
        
        if bookings_df.empty:
            text = "👨‍🎓 <b>Записанные студенты</b>\n\n📭 На этот слот никто не записан."
        else:
            slot_bookings = bookings_df[bookings_df["slot_id"] == slot_id]
            
            active_bookings = slot_bookings[
                slot_bookings["status"].str.lower().isin(["active", "confirmed"])
            ] if "status" in slot_bookings.columns else slot_bookings
            
            if active_bookings.empty:
                text = "👨‍🎓 <b>Записанные студенты</b>\n\n📭 На этот слот никто не записан."
            else:
                lines = ["👨‍🎓 <b>Записанные студенты:</b>\n"]
                
                for i, (_, booking_row) in enumerate(active_bookings.iterrows(), 1):
                    tg_id = booking_row.get("student_tg_id")
                    if tg_id:
                        try:
                            student_user = users.get_by_tg(int(tg_id))
                            if student_user:
                                first_name = student_user.get('first_name', '')
                                last_name = student_user.get('last_name', '')
                                student_name = f"{first_name} {last_name}".strip()
                                if not student_name:
                                    student_name = f"ID: {student_user.get('id', tg_id)}"
                            else:
                                student_name = f"TG: {tg_id}"
                            
                            # Добавляем информацию о времени записи
                            created_at = booking_row.get("created_at", "")
                            if created_at:
                                try:
                                    dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                                    date_str = dt.strftime("%d.%m %H:%M")
                                    lines.append(f"{i}. <b>{student_name}</b>\n   📝 Записался: {date_str}")
                                except:
                                    lines.append(f"{i}. <b>{student_name}</b>")
                            else:
                                lines.append(f"{i}. <b>{student_name}</b>")
                        except Exception as e:
                            log.error(f"Error processing student {tg_id}: {e}")
                            lines.append(f"{i}. ID: {tg_id}")
                
                text = "\n".join(lines)
        
        # Кнопка назад
        kb = InlineKeyboardBuilder()
        kb.button(text="⬅️ Назад к слоту", callback_data=f"r=t;a=slot_card;s={slot_id}")
        
        await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
        
    except Exception as e:
        log.error(f"Error listing students for slot {slot_id}: {e}", exc_info=True)
        await cb.message.edit_text("❌ Ошибка при получении списка студентов.")

# ================================================================================================
# 📚 МЕТОДИЧЕСКИЕ МАТЕРИАЛЫ
# ================================================================================================

@router.callback_query(F.data == "r=t;a=materials_main")
async def materials_main_handler(cb: CallbackQuery):
    """Главное меню методических материалов"""
    await cb.answer()
    
    kb = InlineKeyboardBuilder()
    kb.button(text="📖 Просмотреть список тем курса", callback_data="r=t;a=syllabus_view")
    kb.button(text="📤 Загрузить материалы по неделе", callback_data="r=t;a=material_upload_pick_week")
    kb.button(text="⬅️ Назад", callback_data="r=t;a=back_to_main")
    kb.adjust(1)
    
    text = "📚 <b>Методические материалы</b>\n\nВыберите действие:"
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "r=t;a=syllabus_view")
async def syllabus_view_handler(cb: CallbackQuery, weeks: WeeksService):
    """Просмотр тем курса"""
    await cb.answer()
    
    try:
        weeks_df = weeks.list_all_weeks()
        if weeks_df.empty:
            text = "📖 <b>Темы курса</b>\n\n❌ Темы не загружены"
        else:
            lines = ["📖 <b>Все темы курса:</b>\n"]
            for _, row in weeks_df.iterrows():
                status = row["status_emoji"]
                deadline_str = row["deadline_date"].strftime('%d.%m.%Y')
                lines.append(f"<b>{row['week']}. {row['title']}</b>")
                lines.append(f"   {status} Дедлайн: {deadline_str}\n")
            text = "\n".join(lines)
        
        kb = InlineKeyboardBuilder()
        kb.button(text="⬅️ Назад", callback_data="r=t;a=materials_main")
        
        await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    except Exception as e:
        log.error(f"Error in syllabus_view: {e}")
        await cb.message.edit_text("❌ Ошибка при загрузке тем курса")

# ================================================================================================
# 👨‍🎓 СДАЧИ СТУДЕНТОВ
# ================================================================================================

@router.callback_query(F.data == "r=t;a=submissions_main")
async def submissions_main_handler(cb: CallbackQuery):
    """Главное меню сдач студентов"""
    await cb.answer()
    
    kb = InlineKeyboardBuilder()
    kb.button(text="📆 Актуальные сдачи", callback_data="r=t;a=sub_act_dates")
    kb.button(text="📜 Прошедшие сдачи", callback_data="r=t;a=sub_past_pick_mode")
    kb.button(text="⬅️ Назад", callback_data="r=t;a=back_to_main")
    kb.adjust(1)
    
    text = "👨‍🎓 <b>Сдачи студентов</b>\n\n🚧 Функции частично в разработке\n\nВыберите действие:"
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "r=t;a=sub_act_dates")
async def sub_act_dates_handler(cb: CallbackQuery):
    """Актуальные сдачи"""
    await cb.answer()
    
    text = "📆 <b>Актуальные сдачи</b>\n\n🚧 Функция в разработке\n\nЗдесь будут сдачи на сегодня и ближайшие дни с возможностью:\n• 📂 Скачать работу\n• ✅ Поставить оценку"
    
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data="r=t;a=submissions_main")
    
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "r=t;a=sub_past_pick_mode")
async def sub_past_pick_mode_handler(cb: CallbackQuery):
    """Прошедшие сдачи - режимы поиска"""
    await cb.answer()
    
    kb = InlineKeyboardBuilder()
    kb.button(text="🔎 По слотам", callback_data="r=t;a=sub_past_by_slot")
    kb.button(text="📖 По неделям", callback_data="r=t;a=sub_past_by_week")
    kb.button(text="👥 По группе", callback_data="r=t;a=sub_past_by_group")
    kb.button(text="🧑‍🎓 По студенту", callback_data="r=t;a=sub_past_by_student")
    kb.button(text="⬅️ Назад", callback_data="r=t;a=submissions_main")
    
    kb.adjust(2, 2, 1)
    
    text = "📜 <b>Прошедшие сдачи</b>\n\nВыберите способ поиска:"
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "r=t;a=sub_past_by_slot")
@router.callback_query(F.data == "r=t;a=sub_past_by_week")
@router.callback_query(F.data == "r=t;a=sub_past_by_group")  
@router.callback_query(F.data == "r=t;a=sub_past_by_student")
async def sub_past_by_handler(cb: CallbackQuery):
    """Режимы поиска прошедших сдач"""
    await cb.answer()
    
    data = parse_callback(cb.data)
    action = data.get("a", "")
    
    mode_names = {
        "sub_past_by_slot": "🔎 По слотам",
        "sub_past_by_week": "📖 По неделям",
        "sub_past_by_group": "👥 По группе", 
        "sub_past_by_student": "🧑‍🎓 По студенту"
    }
    
    mode_name = mode_names.get(action, "Неизвестный режим")
    
    text = f"<b>{mode_name}</b>\n\n🚧 Функция в разработке\n\nЗдесь будет поиск прошедших сдач с возможностью:\n• 📂 Скачать работу\n• ✅ Поставить/изменить оценку"
    
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data="r=t;a=sub_past_pick_mode")
    
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

# ================================================================================================
# TODO: ДОРАБОТКА ФУНКЦИЙ
# ================================================================================================

"""
TODO для полной реализации:

1. ИНТЕГРАЦИЯ С СУЩЕСТВУЮЩИМИ ФУНКЦИЯМИ:
   - sched_create_start: интеграция с /schedule мастером
   - slot_action_handler: интеграция с /myslots_manage логикой
   - Все FSM состояния для создания расписания

2. СИСТЕМА СТАТУСОВ И ФИЛЬТРОВ:
   - Фильтры слотов по статусам: 🟢, 🟡, 🔴, ⚪, ⚫ + «Сброс»
   - Пагинация: ‹, › + «Стр. X/Y» для больших списков
   - Кэширование статусов слотов

3. ВЫСТАВЛЕНИЕ ОЦЕНОК:
   - Экраны sub_action_download и sub_action_grade
   - Кнопки: 5, 4, 3, 2, 1, Отмена
   - Toast: "✅ Оценка 5 для Иванов И.И. сохранена"

4. ЗАГРУЗКА МАТЕРИАЛОВ:
   - material_upload_pick_week с реальными неделями
   - material_upload_wait_file FSM состояние
   - "✅ Материалы для Wxx загружены"

5. ДЕТАЛЬНЫЕ ЭКРАНЫ СДАЧ:
   - sub_act_slots -> sub_act_students -> sub_action_[download|grade]
   - Полная навигация по режимам поиска
   - Интеграция с submission и grade сервисами

6. ЛОГИРОВАНИЕ:
   - TEACHER_SCHED_CREATE {teacher_id} {from_date} {to_date} {len} {cap} -> {n_slots}
   - TEACHER_SLOT_ACTION {teacher_id} {slot_id} {action}  
   - TEACHER_MATERIAL_UPLOAD {teacher_id} {week} {file_id}
   - TEACHER_GRADE_SET {teacher_id} {student_id} {week|slot_id} {grade}

7. РЕФАКТОРИНГ ГОТОВНОСТИ:
   - schedule_handler.py (создание и управление расписанием)
   - slots_handler.py (просмотр и действия со слотами)
   - submissions_handler.py (работа со сдачами)
   - materials_handler.py (методические материалы)

ИСПРАВЛЕНИЯ ВНЕСЕНЫ:
✅ 1. Просмотр списка тем курса - теперь работает как /weeks_list
✅ 2. Кнопка назад из методических материалов - исправлена  
✅ 3. Сдачи студентов - все обработчики добавлены
✅ 4. Кнопка назад из расписания - исправлена
✅ 5. Кнопка студенты в слоте - исправлена парсинг callback_data

Все обработчики используют точные строки формата "r=t;a=action;..."
"""