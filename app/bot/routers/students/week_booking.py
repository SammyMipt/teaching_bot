from __future__ import annotations
import pandas as pd
from datetime import datetime, timezone
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.services.assignments_service import AssignmentsService
from app.services.users_service import UsersService
from app.services.slot_service import SlotService
from app.services.booking_service import BookingService

router = Router(name="students_week_booking")

def _s(v) -> str:
    return str(v or "").strip()

def _find_col(df: pd.DataFrame, *candidates: str) -> str | None:
    for col in candidates:
        if col in df.columns:
            return col
    return None

def _ta_present(users: UsersService, ta_code: str) -> tuple[str, str | None]:
    """Возвращает (label, ta_id). Если TA не найден, ta_id=None."""
    if not ta_code:
        return "—", None
    
    # Попробуем найти по ta_code
    ta_id = users.get_ta_id_by_code(ta_code)
    if ta_id:
        row = users.get_by_id(ta_id)
        if row:
            fn = _s(row.get("first_name"))
            ln = _s(row.get("last_name"))
            name = f"{ln} {fn}".strip() or f"TA-{ta_code}"
            return name, ta_id
    
    return f"TA-{ta_code}", None

def _filter_slots_for_ta(slots_df: pd.DataFrame, bookings_df: pd.DataFrame, ta_id: str, slot_service: SlotService) -> pd.DataFrame | None:
    """Фильтрует слоты конкретного TA, показывая только доступные для записи."""
    if slots_df.empty:
        return None

    # Найдем колонку TA
    ta_col = _find_col(slots_df, "ta_id", "teacher_id", "instructor_id")
    if not ta_col:
        return None

    # Фильтруем по TA
    ta_slots = slots_df[slots_df[ta_col].astype(str) == str(ta_id)].copy()
    if ta_slots.empty:
        return ta_slots

    # Обогащаем вычисляемыми статусами
    enriched_slots = []
    for _, row in ta_slots.iterrows():
        slot_dict = row.to_dict()
        slot_id = slot_dict.get("slot_id")
        
        # Считаем активные бронирования
        current_bookings = 0
        if not bookings_df.empty and slot_id:
            slot_bookings = bookings_df[bookings_df.get("slot_id", pd.Series()).astype(str) == str(slot_id)]
            if not slot_bookings.empty:
                status_col = _find_col(slot_bookings, "status", "state")
                if status_col:
                    active_bookings = slot_bookings[
                        slot_bookings[status_col].str.lower().isin(["active", "confirmed"])
                    ]
                    current_bookings = len(active_bookings)
                else:
                    current_bookings = len(slot_bookings)

        # Вычисляем статус
        computed_status = slot_service.get_computed_status(slot_dict, current_bookings)
        
        # Показываем только доступные для записи
        if computed_status in ("free_full", "free_partial"):
            slot_dict["__computed_status"] = computed_status
            slot_dict["__current_bookings"] = current_bookings
            slot_dict["__slot_id"] = slot_id
            
            # Парсим время для сортировки
            try:
                date_str = _s(slot_dict.get("date", ""))
                time_from_str = _s(slot_dict.get("time_from", ""))
                time_to_str = _s(slot_dict.get("time_to", ""))
                
                if date_str and time_from_str and time_to_str:
                    y, m, d = map(int, date_str.split("-"))
                    h_start, min_start = map(int, time_from_str.split(":"))
                    h_end, min_end = map(int, time_to_str.split(":"))
                    
                    start_dt = datetime(y, m, d, h_start, min_start, tzinfo=timezone.utc)
                    end_dt = datetime(y, m, d, h_end, min_end, tzinfo=timezone.utc)
                    
                    slot_dict["__start_ts"] = start_dt
                    slot_dict["__end_ts"] = end_dt
                    slot_dict["__mode"] = _s(slot_dict.get("mode", "online"))
                    
                    location = _s(slot_dict.get("location", ""))
                    meeting_link = _s(slot_dict.get("meeting_link", ""))
                    
                    if slot_dict["__mode"] == "online" and meeting_link:
                        slot_dict["__place"] = meeting_link
                    elif location:
                        slot_dict["__place"] = location
                    else:
                        slot_dict["__place"] = "Аудитория по расписанию"
                    
                    capacity = int(slot_dict.get("capacity", 1))
                    slot_dict["__remains"] = capacity - current_bookings
                    
                    enriched_slots.append(slot_dict)
            except (ValueError, AttributeError):
                continue

    if not enriched_slots:
        return pd.DataFrame()
    
    return pd.DataFrame(enriched_slots)

