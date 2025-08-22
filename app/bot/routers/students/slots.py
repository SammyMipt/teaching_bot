from aiogram import Router, F
from aiogram.types import Message
from app.services.slot_service import SlotService
from app.services.booking_service import BookingService
from app.services.users_service import UsersService

router = Router(name="students_slots")

@router.message(F.text == "/slots")
async def free_slots(message: Message, slots: SlotService, bookings: BookingService, users: UsersService):
    df = slots.list_free_with_bookings(bookings)
    if df.empty:
        await message.answer("Свободных слотов нет.")
        return

    def short_name_by_tg(tg_id: int) -> str:
        u = users.get_by_tg(int(tg_id)) or {}
        ln = (u.get("last_name") or "").strip()
        fn = (u.get("first_name") or "").strip()
        if ln or fn:
            init = (fn[:1] + ".") if fn else ""
            return f"{ln} {init}".strip()
        username = u.get("username")
        return f"@{username}" if username else str(tg_id)

    lines = ["Свободные слоты:"]
    for _, r in df.iterrows():
        cap = int(r.get("capacity", 1))
        booked = int(r.get("booked_count", 0))
        left = cap - booked

        # цветовой индикатор
        if left == cap:
            mark = "🟢"
        elif left == 0:
            mark = "🔴"
        else:
            mark = "🟡"

        # тип и «локация»
        mode = r.get("mode", "online")
        link = r.get("meeting_link") or ""
        location = r.get("location") or ("Онлайн" if mode == "online" else "Аудитория по расписанию")
        mode_label = "Онлайн" if mode == "online" else "Очно"

        # кто записан
        booked_line = ""
        try:
            bdf = bookings.list_for_slot(r["slot_id"])
        except AttributeError:
            # на случай, если метод не добавили — обратимся к «сырой» таблице
            bdf = bookings.table.find(slot_id=r["slot_id"])
        if not bdf.empty:
            names = [short_name_by_tg(tg) for tg in bdf["student_tg_id"].tolist()]
            booked_line = "\n  Записаны: " + ", ".join(names)

        # ссылка показываем как и раньше, но аккуратнее
        link_part = f" • 🔗 {link}" if (mode == "online" and link) else ""

        # финальная строка слота
        lines.append(
            f"{mark} [{r['slot_id']}] {r['date']} {r['time_from']}-{r['time_to']} • {mode_label} • {location}{link_part}\n"
            f"  мест: {cap}, занято: {booked}, свободно: {left}"
            f"{booked_line}"
        )

    await message.answer("\n".join(lines))

@router.message(F.text.startswith("/book"))
async def book_cmd(message: Message, slots: SlotService, bookings: BookingService):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /book [slot_id]")
        return
    slot_id = parts[1].strip()

    df = slots.table.find(slot_id=slot_id)
    if df.empty:
        await message.answer("Слот не найден.")
        return

    # Простая проверка (расширить при необходимости)
    capacity = int(df.iloc[0].get("capacity", 1))
    try:
        bdf = bookings.list_for_slot(slot_id)
        current_bookings = len(bdf)
    except AttributeError:
        bdf = bookings.table.find(slot_id=slot_id)
        current_bookings = len(bdf)

    if current_bookings >= capacity:
        await message.answer("В слоте больше нет свободных мест.")
        return

    # Добавляем запись (упрощенно)
    booking_row = {
        "slot_id": slot_id,
        "student_tg_id": message.from_user.id,
        "status": "active",
        "created_at": "2025-08-21T00:00:00Z"  # заглушка
    }
    bookings.table.append_row(booking_row)
    await message.answer(f"✅ Вы записались на слот {slot_id}!")