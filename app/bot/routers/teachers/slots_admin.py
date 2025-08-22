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
    - новые статусы с правильными цветами
    - скрываем отменённые слоты
    - список фамилий записавшихся
    """
    if not ensure_ta(role):
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

    DEFAULT_LOCATION = "Аудитория по расписанию"

    def _is_nan(x) -> bool:
        return isinstance(x, float) and x != x  # NaN

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

    # Группируем по дням и типам
    by_date = {}
    for _, row in df.iterrows():
        d = row.to_dict()
        date = nz_str(d.get("date", ""))
        mode = nz_str(d.get("mode", "online"))
        link = nz_str(d.get("meeting_link", ""))
        location = nz_str(d.get("location", DEFAULT_LOCATION), DEFAULT_LOCATION)

        # Получаем список записанных студентов
        names = []
        try:
            bdf = bookings.list_for_slot(d["slot_id"])
            if not bdf.empty and "student_tg_id" in bdf.columns:
                active_bookings = bdf
                if "status" in bdf.columns:
                    active_bookings = bdf[bdf["status"].str.lower().isin(["active", "confirmed"])]
                for tg in active_bookings["student_tg_id"].dropna().tolist():
                    try:
                        names.append(short_name_by_tg(int(tg)))
                    except Exception:
                        continue
        except Exception:
            pass

        slot_info = {
            "from_": nz_str(d.get("time_from", "")),
            "to": nz_str(d.get("time_to", "")),
            "cap": nz_int(d.get("capacity", 1), 1),
            "booked": nz_int(d.get("booked_count", 0), 0),
            "location": location,
            "link": link,
            "names": names,
            "computed_status": d.get("computed_status", "free_full"),
            "display_color": d.get("display_color", "🟢"),
            "status_description": d.get("status_description", "")
        }

        if date not in by_date:
            by_date[date] = {"online": {}, "offline": []}

        if mode == "online":
            link_key = link if link else "___no_link___"
            if link_key not in by_date[date]["online"]:
                by_date[date]["online"][link_key] = []
            by_date[date]["online"][link_key].append(slot_info)
        else:
            by_date[date]["offline"].append(slot_info)

    # Сортируем дни
    sorted_days = sorted([d for d in by_date.keys() if d])
    if not sorted_days:
        await message.answer("Нет доступных слотов.")
        return

    out = ["📅 Ваши слоты:"]

    for day in sorted_days:
        # Заголовок дня с человеческой датой
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
                    color = s["display_color"]
                    status_desc = s["status_description"]
                    names_line = f"\n  Записаны: {', '.join(s['names'])}" if s["names"] else ""
                    out.append(
                        f"{color} {s['from_']}-{s['to']} • Онлайн\n"
                        f"  мест: {s['cap']}, занято: {s['booked']}, свободно: {left}{status_desc}{names_line}"
                    )

        # OFFLINE блок
        offline_list = by_date[day]["offline"]
        if offline_list:
            out.append("🏫 Очно")
            for s in offline_list:
                left = s["cap"] - s["booked"]
                color = s["display_color"]
                status_desc = s["status_description"]
                show_loc = s["location"] if (s["location"] and s["location"] != DEFAULT_LOCATION) else ""
                loc_part = f" • {show_loc}" if show_loc else ""
                names_line = f"\n  Записаны: {', '.join(s['names'])}" if s["names"] else ""
                out.append(
                    f"{color} {s['from_']}-{s['to']} • Очно{loc_part}\n"
                    f"  мест: {s['cap']}, занято: {s['booked']}, свободно: {left}{status_desc}{names_line}"
                )

    await message.answer("\n".join(out))