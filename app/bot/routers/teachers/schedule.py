from __future__ import annotations
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from datetime import date as _date, timedelta as _td

from app.services.slot_service import SlotService
from app.services.users_service import UsersService
from app.services.ta_prefs_service import TaPrefsService, DEFAULT_LOCATION

router = Router(name="teachers_schedule")

def ensure_ta(role: str) -> bool:
    return role in ("ta", "owner")

class ScheduleFSM(StatesGroup):
    pick_date = State()
    pick_mode = State()
    online_link = State()
    pick_duration = State()
    pick_capacity = State()
    pick_start = State()
    pick_end = State()
    confirm = State()

def dates_kb(days: int = 14):
    kb = InlineKeyboardBuilder()
    today = _date.today()
    for i in range(days):
        d = today + _td(days=i)
        kb.button(text=d.strftime("%d.%m (%a)"), callback_data=f"sch:date:{d.isoformat()}")
    kb.adjust(4)
    return kb.as_markup()

def mode_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="Онлайн", callback_data="sch:mode:online")
    kb.button(text="Очно", callback_data="sch:mode:offline")
    return kb.as_markup()

def duration_kb():
    kb = InlineKeyboardBuilder()
    for m in (15, 20, 30):
        kb.button(text=f"{m} мин", callback_data=f"sch:dur:{m}")
    kb.button(text="Другое…", callback_data="sch:dur:other")
    return kb.as_markup()

def capacity_kb():
    kb = InlineKeyboardBuilder()
    for c in (1, 2, 3):
        kb.button(text=str(c), callback_data=f"sch:cap:{c}")
    kb.button(text="Другое…", callback_data="sch:cap:other")
    return kb.as_markup()

def _valid_hhmm(s: str) -> bool:
    try:
        h, m = s.split(":")
        h = int(h); m = int(m)
        return 0 <= h < 24 and 0 <= m < 60
    except Exception:
        return False

def _confirm_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Создать", callback_data="sch:confirm")
    kb.button(text="❌ Отмена", callback_data="sch:cancel")
    return kb.as_markup()

@router.message(F.text == "/schedule")
async def schedule_start(message: Message, role: str, state: FSMContext):
    if not ensure_ta(role):
        await message.answer("Только для преподавателей.")
        return
    await state.clear()
    await state.set_state(ScheduleFSM.pick_date)
    await message.answer("Выберите дату приёма:", reply_markup=dates_kb())

@router.callback_query(ScheduleFSM.pick_date, F.data.startswith("sch:date:"))
async def schedule_pick_date(cb: CallbackQuery, state: FSMContext):
    chosen = cb.data.split(":")[-1]
    await state.update_data(date=chosen)
    await state.set_state(ScheduleFSM.pick_mode)
    await cb.message.edit_text(f"Дата: {chosen}\nФормат приёма?", reply_markup=mode_kb())
    await cb.answer()

@router.callback_query(ScheduleFSM.pick_mode, F.data.startswith("sch:mode:"))
async def schedule_pick_mode(cb: CallbackQuery, state: FSMContext, ta_prefs: TaPrefsService, users: UsersService):
    mode = cb.data.split(":")[-1]
    await state.update_data(mode=mode)
    if mode == "online":
        default = ta_prefs.get(users.get_ta_id_by_tg(cb.from_user.id)).get("last_meeting_link","")
        hint = f"\n(последняя ссылка: {default})" if default else ""
        await state.set_state(ScheduleFSM.online_link)
        await cb.message.edit_text("Отправьте ссылку для онлайн-приёма." + hint)
    else:
        default_loc = ta_prefs.get(users.get_ta_id_by_tg(cb.from_user.id)).get("last_location") or DEFAULT_LOCATION
        await state.update_data(location=default_loc)
        await state.set_state(ScheduleFSM.pick_duration)
        await cb.message.edit_text(f"Локация: {default_loc}\nВыберите длительность слота:", reply_markup=duration_kb())
    await cb.answer()

@router.message(ScheduleFSM.online_link, F.text)
async def schedule_set_link(message: Message, state: FSMContext, ta_prefs: TaPrefsService, users: UsersService):
    link = message.text.strip()
    ta_prefs.set_last_link(users.get_ta_id_by_tg(message.from_user.id), link)
    await state.update_data(meeting_link=link)
    await state.set_state(ScheduleFSM.pick_duration)
    await message.answer("Ок. Выберите длительность слота:", reply_markup=duration_kb())

@router.callback_query(ScheduleFSM.pick_duration, F.data.startswith("sch:dur:"))
async def schedule_pick_duration(cb: CallbackQuery, state: FSMContext):
    val = cb.data.split(":")[-1]
    if val == "other":
        await cb.message.edit_text("Введите длительность слота в минутах (5..120):")
        await state.set_state(ScheduleFSM.pick_duration)
        await cb.answer()
        return
    dur = int(val)
    await state.update_data(duration_min=dur)
    await state.set_state(ScheduleFSM.pick_capacity)
    await cb.message.edit_text(f"Длительность: {dur} мин.\nВыберите ёмкость слота:", reply_markup=capacity_kb())
    await cb.answer()

