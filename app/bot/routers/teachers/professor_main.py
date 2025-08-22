"""
Главный роутер для преподавателей с новым UX согласно спецификации.
Реализует главное меню и интеграцию с существующими функциями.
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
        log.error(f"Error parsing callback: {callback_data}, error: {e}")
    return result

# ================================================================================================
# СТАТУСЫ СЛОТОВ
# ================================================================================================

def get_slot_display_status(slot_dict: dict, current_bookings: int) -> dict:
    """Получить статус слота для отображения"""
    now = datetime.now(timezone.utc)
    
    try:
        slot_date = datetime.fromisoformat(slot_dict.get("date", "")).date()
        time_to = slot_dict.get("time_to", "23:59")
        slot_datetime = datetime.combine(slot_date, datetime.strptime(time_to, "%H:%M").time())
        slot_datetime = slot_datetime.replace(tzinfo=timezone.utc)
    except Exception:
        slot_datetime = now
    
    slot_status = slot_dict.get("status", "free").lower()
    capacity = int(slot_dict.get("capacity", 1))
    
    if slot_datetime < now:
        return {"emoji": "⚫", "text": "Прошёл", "status": "past"}
    elif slot_status in ["canceled", "closed"]:
        return {"emoji": "⚪", "text": "Закрыт", "status": "closed"}
    elif current_bookings >= capacity:
        return {"emoji": "🔴", "text": "Занят", "status": "busy"}
    elif current_bookings > 0:
        return {"emoji": "🟡", "text": "Частично свободен", "status": "partial"}
    else:
        return {"emoji": "🟢", "text": "Свободен", "status": "free"}

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
    kb.button(text="📅 Моё расписание", callback_data="r=t;a=schedule_main")
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
    kb.button(text="📅 Моё расписание", callback_data="r=t;a=schedule_main")
    kb.button(text="📚 Методические материалы", callback_data="r=t;a=materials_main")
    kb.button(text="👨‍🎓 Сдачи студентов", callback_data="r=t;a=submissions_main")
    kb.adjust(1)
    
    teacher_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
    if not teacher_name:
        teacher_name = "Преподаватель"
    
    text = f"👨‍🏫 <b>Добро пожаловать, {teacher_name}!</b>\n\n📚 Выберите нужный раздел:"
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

# ================================================================================================
# 📅 РАСПИСАНИЕ
# ================================================================================================

@router.callback_query(F.data == "r=t;a=schedule_main")
async def schedule_main_handler(cb: CallbackQuery):
    """Главное меню расписания"""
    await cb.answer()
    
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Создать расписание", callback_data="r=t;a=sched_create_start")
    kb.button(text="👀 Просмотреть расписание", callback_data="r=t;a=sched_view_dates")
    kb.button(text="✏️ Изменить расписание", callback_data="r=t;a=sched_edit_date")
    kb.button(text="⬅️ Назад", callback_data="r=t;a=back_to_main")
    kb.adjust(1)
    
    text = "📅 <b>Моё расписание</b>\n\nВыберите действие:"
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "r=t;a=sched_create_start")
async def sched_create_start_handler(cb: CallbackQuery):
    """Создание расписания - заглушка"""
    await cb.answer()
    
    text = "➕ <b>Создание расписания</b>\n\n🚧 Интеграция с существующим мастером в разработке\n\nПока используйте команду /schedule для создания слотов."
    
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data="r=t;a=schedule_main")
    
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "r=t;a=sched_view_dates")
async def sched_view_dates_handler(
    cb: CallbackQuery,
    actor_tg_id: int,
    users: UsersService,
    slots: SlotService
):
    """Просмотр расписания - выбор даты"""
    await cb.answer()
    
    ta_id = users.get_ta_id_by_tg(actor_tg_id)
    if not ta_id:
        await cb.message.edit_text("❌ Не удалось определить ваш TA ID")
        return
    
    try:
        slots_df = slots.table.read()
        if slots_df.empty:
            kb = InlineKeyboardBuilder()
            kb.button(text="⬅️ Назад", callback_data="r=t;a=schedule_main")
            await cb.message.edit_text(
                "📅 <b>Просмотр расписания</b>\n\nУ вас пока нет созданных слотов.\n\nСоздайте расписание: ➕ Создать расписание",
                reply_markup=kb.as_markup()
            )
            return
        
        ta_slots = slots_df[slots_df["ta_id"] == ta_id]
        if ta_slots.empty:
            kb = InlineKeyboardBuilder()
            kb.button(text="⬅️ Назад", callback_data="r=t;a=schedule_main")
            await cb.message.edit_text(
                "📅 <b>Просмотр расписания</b>\n\nУ вас пока нет созданных слотов.\n\nСоздайте расписание: ➕ Создать расписание",
                reply_markup=kb.as_markup()
            )
            return
        
        unique_dates = ta_slots["date"].unique()
        unique_dates = sorted([d for d in unique_dates if d])
        
        if not unique_dates:
            kb = InlineKeyboardBuilder()
            kb.button(text="⬅️ Назад", callback_data="r=t;a=schedule_main")
            await cb.message.edit_text(
                "📅 Нет доступных дат в расписании",
                reply_markup=kb.as_markup()
            )
            return
        
        kb = InlineKeyboardBuilder()
        
        for date_str in unique_dates[:10]:
            try:
                date_obj = datetime.fromisoformat(date_str).date()
                formatted_date = date_obj.strftime("%d.%m.%Y")
                date_slots = ta_slots[ta_slots["date"] == date_str]
                slots_count = len(date_slots)
                
                kb.button(
                    text=f"📅 {formatted_date} ({slots_count} слотов)",
                    callback_data=f"r=t;a=slot_list;d={date_str.replace('-', '')}"
                )
            except Exception as e:
                log.error(f"Error processing date {date_str}: {e}")
        
        kb.button(text="⬅️ Назад", callback_data="r=t;a=schedule_main")
        kb.adjust(1)
        
        text = "📅 <b>Просмотр расписания</b>\n\nВыберите дату для просмотра слотов:"
        await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
        
    except Exception as e:
        log.error(f"Error in sched_view_dates: {e}")
        await cb.message.edit_text(f"❌ Ошибка при загрузке расписания: {str(e)}")

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
        parts = cb.data.split(";")
        date_str = None
        for part in parts:
            if part.startswith("d="):
                date_str = part[2:]
                break
        
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
                callback_data=f"r=t;a=slot_actions;s={slot_id}"
            )
        
        kb.button(text="⬅️ Назад", callback_data="r=t;a=sched_view_dates")
        kb.adjust(1)
        
        text = f"📅 <b>Слоты на {formatted_date}</b>\n\nВыберите слот для просмотра деталей:"
        await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
        
    except Exception as e:
        log.error(f"Error in slot_list: {e}")
        await cb.message.edit_text(f"❌ Ошибка: {str(e)}")

@router.callback_query(F.data.startswith("r=t;a=slot_actions;s="))
async def slot_actions_handler(
    cb: CallbackQuery,
    slots: SlotService,
    bookings: BookingService
):
    """Карточка слота с действиями"""
    await cb.answer()
    
    # Извлекаем slot_id
    try:
        parts = cb.data.split(";")
        slot_id = None
        for part in parts:
            if part.startswith("s="):
                slot_id = part[2:]
                break
        
        if not slot_id:
            await cb.message.edit_text("❌ Не удалось определить ID слота")
            return
    except Exception:
        await cb.message.edit_text("❌ Ошибка обработки данных")
        return
    
    try:
        found, slot_dict = slots.get_slot_by_id(slot_id)
        if not found:
            await cb.message.edit_text("❌ Слот не найден")
            return
        
        # Получаем записи на слот
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
        
        status_info = get_slot_display_status(slot_dict, current_bookings)
        
        # Форматируем информацию
        date = slot_dict.get("date", "")
        time_from = slot_dict.get("time_from", "")
        time_to = slot_dict.get("time_to", "")
        capacity = int(slot_dict.get("capacity", 1))
        mode = slot_dict.get("mode", "online")
        location = slot_dict.get("location", "")
        meeting_link = slot_dict.get("meeting_link", "")
        
        if mode == "online" and meeting_link:
            place_info = f"💻 Онлайн: {meeting_link}"
        elif mode == "offline" and location:
            place_info = f"🏫 Очно: {location}"
        else:
            place_info = f"📍 {mode.title()}"
        
        text = f"⏰ <b>{time_from}–{time_to} | {date}</b>\n" \
               f"👥 {current_bookings}/{capacity} | Статус: {status_info['emoji']} {status_info['text']}\n" \
               f"📍 {place_info}\n\n"
        
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
        log.error(f"Error in slot_actions: {e}")
        await cb.message.edit_text(f"❌ Ошибка: {str(e)}")

@router.callback_query(F.data.startswith("r=t;a=slot_students;s="))
async def slot_students_handler(
    cb: CallbackQuery,
    bookings: BookingService,
    users: UsersService
):
    """Список записанных студентов (ОТЛАДКА)"""
    await cb.answer()
    
    # Извлекаем slot_id - добавляем отладку
    try:
        parts = cb.data.split(";")
        slot_id = None
        for part in parts:
            if part.startswith("s="):
                slot_id = part[2:]  # Убираем "s="
                break
        
        log.info(f"slot_students_handler: callback_data={cb.data}, slot_id={slot_id}")
        
        if not slot_id:
            log.error(f"slot_students_handler: slot_id not found in callback_data={cb.data}")
            await cb.answer("❌ Не удалось определить ID слота", show_alert=True)
            return
            
    except Exception as e:
        log.error(f"Error parsing slot_students callback: {cb.data}, error: {e}")
        await cb.answer("❌ Ошибка обработки данных", show_alert=True)
        return
    
    try:
        bookings_df = bookings.table.read()
        log.info(f"slot_students_handler: bookings_df shape={bookings_df.shape if not bookings_df.empty else 'empty'}")
        
        if bookings_df.empty:
            await cb.answer("Никто не записан на этот слот.", show_alert=True)
            return
        
        slot_bookings = bookings_df[bookings_df["slot_id"] == slot_id]
        log.info(f"slot_students_handler: slot_bookings for {slot_id}: {len(slot_bookings)} rows")
        
        active_bookings = slot_bookings[
            slot_bookings["status"].str.lower().isin(["active", "confirmed"])
        ] if "status" in slot_bookings.columns else slot_bookings
        
        log.info(f"slot_students_handler: active_bookings for {slot_id}: {len(active_bookings)} rows")
        
        if active_bookings.empty:
            await cb.answer("Никто не записан на этот слот.", show_alert=True)
            return
        
        lines = ["👨‍🎓 Записанные студенты:\n"]
        
        for i, (_, booking_row) in enumerate(active_bookings.iterrows()):
            tg_id = booking_row.get("student_tg_id")
            if tg_id:
                try:
                    student_user = users.get_by_tg(int(tg_id))
                    if student_user:
                        student_name = f"{student_user.get('first_name', '')} {student_user.get('last_name', '')}".strip()
                        if not student_name:
                            student_name = f"ID: {student_user.get('id', tg_id)}"
                    else:
                        student_name = f"TG: {tg_id}"
                    
                    created_at = booking_row.get("created_at", "")
                    if created_at:
                        try:
                            dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                            date_str = dt.strftime("%d.%m %H:%M")
                            lines.append(f"{i+1}. {student_name} (записался {date_str})")
                        except:
                            lines.append(f"{i+1}. {student_name}")
                    else:
                        lines.append(f"{i+1}. {student_name}")
                except Exception:
                    lines.append(f"{i+1}. ID: {tg_id}")
        
        students_text = "\n".join(lines)
        log.info(f"slot_students_handler: prepared text length={len(students_text)}")
        
        # ПРОБУЕМ РАЗНЫЕ СПОСОБЫ ОТОБРАЖЕНИЯ
        if len(lines) <= 2:  # Если только заголовок + один студент
            await cb.answer(students_text, show_alert=True)
        else:
            # Если много студентов, показываем в сообщении
            kb = InlineKeyboardBuilder()
            kb.button(text="⬅️ Назад", callback_data=f"r=t;a=slot_actions;s={slot_id}")
            await cb.message.edit_text(students_text, reply_markup=kb.as_markup())
        
    except Exception as e:
        log.error(f"Error listing students for slot {slot_id}: {e}", exc_info=True)
        await cb.answer("Ошибка при получении списка студентов.", show_alert=True)

# Действия со слотами - заглушки
@router.callback_query(F.data.startswith("r=t;a=slot_edit;s="))
@router.callback_query(F.data.startswith("r=t;a=slot_open;s="))
@router.callback_query(F.data.startswith("r=t;a=slot_close;s="))
@router.callback_query(F.data.startswith("r=t;a=slot_delete;s="))
async def slot_action_handler(cb: CallbackQuery):
    """Действия со слотом - заглушки"""
    await cb.answer()
    
    try:
        parts = cb.data.split(";")
        action = None
        slot_id = None
        for part in parts:
            if part.startswith("a="):
                action = part[2:]
            elif part.startswith("s="):
                slot_id = part[2:]
        
        if not action or not slot_id:
            await cb.message.edit_text("❌ Ошибка обработки данных")
            return
    except Exception:
        await cb.message.edit_text("❌ Ошибка обработки данных")
        return
    
    action_name = {
        "slot_open": "открытие",
        "slot_close": "закрытие", 
        "slot_delete": "удаление",
        "slot_edit": "редактирование"
    }.get(action, action)
    
    text = f"⚙️ <b>Действие: {action_name}</b>\n\n🚧 Интеграция с существующей логикой в разработке\n\nПока используйте /myslots_manage"
    
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data=f"r=t;a=slot_actions;s={slot_id}")
    
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

# Изменение расписания - ИСПРАВЛЯЕМ создание callback_data
@router.callback_query(F.data == "r=t;a=sched_edit_date")
async def sched_edit_date_handler(
    cb: CallbackQuery,
    actor_tg_id: int,
    users: UsersService,
    slots: SlotService
):
    """Изменение расписания - выбор даты (ИСПРАВЛЕНО)"""
    await cb.answer()
    
    ta_id = users.get_ta_id_by_tg(actor_tg_id)
    if not ta_id:
        await cb.message.edit_text("❌ Не удалось определить ваш TA ID")
        return
    
    try:
        slots_df = slots.table.read()
        if slots_df.empty:
            kb = InlineKeyboardBuilder()
            kb.button(text="⬅️ Назад", callback_data="r=t;a=schedule_main")
            await cb.message.edit_text(
                "✏️ <b>Изменение расписания</b>\n\nУ вас пока нет слотов для изменения.",
                reply_markup=kb.as_markup()
            )
            return
        
        ta_slots = slots_df[slots_df["ta_id"] == ta_id]
        if ta_slots.empty:
            kb = InlineKeyboardBuilder()
            kb.button(text="⬅️ Назад", callback_data="r=t;a=schedule_main")
            await cb.message.edit_text(
                "✏️ <b>Изменение расписания</b>\n\nУ вас пока нет слотов для изменения.",
                reply_markup=kb.as_markup()
            )
            return
        
        # Только будущие слоты
        now = datetime.now().date()
        future_slots = ta_slots[ta_slots["date"] >= now.isoformat()]
        
        if future_slots.empty:
            kb = InlineKeyboardBuilder()
            kb.button(text="⬅️ Назад", callback_data="r=t;a=schedule_main")
            await cb.message.edit_text(
                "✏️ <b>Изменение расписания</b>\n\nНет слотов для изменения (только прошедшие).",
                reply_markup=kb.as_markup()
            )
            return
        
        unique_dates = future_slots["date"].unique()
        unique_dates = sorted([d for d in unique_dates if d])
        
        kb = InlineKeyboardBuilder()
        
        for date_str in unique_dates[:10]:
            try:
                date_obj = datetime.fromisoformat(date_str).date()
                formatted_date = date_obj.strftime("%d.%m.%Y")
                
                date_slots = future_slots[future_slots["date"] == date_str]
                slots_count = len(date_slots)
                
                # ИСПРАВЛЯЕМ callback_data - используем slot_list вместо sched_edit_slot_list
                # так как мы все равно перенаправляем на slot_list
                callback_data = f"r=t;a=slot_list;d={date_str.replace('-', '')}"
                
                kb.button(
                    text=f"✏️ {formatted_date} ({slots_count} слотов)",
                    callback_data=callback_data
                )
                
                # Логируем для отладки
                log.debug(f"Created edit button with callback: {callback_data}")
                
            except Exception as e:
                log.error(f"Error processing edit date {date_str}: {e}")
        
        kb.button(text="⬅️ Назад", callback_data="r=t;a=schedule_main")
        kb.adjust(1)
        
        text = "✏️ <b>Изменение расписания</b>\n\nВыберите дату для изменения слотов:"
        
        await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
        
    except Exception as e:
        log.error(f"Error in sched_edit_date: {e}")
        await cb.message.edit_text(f"❌ Ошибка: {str(e)}")

# Исправляем обработчик изменения расписания - добавляем недостающий обработчик для дат
@router.callback_query(F.data.regexp(r"r=t;a=sched_edit_slot_list;d=\d{8}"))
async def sched_edit_slot_list_handler(
    cb: CallbackQuery,
    actor_tg_id: int,
    users: UsersService,
    slots: SlotService,
    bookings: BookingService
):
    """Список слотов для изменения (ИСПРАВЛЕНО - добавили обработчик)"""
    await cb.answer()
    
    # Переиспользуем обработчик списка слотов
    new_callback = cb.data.replace("sched_edit_slot_list", "slot_list")
    new_cb = copy.copy(cb)
    new_cb.data = new_callback
    
    await slot_list_handler(new_cb, actor_tg_id, users, slots, bookings)

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
    
    text = "📚 <b>Методические материалы</b>\n\n🚧 Функции в разработке\n\nВыберите действие:"
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "r=t;a=syllabus_view")
async def syllabus_view_handler(cb: CallbackQuery, weeks: WeeksService):
    """Просмотр тем курса как в /weeks_list"""
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
                lines.append(f"   📅 Дедлайн: {deadline_str} {status}")
                lines.append("")
            
            full_text = "\n".join(lines)
            if len(full_text) > 4000:
                lines = ["📖 <b>Темы курса (первые 10):</b>\n"]
                for _, row in weeks_df.head(10).iterrows():
                    status = row["status_emoji"] 
                    deadline_str = row["deadline_date"].strftime('%d.%m.%Y')
                    lines.append(f"<b>{row['week']}. {row['title']}</b>")
                    lines.append(f"   📅 Дедлайн: {deadline_str} {status}")
                    lines.append("")
                
                if len(weeks_df) > 10:
                    lines.append(f"... и ещё {len(weeks_df) - 10} тем")
                    
                text = "\n".join(lines)
            else:
                text = full_text
            
    except Exception as e:
        text = f"📖 <b>Темы курса</b>\n\n❌ Ошибка: {str(e)}"
    
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data="r=t;a=materials_main")
    
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "r=t;a=material_upload_pick_week")
async def material_upload_pick_week_handler(cb: CallbackQuery):
    """Загрузка материалов - заглушка"""
    await cb.answer()
    
    text = "📤 <b>Загрузка материалов</b>\n\n🚧 Функция в разработке\n\nЗдесь будет возможность загружать материалы по неделям курса."
    
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад", callback_data="r=t;a=materials_main")
    
    await cb.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")

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