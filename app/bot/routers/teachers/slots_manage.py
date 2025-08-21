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


def _status_mark_and_tail(status: str, cap: int, booked: int) -> tuple[str, str]:
    status = (status or "free").lower()
    if status == "closed":
        return "⚪", " • закрыт для записи"
    # free: раскрашиваем по занятости
    left = max(0, cap - booked)
    if left == cap:
        return "🟢", ""
    if left == 0:
        return "🔴", ""
    return "🟡", ""


def _slot_text(row: dict, names: list[str], booked_count: int | None = None) -> str:
    """Формирует текст карточки слота на основе строки CSV и списка имён записанных."""
    DEFAULT_LOCATION = "Аудитория по расписанию"

    date = _nz_str(row.get("date", ""))
    t_from = _nz_str(row.get("time_from", ""))
    t_to = _nz_str(row.get("time_to", ""))
    mode = _nz_str(row.get("mode", "online"))
    loc = _nz_str(row.get("location", DEFAULT_LOCATION), DEFAULT_LOCATION)
    cap = _nz_int(row.get("capacity", 0), 0)
    status = _nz_str(row.get("status", "free"), "free")

    booked = booked_count if booked_count is not None else _nz_int(row.get("booked_count", 0), 0)
    left = max(0, cap - booked)

    mark, tail = _status_mark_and_tail(status, cap, booked)

    if mode == "online":
        mode_label = "Онлайн"
    else:
        if loc and loc != DEFAULT_LOCATION:
            mode_label = f"Очно • {loc}"
        else:
            mode_label = "Очно"

    names_line = f"\n  Записаны: {', '.join(names)}" if names else ""

    return (
        f"{mark} {date} {t_from}-{t_to} • {mode_label}\n"
        f"  мест: {cap}, занято: {booked}, свободно: {left}{tail}"
        f"{names_line}"
    )


