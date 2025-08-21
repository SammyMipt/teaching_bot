from __future__ import annotations

import math
import re
from datetime import datetime, date, time, timezone
from typing import Any, Dict, Optional, Tuple

import pandas as pd
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.services.users_service import UsersService
from app.services.slot_service import SlotService
from app.services.booking_service import BookingService
from app.services.assignments_service import AssignmentsService

router = Router(name="students_week_booking")


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _s(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, float) and math.isnan(val):
        return ""
    return str(val).strip()

def _now_utc_ts() -> float:
    return datetime.now(tz=timezone.utc).timestamp()

def _find_col(df: pd.DataFrame, *aliases: str) -> Optional[str]:
    """
    Вернуть первую подходящую колонку по набору синонимов (без учёта регистра и пробелов).
    """
    if df is None or df.empty:
        return None
    cols_norm = {re.sub(r"\s+", "", c).lower(): c for c in df.columns}
    for a in aliases:
        key = re.sub(r"\s+", "", a).lower()
        if key in cols_norm:
            return cols_norm[key]
    # мягкий startswith
    for a in aliases:
        prefix = re.sub(r"\s+", "", a).lower()
        for k, orig in cols_norm.items():
            if k.startswith(prefix):
                return orig
    return None

def _to_ts(val: Any) -> Optional[float]:
    """Преобразовать строку даты/времени или число в epoch seconds (UTC)."""
    if val is None:
        return None
    # уже число
    try:
        if isinstance(val, (int, float)) and not (isinstance(val, float) and math.isnan(val)):
            v = float(val)
            if v > 10**11:  # мс → сек
                v = v / 1000.0
            return v
    except Exception:
        pass
    # строка времени
    try:
        dt = pd.to_datetime(val, utc=True, dayfirst=False, errors="coerce")
        if pd.isna(dt):
            return None
        return dt.to_pydatetime().timestamp()
    except Exception:
        return None

def _combine_ts(d_str: str, t_str: str) -> Optional[float]:
    """
    Скомбинировать date ('YYYY-MM-DD') и time ('HH:MM') в локальное время,
    затем вернуть epoch seconds (UTC).
    """
    d = _s(d_str)
    t = _s(t_str)
    if not d or not t:
        return None
    try:
        y, m, dd = map(int, d.split("-"))
        hh, mm = map(int, t.split(":"))
        local_dt = datetime(y, m, dd, hh, mm)  # naive -> трактуем как локальное
        # Считаем, что локальная tz системы — корректная для бота
        aware = local_dt.astimezone()  # локальное → aware (локальная зона)
        return aware.astimezone(timezone.utc).timestamp()
    except Exception:
        return None

