from __future__ import annotations

from aiogram import Router, F
from aiogram.types import Message

from app.services.slot_service import SlotService
from app.services.booking_service import BookingService
from app.services.users_service import UsersService
from app.utils.time import parse_time_range

from datetime import datetime, date as _date, time as _time
import locale

router = Router(name="teachers_slots_admin")


def ensure_ta(role: str) -> bool:
    return role in ("ta", "owner")


@router.message(F.text.startswith("/addslot"))
async def addslot(message: Message, role: str, slots: SlotService, users: UsersService):
    """
    Быстрое добавление одного слота вручную:
    /addslot YYYY-MM-DD HH:MM-HH:MM [online|offline] [location]
    """
    if not ensure_ta(role):
        await message.answer("Только для преподавателей.")
        return

    parts = message.text.split(maxsplit=4)
    if len(parts) < 3:
        await message.answer("Формат: /addslot YYYY-MM-DD HH:MM-HH:MM [online|offline] [location]")
        return

    date_str = parts[1]
    time_from, time_to = parse_time_range(parts[2])
    mode = parts[3] if len(parts) >= 4 else "online"
    location = parts[4] if len(parts) >= 5 else ""

    ta_id = users.get_ta_id_by_tg(message.from_user.id)
    if not ta_id:
        await message.answer("В вашем профиле не задан TA-ID.")
        return

    row = slots.add_slot(
        ta_id=ta_id,
        date=date_str,
        time_from=time_from,
        time_to=time_to,
        mode=mode,
        location=location,
    )

    await message.answer(
        f"Добавлен слот: {date_str} {time_from}-{time_to} "
        f"({ 'Онлайн' if mode == 'online' else 'Очно' }"
        f"{f' • {location}' if (mode == 'offline' and location.strip()) else ''})"
    )


