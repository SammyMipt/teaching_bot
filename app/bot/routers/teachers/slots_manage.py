from __future__ import annotations

import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.exceptions import TelegramBadRequest

from app.services.slot_service import SlotService
from app.services.booking_service import BookingService
from app.services.users_service import UsersService

log = logging.getLogger("slots_manage")
router = Router(name="teachers_slots_manage")


# ----------------------- helpers -----------------------

def _is_nan(x) -> bool:
    return isinstance(x, float) and x != x  # NaN


def _nz_str(val, fallback: str = "") -> str:
    if isinstance(val, str) and val.strip():
        return val.strip()
    return fallback


def _nz_int(val, fallback: int = 0) -> int:
    if isinstance(val, (int,)) and not _is_nan(val):
        return int(val)
    if isinstance(val, (float,)) and not _is_nan(val):
        return int(val)
    if isinstance(val, str) and val.isdigit():
        return int(val)
    return fallback


def _short_name_by_tg(users: UsersService, tg_id: int) -> str:
    u = users.get_by_tg(int(tg_id)) or {}
    ln = _nz_str(u.get("last_name", ""))
    fn = _nz_str(u.get("first_name", ""))
    if ln or fn:
        init = (fn[:1] + ".") if fn else ""
        return f"{ln} {init}".strip()
    username = u.get("username")
    return f"@{username}" if username else str(tg_id)


def _slot_text(row: dict, names: list[str], booked_count: int | None = None) -> str:
    """Формирует текст карточки слота на основе строки CSV и списка имён записанных."""
    DEFAULT_LOCATION = "Аудитория по расписанию"

    date = _nz_str(row.get("date", ""))
    t_from = _nz_str(row.get("time_from", ""))
    t_to = _nz_str(row.get("time_to", ""))
    mode = _nz_str(row.get("mode", "online"))
    loc = _nz_str(row.get("location", DEFAULT_LOCATION), DEFAULT_LOCATION)
    cap = _nz_int(row.get("capacity", 0), 0)
    
    # Используем новые поля если доступны
    computed_status = row.get("computed_status", "free_full")
    display_color = row.get("display_color", "🟢")
    status_description = row.get("status_description", "")

    booked = booked_count if booked_count is not None else _nz_int(row.get("booked_count", 0), 0)
    left = max(0, cap - booked)

    if mode == "online":
        mode_label = "Онлайн"
    else:
        if loc and loc != DEFAULT_LOCATION:
            mode_label = f"Очно • {loc}"
        else:
            mode_label = "Очно"

    names_line = f"\n  Записаны: {', '.join(names)}" if names else ""

    return (
        f"{display_color} {date} {t_from}-{t_to} • {mode_label}\n"
        f"  мест: {cap}, занято: {booked}, свободно: {left}{status_description}"
        f"{names_line}"
    )


def _kb_manage(slot_id: str, computed_status: str) -> InlineKeyboardMarkup:
    """Создает клавиатуру управления слотом на основе вычисляемого статуса"""
    
    # Определяем доступные действия на основе статуса
    kb_buttons = []
    
    if computed_status in ("free_full", "free_partial", "busy"):
        # Можно закрыть
        kb_buttons.append([InlineKeyboardButton(text="❌ Закрыть запись", callback_data=f"slot:toggle_open:{slot_id}")])
    elif computed_status == "closed":
        # Можно открыть
        kb_buttons.append([InlineKeyboardButton(text="✅ Открыть запись", callback_data=f"slot:toggle_open:{slot_id}")])
    
    # Отменить можно всегда (кроме уже отмененных)
    if computed_status != "canceled":
        kb_buttons.append([InlineKeyboardButton(text="🗑 Отменить слот", callback_data=f"slot:cancel:{slot_id}")])
    
    # Список записанных всегда доступен
    kb_buttons.append([InlineKeyboardButton(text="👥 Список записанных", callback_data=f"slot:list:{slot_id}")])
    
    return InlineKeyboardMarkup(inline_keyboard=kb_buttons)


def _kb_confirm_cancel(slot_id: str) -> InlineKeyboardMarkup:
    yes = InlineKeyboardButton(text="Да, отменить", callback_data=f"slot:confirm_cancel:{slot_id}")
    no = InlineKeyboardButton(text="Нет", callback_data=f"slot:cancel_no:{slot_id}")
    return InlineKeyboardMarkup(inline_keyboard=[[yes, no]])