def _slot_brief_row(start_ts, end_ts, mode: str, place: str, remains: int) -> str:
    """Краткое описание слота для кнопки."""
    try:
        if isinstance(start_ts, datetime) and isinstance(end_ts, datetime):
            time_str = f"{start_ts.strftime('%H:%M')}-{end_ts.strftime('%H:%M')}"
            date_str = start_ts.strftime('%d.%m')
        else:
            time_str = f"{start_ts}-{end_ts}"
            date_str = "???"
        
        mode_emoji = "💻" if mode == "online" else "🏫"
        place_short = place[:15] + "..." if len(place) > 15 else place
        
        return f"{date_str} {time_str} {mode_emoji} {place_short} (мест: {remains})"
    except Exception:
        return f"{start_ts}-{end_ts} {mode} {place} (мест: {remains})"

@router.message(F.text.startswith("/week"))
async def week_booking(
    message: Message,
    actor_tg_id: int,  # Используем actor_tg_id из middleware
    users: UsersService,
    assignments: AssignmentsService,
):
    """
    Показать назначенного ТА для недели и дать кнопку перехода к его слотам.
    /week [номер_недели]
    """
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /week [номер_недели]")
        return
    
    try:
        week = int(parts[1])
    except ValueError:
        await message.answer("Номер недели должен быть числом.")
        return

    # Проверяем роль студента и получаем его student_code
    user = users.get_by_tg(actor_tg_id)
    if not user or user.get("role") != "student":
        await message.answer("Команда доступна только студентам. Пройдите регистрацию: /register")
        return

    # Получаем student_code из профиля пользователя
    student_code = user.get("id") or user.get("student_code")
    if not student_code:
        await message.answer("В вашем профиле не указан student_code. Обратитесь к администратору.")
        return

    # Получаем назначение для студента на эту неделю
    ta_code = assignments.get_assignment_for_student_code(str(student_code), week)
    if not ta_code:
        await message.answer(f"Для недели {week} пока нет назначенного проверяющего.")
        return

    ta_label, ta_id = _ta_present(users, ta_code)
    lines = [f"Неделя {week}: принимает {ta_label}."]
    kb = InlineKeyboardBuilder()
    if ta_id:
        kb.button(text="📅 Показать слоты этого ТА", callback_data=f"wk:slots:{ta_code}:{week}")

    await message.answer("\n".join(lines), reply_markup=kb.as_markup() if ta_id else None)


@router.callback_query(F.data.startswith("wk:slots:"))
async def show_ta_slots(
    cb: CallbackQuery,
    users: UsersService,
    slots: SlotService,
    bookings: BookingService,
):
    """
    Показать только актуальные слоты конкретного ТА (будущие, открытые, с местами).
    callback: wk:slots:<ta_code>:<week>
    """
    try:
        _, _, ta_code, week_str = _s(cb.data).split(":", 3)
    except Exception:
        await cb.answer("Некорректный запрос", show_alert=True)
        return

    ta_label, ta_id = _ta_present(users, ta_code)
    if not ta_id:
        await cb.answer("У преподавателя не задан внутренний TA-ID (users.id)", show_alert=True)
        return

    sdf = slots.table.read()
    bdf = bookings.table.read()
    df = _filter_slots_for_ta(sdf, bdf, ta_id, slots)
    if df is None or df.empty:
        await cb.message.edit_text(f"Слоты {ta_label} не найдены (нет открытых ближайших).")
        await cb.answer()
        return

    kb = InlineKeyboardBuilder()
    df = df.sort_values(["__start_ts", "__slot_id"])
    for _, row in df.iterrows():
        label = _slot_brief_row(
            row.get("__start_ts"), 
            row.get("__end_ts"), 
            _s(row.get("__mode")), 
            _s(row.get("__place")), 
            int(row.get("__remains") or 0)
        )
        slot_id = _s(row.get("__slot_id"))
        kb.button(text=f"Записаться: {label}", callback_data=f"wk:book:{ta_code}:{slot_id}")
    kb.adjust(1)

    await cb.message.edit_text(f"Слоты {ta_label}:", reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("wk:book:"))