def _kb_manage(slot_id: str, status: str) -> InlineKeyboardMarkup:
    is_closed = (status or "free").lower() == "closed"
    toggle_text = "✅ Открыть запись" if is_closed else "❌ Закрыть запись"
    kb = [
        [InlineKeyboardButton(text=toggle_text, callback_data=f"slot:toggle_open:{slot_id}")],
        [InlineKeyboardButton(text="🗑 Отменить слот", callback_data=f"slot:cancel:{slot_id}")],
        [InlineKeyboardButton(text="👥 Список записанных", callback_data=f"slot:list:{slot_id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


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
    df = slots.list_for_teacher(ta_id)
    if df.empty:
        await message.answer("Слотов пока нет.")
        return

    # Покажем только будущие и не отменённые
    try:
        df = df.sort_values(by=["date", "time_from", "time_to"])
    except Exception:
        pass

    def _end_dt(d_str: str, to_str: str):
        try:
            y, m, d = map(int, d_str.split("-"))
            hh, mm = map(int, to_str.split(":"))
            return datetime(y, m, d, hh, mm)
        except Exception:
            return None

    now = datetime.now()
    count = 0

    for _, r in df.iterrows():
        status = _nz_str(r.get("status", "free"), "free").lower()
        if status == "canceled":
            continue

        date_str = _nz_str(r.get("date", ""))
        t_to = _nz_str(r.get("time_to", ""))
        if not date_str or not t_to:
            continue

        if (dt := _end_dt(date_str, t_to)) and dt <= now:
            continue  # прошло

        slot_id = str(r["slot_id"])
        # получаем список имён записанных (по желанию можно скрывать)
        try:
            bdf = bookings.list_for_slot(slot_id)
        except Exception:
            bdf = None

        names: list[str] = []
        if bdf is not None and not bdf.empty and "student_tg_id" in bdf.columns:
            active = bdf[bdf.get("status", "active") == "active"] if "status" in bdf.columns else bdf
            for tg in active["student_tg_id"].dropna().tolist():
                try:
                    names.append(_short_name_by_tg(users, int(tg)))
                except Exception:
                    continue

        booked_count = len(names)
        text = _slot_text(r.to_dict(), names, booked_count)
        kb = _kb_manage(slot_id, status)
        await message.answer(text, reply_markup=kb)
        count += 1

    if count == 0:
        await message.answer("Ближайших слотов нет.")


# ----------------------- callbacks -----------------------

@router.callback_query(F.data.startswith("slot:toggle_open:"))
async def cb_toggle_open(cb: CallbackQuery, slots: SlotService, bookings: BookingService, users: UsersService):
    slot_id = cb.data.split(":")[-1]
    ok, row = slots.get_by_id(slot_id)
    if not ok:
        await cb.answer("Слот не найден", show_alert=True)
        return

    curr = _nz_str(row.get("status", "free"), "free").lower()
    if curr == "canceled":
        await cb.answer("Слот уже отменён", show_alert=True)
        return

    new_status = "closed" if curr == "free" else "free"

    # сначала пишем CSV
    updated = False
    if hasattr(slots, "set_status"):
        try:
            updated = bool(slots.set_status(slot_id, new_status))
        except Exception as e:
            log.warning("set_status failed: %s", e)
    if not updated:
        # fallback прямой правкой таблицы
        df = slots.table.read()
        mask = df["slot_id"].astype(str) == str(slot_id)
        if mask.any():
            df.loc[mask, "status"] = new_status
            slots.table.write(df)
            updated = True

    if not updated:
        await cb.answer("Не удалось изменить состояние", show_alert=True)
        return

    # уведомим записанных только при закрытии
    if new_status == "closed":
        try:
            bdf = bookings.list_for_slot(slot_id)
        except Exception:
            bdf = None

        if bdf is not None and not bdf.empty and "student_tg_id" in bdf.columns:
            active = bdf[bdf.get("status", "active") == "active"] if "status" in bdf.columns else bdf
            tg_ids = [int(x) for x in active["student_tg_id"].dropna().tolist()]
            ta_id = str(row.get("ta_id", "")).strip()
            tg_for_ta = users.get_tg_by_ta_id(ta_id) if ta_id else None
            teacher = _short_name_by_tg(users, int(tg_for_ta)) if tg_for_ta and str(tg_for_ta).isdigit() else _nz_str(ta_id, "TA")
            notif = (
                f"Запись на приём у {teacher} закрыта\n"
                f"Слот: {row.get('date','')} {row.get('time_from','')}-{row.get('time_to','')}"
            )
            ok_cnt = 0
            for sid in tg_ids:
                try:
                    await cb.bot.send_message(sid, notif)
                    ok_cnt += 1
                except Exception as e:
                    log.warning("Notify student %s failed: %s", sid, e)
            log.info("Closed slot %s: notified %d students", slot_id, ok_cnt)

    await _refresh_card(cb, slots, bookings, slot_id, info=("Открыто для записи" if new_status == "free" else "Закрыто для записи"))


@router.callback_query(F.data.startswith("slot:cancel:"))
async def cb_cancel(cb: CallbackQuery, slots: SlotService):
    slot_id = cb.data.split(":")[-1]
    ok, _ = slots.get_by_id(slot_id)
    if not ok:
        await cb.answer("Слот не найден", show_alert=True)
        return
    await cb.message.edit_reply_markup(reply_markup=_kb_confirm_cancel(slot_id))
    await cb.answer()


@router.callback_query(F.data.startswith("slot:cancel_no:"))
async def cb_cancel_no(cb: CallbackQuery, slots: SlotService, bookings: BookingService):
    slot_id = cb.data.split(":")[-1]
    await _refresh_card(cb, slots, bookings, slot_id, info="Отмена не подтверждена")


@router.callback_query(F.data.startswith("slot:confirm_cancel:"))
async def cb_confirm_cancel(cb: CallbackQuery, slots: SlotService, bookings: BookingService, users: UsersService):
    slot_id = cb.data.split(":")[-1]
    ok, row = slots.get_by_id(slot_id)
    if not ok:
        await cb.answer("Слот не найден", show_alert=True)
        return

    # статус -> canceled
    updated = False
    if hasattr(slots, "set_status"):
        try:
            updated = bool(slots.set_status(slot_id, "canceled"))
        except Exception as e:
            log.warning("set_status(canceled) failed: %s", e)
    if not updated:
        df = slots.table.read()
        mask = df["slot_id"].astype(str) == str(slot_id)
        if mask.any():
            df.loc[mask, "status"] = "canceled"
            slots.table.write(df)
            updated = True

    if not updated:
        await cb.answer("Не удалось отменить слот", show_alert=True)
        return

    # уведомления записанным
    try:
        bdf = bookings.list_for_slot(slot_id)
    except Exception:
        bdf = None

    if bdf is not None and not bdf.empty and "student_tg_id" in bdf.columns:
        active = bdf[bdf.get("status", "active") == "active"] if "status" in bdf.columns else bdf
        tg_ids = [int(x) for x in active["student_tg_id"].dropna().tolist()]
        ta_id = str(row.get("ta_id", "")).strip()
        tg_for_ta = users.get_tg_by_ta_id(ta_id) if ta_id else None
        teacher = _short_name_by_tg(users, int(tg_for_ta)) if tg_for_ta and str(tg_for_ta).isdigit() else _nz_str(ta_id, "TA")
        notif = (
            f"Слот у {teacher} отменён\n"
            f"{row.get('date','')} {row.get('time_from','')}-{row.get('time_to','')}"
        )
        ok_cnt = 0
        for sid in tg_ids:
            try:
                await cb.bot.send_message(sid, notif)
                ok_cnt += 1
            except Exception as e:
                log.warning("Notify student %s failed: %s", sid, e)
        log.info("Canceled slot %s: notified %d students", slot_id, ok_cnt)

    # удалим карточку
    try:
        await cb.message.delete()
    except TelegramBadRequest:
        pass
    await cb.answer("Слот отменён")


@router.callback_query(F.data.startswith("slot:list:"))
async def cb_list_students(cb: CallbackQuery, bookings: BookingService, users: UsersService, slots: SlotService):
    slot_id = cb.data.split(":")[-1]
    try:
        bdf = bookings.list_for_slot(slot_id)
    except Exception:
        bdf = None

    names: list[str] = []
    if bdf is not None and not bdf.empty and "student_tg_id" in bdf.columns:
        active = bdf[bdf.get("status", "active") == "active"] if "status" in bdf.columns else bdf
        for tg in active["student_tg_id"].dropna().tolist():
            try:
                names.append(_short_name_by_tg(users, int(tg)))
            except Exception:
                continue

    if not names:
        await cb.answer("Никто не записан", show_alert=True)
        return

    await cb.answer("\n".join(names), show_alert=True)


# ----------------------- refresh card -----------------------

async def _refresh_card(cb: CallbackQuery, slots: SlotService, bookings: BookingService, slot_id: str, info: str | None = None):
    ok, row = slots.get_by_id(slot_id)
    if not ok:
        await cb.answer("Слот не найден", show_alert=True)
        return

    # посчитаем фактическую занятость
    booked_count = 0
    try:
        bdf = bookings.list_for_slot(slot_id)
    except Exception:
        bdf = None

    names: list[str] = []
    if bdf is not None and not bdf.empty and "student_tg_id" in bdf.columns:
        active = bdf[bdf.get("status", "active") == "active"] if "status" in bdf.columns else bdf
        ids = [int(x) for x in active["student_tg_id"].dropna().tolist()]
        booked_count = len(ids)

    text = _slot_text(row, names, booked_count)
    kb = _kb_manage(str(slot_id), _nz_str(row.get("status", "free"), "free"))

    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as e:
        msg = str(e).lower()
        if "message is not modified" in msg:
            # Обновим хотя бы клавиатуру
            try:
                await cb.message.edit_reply_markup(reply_markup=kb)
            except TelegramBadRequest:
                pass
            await cb.answer(info or "Без изменений")
            return
        raise

    await cb.answer(info or "")