def _boolish(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    s = _s(val).lower()
    return s in {"1", "true", "yes", "y", "open", "opened", "active", "published", "включено", "открыт", "да"}

def _is_canceled(val: Any) -> bool:
    s = _s(val).lower()
    return s in {"cancel", "canceled", "cancelled", "отменен", "отменён"}

def _human_name(user: Optional[Dict[str, Any]]) -> str:
    if not user:
        return "—"
    first = _s(user.get("first_name"))
    last = _s(user.get("last_name"))
    if first or last:
        return f"{last} {first}".strip()
    uname = _s(user.get("username"))
    return f"@{uname}" if uname else "—"

def _ta_present(users: UsersService, ta_code: str) -> Tuple[str, Optional[str]]:
    """
    Вернуть метку для вывода и ta_id. В нашей текущей схеме ta_code == users.id
    (например, 'TA-00'), поэтому просто ищем по id.
    """
    code = _s(ta_code)
    if not code:
        return "не назначен", None
    u = users.get_by_id(code)
    name = _human_name(u)
    return f"{name} ({code})", (u or {}).get("id")

def _fmt_ts(ts: Optional[float]) -> str:
    if ts is None or (isinstance(ts, float) and math.isnan(ts)):
        return "?"
    dt = datetime.fromtimestamp(float(ts), tz=timezone.utc).astimezone()
    return dt.strftime("%d.%m %H:%M")

def _slot_brief_row(start_ts: Optional[float], end_ts: Optional[float], mode: str, place: str, remains: int) -> str:
    # "12.09 14:00–14:30 | online | Zoom | мест: 2"
    parts = [f"{_fmt_ts(start_ts)}–{_fmt_ts(end_ts)}"]
    if _s(mode):
        parts.append(_s(mode))
    if _s(place):
        parts.append(_s(place))
    parts.append(f"мест: {int(remains or 0)}")
    return " | ".join(parts)


# ──────────────────────────────────────────────────────────────────────────────
# Core filtering
# ──────────────────────────────────────────────────────────────────────────────

def _filter_slots_for_ta(slots_df: pd.DataFrame, bookings_df: pd.DataFrame, ta_id: str) -> pd.DataFrame:
    """
    Вернуть только будущие, открытые, не отменённые слоты указанного ТА с доступными местами.
    Поддерживает две схемы:
      1) явные поля времени: start_at/end_at (или их синонимы);
      2) пара полей date + time_from/time_to.
    Добавляет вычисленные поля:
      __start_ts, __end_ts, __remains, __slot_id, __mode, __place.
    """
    if slots_df is None or slots_df.empty:
        return pd.DataFrame()

    # Базовые колонки
    col_id = _find_col(slots_df, "slot_id", "id", "uid")
    col_ta = _find_col(slots_df, "ta_id", "teacher_tg_id", "owner_tg_id", "ta_tg_id", "teacher_id")
    col_status = _find_col(slots_df, "status")
    col_is_open = _find_col(slots_df, "is_open", "open", "opened")
    col_is_canceled = _find_col(slots_df, "is_canceled", "canceled", "cancelled", "cancel")
    col_capacity = _find_col(slots_df, "capacity", "cap", "places")
    col_format = _find_col(slots_df, "format", "mode")
    col_place = _find_col(slots_df, "place", "location", "room", "url", "link")

    # Временные колонки (варианты)
    col_start = _find_col(slots_df, "start_at", "start", "start_ts", "datetime", "begin_at")
    col_end = _find_col(slots_df, "end_at", "end", "end_ts", "finish_at")
    col_date = _find_col(slots_df, "date")
    col_from = _find_col(slots_df, "time_from", "from", "start_time")
    col_to = _find_col(slots_df, "time_to", "to", "end_time")
    col_duration = _find_col(slots_df, "duration_min", "duration")

    # Фильтр по ТА
    if not col_ta:
        return pd.DataFrame()
    df = slots_df.copy()
    df = df[df[col_ta].astype(str) == str(ta_id)]
    if df.empty:
        return df

    # Вычисляем start/end ts
    if col_start:
        st_ts = df[col_start].apply(_to_ts)
        en_ts = df[col_end].apply(_to_ts) if col_end else None
    else:
        # сборка из date + time_from / time_to (+ optional duration_min)
        st_ts = df.apply(lambda r: _combine_ts(r.get(col_date), r.get(col_from)), axis=1) if col_date and col_from else pd.Series([None] * len(df), index=df.index)
        if col_to:
            en_ts = df.apply(lambda r: _combine_ts(r.get(col_date), r.get(col_to)), axis=1)
        elif col_duration and col_from:
            # когда есть только длительность
            def _end_from_duration(r):
                st = _combine_ts(r.get(col_date), r.get(col_from))
                try:
                    dur = int(float(r.get(col_duration)))
                except Exception:
                    dur = 0
                if st is None or dur <= 0:
                    return None
                return st + dur * 60
            en_ts = df.apply(_end_from_duration, axis=1)
        else:
            en_ts = pd.Series([None] * len(df), index=df.index)

    now_ts = _now_utc_ts()
    df = df[st_ts.notna() & (st_ts > now_ts)]
    if df.empty:
        return df

    # Открыт и не отменён
    if col_status and "canceled" in set(df[col_status].astype(str).str.lower().unique()):
        df = df[df[col_status].astype(str).str.lower() != "canceled"]
    if col_is_open:
        df = df[df[col_is_open].apply(_boolish)]
    if df.empty:
        return df
    if col_is_canceled:
        df = df[~df[col_is_canceled].apply(_is_canceled)]
    if df.empty:
        return df

    # Ёмкость
    if not col_capacity:
        return pd.DataFrame()
    df[col_capacity] = pd.to_numeric(df[col_capacity], errors="coerce").fillna(0).astype(int)

    # Брони → остаток мест
    if bookings_df is None:
        bookings_df = pd.DataFrame()
    b_slot = _find_col(bookings_df, "slot_id", "id", "uid")
    b_status = _find_col(bookings_df, "status", "state")
    if b_slot:
        bdf = bookings_df.copy()
        if b_status:
            bdf = bdf[bdf[b_status].map(lambda v: _s(v).lower() not in {"cancel", "canceled", "cancelled", "отменен", "отменён"})]
        booked_counts = bdf.groupby(b_slot).size()
        def remains(row) -> int:
            sid = str(row[col_id]) if col_id else None
            taken = int(booked_counts.get(sid, 0)) if sid is not None else 0
            return max(int(row[col_capacity]) - taken, 0)
        remains_series = df.apply(remains, axis=1)
    else:
        remains_series = df[col_capacity].clip(lower=0)

    # Итог: добиваем технику подписи
    out = df.copy()
    out["__start_ts"] = st_ts.loc[df.index]
    out["__end_ts"] = en_ts.loc[df.index] if en_ts is not None else None
    out["__remains"] = remains_series
    out["__slot_id"] = out[col_id].astype(str) if col_id else out.index.astype(str)
    out["__mode"] = out[col_format] if col_format else ""
    out["__place"] = out[col_place] if col_place else ""
    return out[out["__remains"] > 0]


# ──────────────────────────────────────────────────────────────────────────────
# Handlers
# ──────────────────────────────────────────────────────────────────────────────

@router.message(F.text.startswith("/week"))
async def week_info(
    message: Message,
    actor_tg_id: int,
    users: UsersService,
    assignments: AssignmentsService,
):
    """
    /week <n> — показать, кто принимает у студента неделю n и кнопку «Показать слоты».
    """
    # Парсим номер недели
    week = None
    m = re.match(r"^/week\s+(\d+)", _s(message.text))
    if m:
        week = int(m.group(1))
    if not week:
        await message.answer("Укажите неделю: /week 1")
        return

    # Находим текущего студента
    stu = users.get_by_tg(actor_tg_id)
    if not stu or _s(stu.get("role")) != "student":
        await message.answer("Команда доступна только студентам. Пройдите регистрацию: /register")
        return
    # после миграции идентификатор студента хранится в users.id
    student_code = _s(stu.get("id") or stu.get("student_code"))

    # Назначение
    a = None
    try:
        a = assignments.get(student_code, week)
    except Exception:
        a = None

    if a is None:
        await message.answer(f"Для недели {week} пока нет назначенного проверяющего.")
        return

    # нормализуем ответ AssignmentsService (строка/словарь)
    if isinstance(a, str):
        ta_code = _s(a)
    elif isinstance(a, dict):
        ta_code = _s(a.get("ta_code") or a.get("ta") or "")
    else:
        ta_code = _s(a)

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
    df = _filter_slots_for_ta(sdf, bdf, ta_id)
    if df is None or df.empty:
        await cb.message.edit_text(f"Слоты {ta_label} не найдены (нет открытых ближайших).")
        await cb.answer()
        return

    kb = InlineKeyboardBuilder()
    df = df.sort_values(["__start_ts", "__slot_id"])
    for _, row in df.iterrows():
        label = _slot_brief_row(row.get("__start_ts"), row.get("__end_ts"), _s(row.get("__mode")), _s(row.get("__place")), int(row.get("__remains") or 0))
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

    # Таблицы
    sdf = slots.table.read()
    bdf = bookings.table.read()

    # Колонки
    s_id = _find_col(sdf, "slot_id", "id", "uid")
    s_status = _find_col(sdf, "status")
    s_open = _find_col(sdf, "is_open", "open", "opened")
    s_cancel = _find_col(sdf, "is_canceled", "canceled", "cancelled", "cancel")
    s_capacity = _find_col(sdf, "capacity", "cap", "places")

    # Время
    s_start = _find_col(sdf, "start_at", "start", "start_ts", "datetime", "begin_at")
    s_end = _find_col(sdf, "end_at", "end", "end_ts", "finish_at")
    s_date = _find_col(sdf, "date")
    s_from = _find_col(sdf, "time_from", "from", "start_time")
    s_to = _find_col(sdf, "time_to", "to", "end_time")
    s_dur = _find_col(sdf, "duration_min", "duration")

    # Найдём слот
    if not s_id or slot_id not in sdf[s_id].astype(str).values:
        await cb.answer("Слот не найден", show_alert=True)
        return
    row = sdf.loc[sdf[s_id].astype(str) == slot_id].iloc[0]

    # Валидации слота: будущий, открыт, не отменён, есть места
    if s_start:
        start_ts = _to_ts(row.get(s_start))
        end_ts = _to_ts(row.get(s_end)) if s_end else None
    else:
        start_ts = _combine_ts(row.get(s_date), row.get(s_from)) if s_date and s_from else None
        if s_to:
            end_ts = _combine_ts(row.get(s_date), row.get(s_to))
        elif s_dur and s_from:
            try:
                dur = int(float(row.get(s_dur)))
            except Exception:
                dur = 0
            end_ts = start_ts + dur * 60 if start_ts and dur > 0 else None
        else:
            end_ts = None

    if not start_ts or start_ts <= _now_utc_ts():
        await cb.answer("Слот уже прошёл.", show_alert=True)
        return

    if s_status and str(row.get(s_status, "")).lower() == "canceled":
        await cb.answer("Слот отменён.", show_alert=True)
        return
    if s_open and not _boolish(row.get(s_open)):
        await cb.answer("Слот закрыт.", show_alert=True)
        return
    if s_cancel and _is_canceled(row.get(s_cancel)):
        await cb.answer("Слот отменён.", show_alert=True)
        return

    cap = int(pd.to_numeric(row.get(s_capacity), errors="coerce") if s_capacity else 0)
    if cap <= 0:
        await cb.answer("Мест нет.", show_alert=True)
        return

    # Текущее количество броней на слот
    b_slot = _find_col(bdf, "slot_id", "id", "uid")
    b_status = _find_col(bdf, "status", "state")
    b_student = _find_col(bdf, "student_tg_id", "student_id", "tg_id")
    if b_slot:
        active_b = bdf.copy()
        if b_status:
            active_b = active_b[active_b[b_status].map(lambda v: _s(v).lower() not in {"cancel", "canceled", "cancelled", "отменен", "отменён"})]
        # Уже записан этот студент?
        if b_student:
            dup = active_b[(active_b[b_slot].astype(str) == slot_id) & (active_b[b_student].astype(str) == str(actor_tg_id))]
            if not dup.empty:
                await cb.answer("Вы уже записаны на этот слот.", show_alert=True)
                return
        taken = int((active_b[b_slot].astype(str) == slot_id).sum())
        if taken >= cap:
            await cb.answer("Мест уже нет.", show_alert=True)
            return

    # Готовим запись
    new_row = {}
    # Сопоставим стандартные поля
    if b_slot:
        new_row[b_slot] = slot_id
    if b_student:
        new_row[b_student] = actor_tg_id
    if b_status:
        new_row[b_status] = "active"
    # Стандартизируем минимальный набор
    new_row.setdefault("slot_id", slot_id)
    new_row.setdefault("student_tg_id", actor_tg_id)
    new_row.setdefault("status", "active")
    # timestamp
    new_row.setdefault("created_at", datetime.now(timezone.utc).isoformat())

    # Записываем
    bdf2 = bookings.table.read()
    # гарантируем наличие всех колонок перед записью
    for k in new_row.keys():
        if k not in bdf2.columns:
            bdf2[k] = None
    bdf2 = pd.concat([bdf2, pd.DataFrame([new_row])], ignore_index=True)

    with bookings.table.lock:
        bdf2.to_csv(bookings.table.path, index=False)

    # Ответ
    label = _slot_brief_row(start_ts, end_ts, _s(row.get(_find_col(sdf, "format", "mode"))), _s(row.get(_find_col(sdf, "place", "location", "room", "url", "link"))), max(cap - 1, 0))
    await cb.message.edit_text(f"✅ Записаны на слот: {label}")
    await cb.answer("Готово")