async def book_slot(
    cb: CallbackQuery,
    actor_tg_id: int,
    users: UsersService,
    bookings: BookingService,
    slots: SlotService,
):
    """
    Бронирование слота. Повторная валидация: слот открытый, будущий, есть места, студент не записан.
    callback: wk:book:<ta_code>:<slot_id>
    """
    try:
        _, _, ta_code, slot_id = _s(cb.data).split(":", 3)
    except Exception:
        await cb.answer("Некорректные данные", show_alert=True)
        return

    # Найдём студента
    stu = users.get_by_tg(actor_tg_id)
    if not stu or _s(stu.get("role")) != "student":
        await cb.answer("Бронь доступна только студентам.", show_alert=True)
        return

    # Проверяем существование слота
    found, slot_dict = slots.get_slot_by_id(slot_id)
    if not found:
        await cb.answer("Слот не найден.", show_alert=True)
        return

    # Получаем текущие бронирования
    try:
        bdf = bookings.list_for_slot(slot_id)
        current_bookings = 0
        if not bdf.empty:
            # Считаем активные бронирования
            if "status" in bdf.columns:
                active_bookings = bdf[bdf["status"].str.lower().isin(["active", "confirmed"])]
                current_bookings = len(active_bookings)
                
                # Проверяем, не записан ли уже этот студент
                student_bookings = active_bookings[
                    active_bookings["student_tg_id"].astype(str) == str(actor_tg_id)
                ]
                if not student_bookings.empty:
                    await cb.answer("Вы уже записаны на этот слот.", show_alert=True)
                    return
            else:
                current_bookings = len(bdf)
                # Проверяем дубли
                student_bookings = bdf[bdf["student_tg_id"].astype(str) == str(actor_tg_id)]
                if not student_bookings.empty:
                    await cb.answer("Вы уже записаны на этот слот.", show_alert=True)
                    return
    except Exception:
        current_bookings = 0

    # Проверяем доступность слота
    computed_status = slots.get_computed_status(slot_dict, current_bookings)
    
    if computed_status not in ("free_full", "free_partial"):
        status_messages = {
            "busy": "Мест уже нет.",
            "closed": "Слот закрыт.",
            "canceled": "Слот отменён.",
            "pasted": "Слот уже прошел."
        }
        await cb.answer(status_messages.get(computed_status, "Слот недоступен."), show_alert=True)
        return

    # Проверяем лимит мест
    capacity = int(slot_dict.get("capacity", 1))
    if current_bookings >= capacity:
        await cb.answer("Мест уже нет.", show_alert=True)
        return

    # Создаем бронирование
    try:
        from datetime import datetime, timezone
        booking_row = {
            "slot_id": slot_id,
            "student_tg_id": actor_tg_id,
            "status": "active",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "comment": ""
        }
        
        # Добавляем бронирование через CSV таблицу
        bookings.table.append_row(booking_row)
        
        # Формируем красивый ответ
        date_str = slot_dict.get('date', '')
        time_from = slot_dict.get('time_from', '')
        time_to = slot_dict.get('time_to', '')
        mode = slot_dict.get('mode', 'online')
        location = slot_dict.get('location', '')
        meeting_link = slot_dict.get('meeting_link', '')
        
        # Определяем, что показать в качестве места
        place_info = ""
        if mode == "online":
            if meeting_link:
                place_info = f"\n🔗 {meeting_link}"
            else:
                place_info = "\n💻 Онлайн"
        else:
            if location and location != "Аудитория по расписанию":
                place_info = f"\n🏫 {location}"
            else:
                place_info = "\n🏫 Очно (место уточнит преподаватель)"

        # Вычисляем новый статус после записи
        new_bookings = current_bookings + 1
        new_status = slots.get_computed_status(slot_dict, new_bookings)
        
        status_suffix = ""
        if new_status == "busy":
            status_suffix = " (последнее место)"
        elif new_status == "free_partial":
            remaining = capacity - new_bookings
            status_suffix = f" (осталось мест: {remaining})"

        await cb.message.edit_text(
            f"✅ Записаны на слот{status_suffix}!\n"
            f"📅 {date_str} {time_from}-{time_to}"
            f"{place_info}"
        )
        await cb.answer("Готово!")
        
    except Exception as e:
        await cb.answer(f"Ошибка при записи: {str(e)}", show_alert=True)