# ----------------------- /myslots_manage -----------------------

@router.message(Command("myslots_manage"))
async def myslots_manage(
    message: Message,
    role: str,
    slots: SlotService,
    bookings: BookingService,
    users: UsersService,
):
    if role not in ("ta", "owner"):
        await message.answer("Только для преподавателей.")
        return

    ta_id = users.get_ta_id_by_tg(message.from_user.id)
    if not ta_id:
        await message.answer("В вашем профиле не задан TA-ID.")
        return
    
    # Получаем обогащенные данные слотов
    df = slots.get_enriched_slots_for_teacher(ta_id, bookings)
    if df.empty:
        await message.answer("Слотов пока нет.")
        return

    # Показываем только не прошедшие слоты
    df_filtered = df[df["computed_status"] != "pasted"].copy()
    if df_filtered.empty:
        await message.answer("Ближайших слотов нет.")
        return

    # Сортируем по дате и времени
    try:
        df_filtered = df_filtered.sort_values(by=["date", "time_from", "time_to"])
    except Exception:
        pass

    count = 0
    for _, row in df_filtered.iterrows():
        row_dict = row.to_dict()
        slot_id = str(row_dict["slot_id"])
        computed_status = row_dict.get("computed_status", "free_full")
        
        # получаем список имён записанных
        names: list[str] = []
        try:
            bdf = bookings.list_for_slot(slot_id)
            if not bdf.empty and "student_tg_id" in bdf.columns:
                active = bdf
                if "status" in bdf.columns:
                    active = bdf[bdf["status"].str.lower().isin(["active", "confirmed"])]
                for tg in active["student_tg_id"].dropna().tolist():
                    try:
                        names.append(_short_name_by_tg(users, int(tg)))
                    except Exception:
                        continue
        except Exception:
            pass

        booked_count = len(names)
        text = _slot_text(row_dict, names, booked_count)
        kb = _kb_manage(slot_id, computed_status)
        await message.answer(text, reply_markup=kb)
        count += 1

    if count == 0:
        await message.answer("Ближайших слотов нет.")


# ----------------------- Callback handlers -----------------------

@router.callback_query(F.data.startswith("slot:toggle_open:"))
async def cb_toggle_open(cb: CallbackQuery, slots: SlotService, bookings: BookingService, users: UsersService):
    slot_id = cb.data.split(":")[-1]
    found, slot_dict = slots.get_slot_by_id(slot_id)
    if not found:
        await cb.answer("Слот не найден.", show_alert=True)
        return

    # Проверяем текущий статус
    current_bookings = 0
    try:
        bdf = bookings.list_for_slot(slot_id)
        if not bdf.empty and "status" in bdf.columns:
            active_bookings = bdf[bdf["status"].str.lower().isin(["active", "confirmed"])]
            current_bookings = len(active_bookings)
        else:
            current_bookings = len(bdf) if not bdf.empty else 0
    except Exception:
        pass

    computed_status = slots.get_computed_status(slot_dict, current_bookings)
    
    # Определяем действие
    if computed_status == "closed":
        # Открываем
        success = slots.set_open(slot_id, True)
        action_text = "открыт" if success else "не удалось открыть"
    else:
        # Закрываем
        success = slots.set_open(slot_id, False)
        action_text = "закрыт" if success else "не удалось закрыть"

    if success:
        # Обновляем сообщение
        try:
            # Получаем обновленные данные
            _, updated_slot = slots.get_slot_by_id(slot_id)
            updated_status = slots.get_computed_status(updated_slot, current_bookings)
            
            # Получаем имена записанных
            names = []
            try:
                bdf = bookings.list_for_slot(slot_id)
                if not bdf.empty and "student_tg_id" in bdf.columns:
                    active = bdf
                    if "status" in bdf.columns:
                        active = bdf[bdf["status"].str.lower().isin(["active", "confirmed"])]
                    for tg in active["student_tg_id"].dropna().tolist():
                        try:
                            names.append(_short_name_by_tg(users, int(tg)))
                        except Exception:
                            continue
            except Exception:
                pass

            # Добавляем вычисленные поля
            updated_slot["computed_status"] = updated_status
            updated_slot["display_color"] = slots.get_display_color(updated_status)
            updated_slot["status_description"] = slots.get_status_description(updated_status)
            updated_slot["booked_count"] = current_bookings

            text = _slot_text(updated_slot, names, current_bookings)
            kb = _kb_manage(slot_id, updated_status)
            await cb.message.edit_text(text, reply_markup=kb)
        except TelegramBadRequest:
            pass
    
    await cb.answer(f"Слот {action_text}")