@router.message(F.text == "/myslots")
async def myslots(
    message: Message,
    role: str,
    slots: SlotService,
    bookings: BookingService,
    users: UsersService,
):
    """
    Красивое отображение слотов преподавателя:
    - разбивка по датам (заголовок дня)
    - внутри дня: по онлайн‑ссылкам (каждая ссылка — секция) и отдельный блок «Очно»
    - скрываем прошедшие/завершившиеся и отменённые слоты
    - без slot_id
    - индикаторы занятости (🟢 свободно / 🟡 частично / 🔴 занято)
    - список фамилий записавшихся
    - NaN-safe для CSV
    """
    if not ensure_ta(role):
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

    DEFAULT_LOCATION = "Аудитория по расписанию"

    def _is_nan(x) -> bool:
        return isinstance(x, float) and x != x  # NaN
    
    def _status_mark_and_tail(s: dict) -> tuple[str, str]:
        """Возвращает (иконка, 'хвост') для статуса."""
        status = (s.get("status") or "free").lower()
        if status == "closed":
            return "⚪", " • закрыт для записи"
        # free -> считаем по заполненности
        left = max(0, int(s["cap"]) - int(s["booked"]))
        if left == s["cap"]:
            return "🟢", ""
        if left == 0:
            return "🔴", ""
        return "🟡", ""

    def nz_str(val: object, fallback: str = "") -> str:
        if isinstance(val, str) and val.strip():
            return val.strip()
        return fallback

    def nz_int(val: object, fallback: int = 0) -> int:
        if isinstance(val, (int,)) and not _is_nan(val):
            return int(val)
        if isinstance(val, float) and not _is_nan(val):
            return int(val)
        return fallback

    def short_name_by_tg(tg_id: int) -> str:
        u = users.get_by_tg(int(tg_id)) or {}
        ln = nz_str(u.get("last_name", ""))
        fn = nz_str(u.get("first_name", ""))
        if ln or fn:
            init = (fn[:1] + ".") if fn else ""
            return f"{ln} {init}".strip()
        username = u.get("username")
        return f"@{username}" if username else str(tg_id)

    def parse_end_dt(d_str: str, to_str: str) -> datetime | None:
        try:
            y, m, d = map(int, d_str.split("-"))
            hh, mm = map(int, to_str.split(":"))
            return datetime(y, m, d, hh, mm)
        except Exception:
            return None

    now = datetime.now()

    # Отсортируем и заранее отфильтруем отменённые/прошедшие
    try:
        df = df.sort_values(by=["date", "time_from", "time_to"])
    except Exception:
        pass

    filtered_rows: list[dict] = []
    for _, r in df.iterrows():
        status = nz_str(r.get("status", "active"), "active").lower()
        if status == "canceled":
            continue

        date_str = nz_str(r.get("date", ""))
        t_from = nz_str(r.get("time_from", ""))
        t_to = nz_str(r.get("time_to", ""))

        # если нет корректной даты/времени — пропускаем
        if not date_str or not t_to:
            continue

        end_dt = parse_end_dt(date_str, t_to)
        if end_dt and end_dt <= now:
            # уже прошло или закончилось
            continue

        # нормализуем поля для дальнейшей логики
        cap = nz_int(r.get("capacity", 1), 1)
        mode = nz_str(r.get("mode", "online"), "online")
        link = nz_str(r.get("meeting_link", ""), "")
        location = nz_str(r.get("location", DEFAULT_LOCATION), DEFAULT_LOCATION)

        # подтянем брони
        try:
            bdf = bookings.list_for_slot(r["slot_id"])
        except AttributeError:
            bdf = bookings.table.find(slot_id=r["slot_id"])

        names: list[str] = []
        if bdf is not None and not bdf.empty:
            # учитывать только активные брони (если есть колонка status)
            cols = {c.lower(): c for c in bdf.columns}
            col_status = cols.get("status")
            if col_status:
                bdf = bdf[bdf[col_status].astype(str).str.lower() != "canceled"]

            # взять колонку с tg студента (поддержим разные названия)
            col_tg = cols.get("student_tg_id") or cols.get("tg_id") or cols.get("student_id")
            if col_tg:
                for tg in bdf[col_tg].astype(str).tolist():
                    try:
                        names.append(short_name_by_tg(int(tg)))
                    except Exception:
                        continue

        filtered_rows.append(
            dict(
                date=date_str,
                from_=t_from,
                to=t_to,
                cap=cap,
                booked=len(names),
                names=names,
                mode=mode,
                link=link,
                location=location,
                status=status,  # <= ВАЖНО
            )
        )

    if not filtered_rows:
        await message.answer("Ближайших слотов нет.")
        return

    # Группировка: date -> { online: {link: [slots]}, offline: [slots] }
    by_date: dict[str, dict] = {}
    for s in filtered_rows:
        day = s["date"]
        if day not in by_date:
            by_date[day] = {"online": {}, "offline": []}

        if s["mode"] == "online":
            key = s["link"] or "___no_link___"
            by_date[day]["online"].setdefault(key, []).append(s)
        else:
            by_date[day]["offline"].append(s)

    # Красиво отсортируем даты по возрастанию
    def _date_key(d: str):
        try:
            y, m, dd = map(int, d.split("-"))
            return (y, m, dd)
        except Exception:
            return (9999, 12, 31)

    sorted_days = sorted(by_date.keys(), key=_date_key)

    # Пытаемся поставить русскую локаль для названия дня недели (не обязательно)
    try:
        locale.setlocale(locale.LC_TIME, "ru_RU.UTF-8")
    except Exception:
        pass

    out: list[str] = []
    for day in sorted_days:
        # Заголовок дня, напр. "📅 20.08.2025 (ср)"
        try:
            y, m, d = map(int, day.split("-"))
            dt = datetime(y, m, d)
            day_label = dt.strftime("%d.%m.%Y (%a)")
        except Exception:
            day_label = day

        out.append(f"📅 {day_label}")

        # ONLINE секции по ссылкам
        online_groups = by_date[day]["online"]
        if online_groups:
            keys = sorted([k for k in online_groups.keys() if k != "___no_link___"]) + (
                ["___no_link___"] if "___no_link___" in online_groups else []
            )
            for key in keys:
                header = f"🔗 Ссылка: {online_groups[key][0]['link']}" if key != "___no_link___" else "🔗 Ссылка: (не указана)"
                out.append(header)
                for s in online_groups[key]:
                    left = s["cap"] - s["booked"]
                    mark, tail = _status_mark_and_tail(s)
                    names_line = f"\n  Записаны: {', '.join(s['names'])}" if s["names"] else ""
                    out.append(
                        f"{mark} {s['from_']}-{s['to']} • Онлайн\n"
                        f"  мест: {s['cap']}, занято: {s['booked']}, свободно: {left}{tail}{names_line}"
                    )

        # OFFLINE блок
        offline_list = by_date[day]["offline"]
        if offline_list:
            out.append("🏫 Очно")
            for s in offline_list:
                left = s["cap"] - s["booked"]
                mark, tail = _status_mark_and_tail(s)
                show_loc = s["location"] if (s["location"] and s["location"] != "Аудитория по расписанию") else ""
                loc_part = f" • {show_loc}" if show_loc else ""
                names_line = f"\n  Записаны: {', '.join(s['names'])}" if s["names"] else ""
                out.append(
                    f"{mark} {s['from_']}-{s['to']} • Очно{loc_part}\n"
                    f"  мест: {s['cap']}, занято: {s['booked']}, свободно: {left}{tail}{names_line}"
                )

    await message.answer("\n".join(out))