@router.message(ScheduleFSM.pick_duration, F.text.regexp(r"^\d{1,3}$"))
async def schedule_set_duration_text(message: Message, state: FSMContext):
    dur = int(message.text.strip())
    if dur < 5 or dur > 120:
        await message.answer("Допустимо 5..120 минут. Повторите ввод.")
        return
    await state.update_data(duration_min=dur)
    await state.set_state(ScheduleFSM.pick_capacity)
    await message.answer(f"Длительность: {dur} мин.\nВыберите ёмкость слота:", reply_markup=capacity_kb())

@router.callback_query(ScheduleFSM.pick_capacity, F.data.startswith("sch:cap:"))
async def schedule_pick_capacity(cb: CallbackQuery, state: FSMContext):
    val = cb.data.split(":")[-1]
    if val == "other":
        await cb.message.edit_text("Введите ёмкость (1..20):")
        await state.set_state(ScheduleFSM.pick_capacity)
        await cb.answer()
        return
    cap = int(val)
    await state.update_data(capacity=cap)
    await state.set_state(ScheduleFSM.pick_start)
    await cb.message.edit_text("Введите время начала окна (HH:MM).")
    await cb.answer()

@router.message(ScheduleFSM.pick_capacity, F.text.regexp(r"^\d{1,2}$"))
async def schedule_set_capacity_text(message: Message, state: FSMContext):
    cap = int(message.text.strip())
    if cap < 1 or cap > 20:
        await message.answer("Допустимо 1..20. Повторите ввод.")
        return
    await state.update_data(capacity=cap)
    await state.set_state(ScheduleFSM.pick_start)
    await message.answer("Введите время начала окна (HH:MM).")

@router.message(ScheduleFSM.pick_start, F.text)
async def schedule_set_start(message: Message, state: FSMContext):
    t = message.text.strip()
    try:
        h, m = map(int, t.split(":"))
        assert 0 <= h < 24 and 0 <= m < 60
    except Exception:
        await message.answer("Неверный формат. Введите HH:MM (например, 09:30).")
        return
    await state.update_data(start_time=t)
    await state.set_state(ScheduleFSM.pick_end)
    await message.answer("Введите время окончания окна (HH:MM). (Ограничение: не более 6 часов от начала)")

@router.message(ScheduleFSM.pick_end, F.text)
async def schedule_set_end(message: Message, state: FSMContext, ta_prefs: TaPrefsService, users: UsersService):
    t = message.text.strip()
    try:
        h, m = map(int, t.split(":"))
        assert 0 <= h < 24 and 0 <= m < 60
    except Exception:
        await message.answer("Неверный формат. Введите HH:MM.")
        return
    data = await state.get_data()
    await state.update_data(end_time=t)

    mode = data.get("mode")
    date = data.get("date")
    link = data.get("meeting_link","")
    loc  = data.get("location") or (ta_prefs.get(users.get_ta_id_by_tg(message.from_user.id)).get("last_location") or DEFAULT_LOCATION)
    dur  = int(data.get("duration_min"))
    cap  = int(data.get("capacity"))
    start= data.get("start_time")
    end  = t

    lines = [
        "Подтвердите создание расписания:",
        f"Дата: {date}",
        f"Формат: {'Онлайн' if mode=='online' else 'Очно'}",
        f"Локация: {loc}" if mode=='offline' else f"Ссылка: {link}",
        f"Длительность слота: {dur} мин",
        f"Ёмкость слота: {cap}",
        f"Окно: {start} — {end}",
        "Лимиты: слот ≤ 120 мин, окно ≤ 6 часов, емкость ≤ 20.",
    ]
    await state.set_state(ScheduleFSM.confirm)
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Создать", callback_data="sch:confirm")
    kb.button(text="❌ Отмена", callback_data="sch:cancel")
    await message.answer("\n".join(lines), reply_markup=kb.as_markup())

@router.callback_query(ScheduleFSM.confirm, F.data.in_(["sch:confirm","sch:cancel"]))
async def schedule_confirm(cb: CallbackQuery,state: FSMContext,slots: SlotService,ta_prefs: TaPrefsService,users: UsersService):
    ta_id = users.get_ta_id_by_tg(cb.from_user.id)    # owner тоже ок (id=TA-00)
    if not ta_id:
        await state.clear()
        await cb.message.edit_text("Ошибка: у вашего аккаунта нет внутреннего TA-ID (users.id). Обратитесь к owner.")
        await cb.answer()
        return

    data = await state.get_data()
    res = slots.add_window(
        ta_id=ta_id,
        date=data["date"],
        start_time=data["start_time"],
        end_time=data["end_time"],
        duration_min=int(data["duration_min"]),
        capacity=int(data["capacity"]),
        mode=data["mode"],
        location=(data.get("location") or ta_prefs.get(ta_id).get("last_location") or "Аудитория по расписанию"),
        meeting_link=data.get("meeting_link",""),
    )
    await state.clear()
    if not res.get("ok"):
        await cb.message.edit_text(f"Ошибка: {res.get('error')}")
    else:
        created = len(res.get("created", []))
        skipped = res.get("skipped", [])
        text = f"Создано слотов: {created}."
        if skipped:
            text += f"\nПропущено (конфликты): {len(skipped)} → {', '.join(skipped[:6])}{'…' if len(skipped)>6 else ''}"
        await cb.message.edit_text(text)
    await cb.answer()