@router.callback_query(F.data.startswith("slot:cancel:"))
async def cb_cancel_slot(cb: CallbackQuery):
    slot_id = cb.data.split(":")[-1]
    kb = _kb_confirm_cancel(slot_id)
    await cb.message.edit_text("⚠️ Вы уверены, что хотите отменить этот слот?", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("slot:confirm_cancel:"))
async def cb_confirm_cancel(cb: CallbackQuery, slots: SlotService):
    slot_id = cb.data.split(":")[-1]
    success = slots.cancel_slot(slot_id, canceled_by=str(cb.from_user.id), reason="Отменено преподавателем")
    
    if success:
        await cb.message.edit_text("✅ Слот отменён.")
    else:
        await cb.message.edit_text("❌ Не удалось отменить слот.")
    
    await cb.answer("Слот отменён" if success else "Ошибка отмены")


@router.callback_query(F.data.startswith("slot:cancel_no:"))
async def cb_cancel_no(cb: CallbackQuery, slots: SlotService, bookings: BookingService, users: UsersService):
    slot_id = cb.data.split(":")[-1]
    
    # Возвращаем исходное отображение слота
    found, slot_dict = slots.get_slot_by_id(slot_id)
    if not found:
        await cb.message.edit_text("Слот не найден.")
        await cb.answer()
        return

    # Получаем текущее состояние
    current_bookings = 0
    names = []
    try:
        bdf = bookings.list_for_slot(slot_id)
        if not bdf.empty and "student_tg_id" in bdf.columns:
            active = bdf
            if "status" in bdf.columns:
                active = bdf[bdf["status"].str.lower().isin(["active", "confirmed"])]
            current_bookings = len(active)
            for tg in active["student_tg_id"].dropna().tolist():
                try:
                    names.append(_short_name_by_tg(users, int(tg)))
                except Exception:
                    continue
        else:
            current_bookings = len(bdf) if not bdf.empty else 0
    except Exception:
        pass

    computed_status = slots.get_computed_status(slot_dict, current_bookings)
    
    # Добавляем вычисленные поля
    slot_dict["computed_status"] = computed_status
    slot_dict["display_color"] = slots.get_display_color(computed_status)
    slot_dict["status_description"] = slots.get_status_description(computed_status)
    slot_dict["booked_count"] = current_bookings

    text = _slot_text(slot_dict, names, current_bookings)
    kb = _kb_manage(slot_id, computed_status)
    
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("slot:list:"))
async def cb_list_bookings(cb: CallbackQuery, bookings: BookingService, users: UsersService):
    slot_id = cb.data.split(":")[-1]
    
    try:
        bdf = bookings.list_for_slot(slot_id)
        if bdf.empty:
            await cb.answer("Никто не записан на этот слот.", show_alert=True)
            return

        lines = ["Записанные студенты:"]
        
        # Фильтруем активные бронирования
        active_bookings = bdf
        if "status" in bdf.columns:
            active_bookings = bdf[bdf["status"].str.lower().isin(["active", "confirmed"])]
        
        if active_bookings.empty:
            await cb.answer("Никто не записан на этот слот.", show_alert=True)
            return

        for _, booking_row in active_bookings.iterrows():
            tg_id = booking_row.get("student_tg_id")
            if tg_id:
                try:
                    student_name = _short_name_by_tg(users, int(tg_id))
                    booked_at = booking_row.get("created_at", "")
                    if booked_at:
                        try:
                            # Форматируем дату
                            from datetime import datetime
                            dt = datetime.fromisoformat(booked_at.replace('Z', '+00:00'))
                            date_str = dt.strftime("%d.%m %H:%M")
                            lines.append(f"• {student_name} (записался {date_str})")
                        except:
                            lines.append(f"• {student_name}")
                    else:
                        lines.append(f"• {student_name}")
                except Exception:
                    lines.append(f"• ID: {tg_id}")

        await cb.answer("\n".join(lines), show_alert=True)
        
    except Exception as e:
        log.error(f"Error listing bookings for slot {slot_id}: {e}")
        await cb.answer("Ошибка при получении списка записанных.", show_alert=True)