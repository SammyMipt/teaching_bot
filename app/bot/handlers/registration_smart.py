"""
Умная система регистрации с fuzzy matching и правильным UX
"""
import logging
import time
from typing import List

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from app.bot.auth import resolve_role, effective_user_id, is_impersonating
from app.storage import roster, user_links
from app.storage.users import get_user, upsert_user
from app.storage.pending_registrations import add_pending_registration
from app.storage.roster_matching import find_student_matches, validate_match_quality, MatchResult
from app.core.config import settings

log = logging.getLogger(__name__)
router = Router()

# ---------- FSM состояния ----------
class SmartReg(StatesGroup):
    lastname = State()
    firstname = State()
    group = State()
    email = State()
    code = State()
    confirm_match = State()
    choose_match = State()

# ---------- Клавиатуры ----------
def _kb_confirm_match() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, это я", callback_data="match::confirm"),
         InlineKeyboardButton(text="❌ Нет, не я", callback_data="match::reject")]
    ])

def _kb_choose_matches(matches: List[MatchResult]) -> InlineKeyboardMarkup:
    buttons = []
    for i, match in enumerate(matches[:3]):  # Максимум 3 варианта
        confidence_emoji = "🎯" if match.confidence > 0.9 else "🔍" if match.confidence > 0.8 else "❓"
        text = f"{confidence_emoji} {match.display_name}"
        buttons.append([InlineKeyboardButton(
            text=text,
            callback_data=f"choose::{match.student_code}"
        )])
    
    # Добавляем кнопку "Ни один не подходит"
    buttons.append([InlineKeyboardButton(
        text="❌ Ни один не подходит",
        callback_data="choose::none"
    )])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def _kb_none_found() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📧 Попробовать другой email", callback_data="retry::email"),
         InlineKeyboardButton(text="👥 Обратиться к преподавателю", callback_data="retry::teacher")]
    ])

# ---------- Функции отправки уведомлений owner'у ----------
async def notify_owner_about_problem(
    bot, 
    user_id: int,
    username: str,
    full_name: str,
    group: str,
    email: str,
    reason: str
):
    """Отправляет уведомление owner'у о проблемной регистрации"""
    
    reason_texts = {
        "no_match": "🔍 Не найден в ростере",
        "rejected_all": "❌ Отклонил все варианты",
        "multiple_uncertain": "❓ Слишком много неточных совпадений",
        "email_conflict": "⚠️ Email уже привязан к другому аккаунту"
    }
    
    reason_text = reason_texts.get(reason, reason)
    message = (
        f"🚨 ПРОБЛЕМНАЯ РЕГИСТРАЦИЯ\n\n"
        f"👤 ФИО: {full_name}\n"
        f"🎓 Группа: {group}\n"
        f"📧 Email: {email}\n"
        f"👤 Telegram: @{username} (ID: {user_id})\n"
        f"❗ Проблема: {reason_text}\n\n"
        f"💡 Действия:\n"
        f"1️⃣ Проверьте данные в roster.csv\n"
        f"2️⃣ При необходимости добавьте студента\n"
        f"3️⃣ Используйте /impersonate {user_id} и /register для регистрации\n"
        f"4️⃣ Используйте /resolve_pending {user_id} после решения\n\n"
        f"📋 Список всех проблем: /pending_students"
    )
    
    # Отправляем всем owner'ам
    for owner_id in settings.owner_ids:
        try:
            await bot.send_message(owner_id, message)
        except Exception as e:
            log.error(f"Не удалось отправить уведомление owner'у {owner_id}: {e}")

# ---------- Хендлеры ----------
@router.message(Command("register"))
async def smart_register_start(msg: Message, state: FSMContext):
    # Предупреждение при имперсонации
    if is_impersonating(msg) and msg.from_user.id in settings.owner_ids:
        await msg.answer(
            "⚠️ ВНИМАНИЕ: Включена имперсонация!\n"
            f"Вы регистрируете аккаунт для user_id={effective_user_id(msg)}, НЕ для себя.\n"
            "Если это случайно — отправьте /unimpersonate и запустите /register снова.\n\n"
            "Продолжаем регистрацию..."
        )
    
    uid = effective_user_id(msg)
    if get_user(uid):
        return await msg.answer("Вы уже зарегистрированы. Команда: /whoami")
    
    await state.set_state(SmartReg.lastname)
    await msg.answer(
        "👋 Добро пожаловать! Начинаем регистрацию.\n\n"
        "📝 Введите вашу фамилию:\n"
        "Пример: Иванов"
    )

@router.message(SmartReg.lastname)
async def smart_reg_lastname(msg: Message, state: FSMContext):
    lastname = msg.text.strip()
    if len(lastname) < 2:
        return await msg.answer("Фамилия слишком короткая. Введите фамилию:")
    
    await state.update_data(lastname=lastname)
    await state.set_state(SmartReg.firstname)
    await msg.answer(
        "👤 Введите ваше имя:\n"
        "Пример: Иван"
    )

@router.message(SmartReg.firstname)
async def smart_reg_firstname(msg: Message, state: FSMContext):
    firstname = msg.text.strip()
    if len(firstname) < 2:
        return await msg.answer("Имя слишком короткое. Введите имя:")
    
    await state.update_data(firstname=firstname)
    await state.set_state(SmartReg.group)
    await msg.answer(
        "🎓 Введите вашу группу:\n"
        "Примеры: B1, MFAI-01, М-22"
    )

@router.message(SmartReg.group)
async def smart_reg_group(msg: Message, state: FSMContext):
    group = msg.text.strip()
    if len(group) < 1:
        return await msg.answer("Группа не может быть пустой. Попробуйте ещё раз:")
    
    await state.update_data(group=group)
    await state.set_state(SmartReg.email)
    await msg.answer(
        "📧 Введите ваш email (тот же, что в LMS):\n"
        "Это очень важно для автоматического поиска в системе!"
    )

@router.message(SmartReg.email)
async def smart_reg_email(msg: Message, state: FSMContext):
    email = msg.text.strip()
    if "@" not in email or "." not in email:
        return await msg.answer("Введите корректный email адрес:")
    
    await state.update_data(email=email)
    await state.set_state(SmartReg.code)
    await msg.answer("🔐 Введите код курса или код преподавателя")

@router.message(SmartReg.code)
async def smart_reg_code(msg: Message, state: FSMContext):
    data = await state.get_data()
    uid = effective_user_id(msg)
    code = (msg.text or "").strip()
    
    # Определяем роль и статус по коду
    if uid in settings.owner_ids:
        role, status = "owner", "active"
    elif code == settings.COURSE_CODE:
        role, status = "student", "active"
    elif code == settings.INSTRUCTOR_CODE:
        role, status = "instructor", "pending"
    else:
        await msg.answer("❌ Неверный код. Попробуйте ещё раз или свяжитесь с преподавателем.")
        return

    # Сохраняем роль в state для дальнейшего использования
    await state.update_data(role=role, status=status, code_used=code)

    if role == "student":
        # Для студентов - ищем в ростере
        await msg.answer("🔍 Ищу вас в списке студентов...")
        await process_student_matching(msg, state, data["lastname"], data["firstname"], data["group"], data["email"])
    else:
        # Для преподавателей и owner'ов - сразу регистрируем
        await finalize_registration(msg, state, data, role, status, code, skip_roster=True)

async def process_student_matching(msg: Message, state: FSMContext, lastname: str, firstname: str, group: str, email: str):
    """Обрабатывает поиск студента в ростере"""
    uid = effective_user_id(msg)
    
    # Формируем полное имя для поиска
    full_name = f"{lastname} {firstname}"
    
    # Ищем совпадения
    matches = find_student_matches(full_name, group, email)
    match_status, filtered_matches = validate_match_quality(matches)
    
    if match_status == "exact":
        # Точное совпадение по email
        match = filtered_matches[0]
        await state.update_data(
            selected_student_code=match.student_code,
            selected_external_email=match.external_email,
            selected_display_name=match.display_name
        )
        await state.set_state(SmartReg.confirm_match)
        
        await msg.answer(
            f"🎯 Отлично! Нашёл точное совпадение:\n\n"
            f"👤 {match.display_name}\n"
            f"📧 {match.external_email}\n"
            f"🆔 Код: {match.student_code}\n\n"
            f"Это вы?",
            reply_markup=_kb_confirm_match()
        )
        
    elif match_status == "good":
        # Одно хорошее совпадение
        match = filtered_matches[0]
        await state.update_data(
            selected_student_code=match.student_code,
            selected_external_email=match.external_email,
            selected_display_name=match.display_name
        )
        await state.set_state(SmartReg.confirm_match)
        
        confidence_text = "высокой" if match.confidence > 0.9 else "средней"
        await msg.answer(
            f"🔍 Найдено совпадение с {confidence_text} уверенностью:\n\n"
            f"👤 {match.display_name}\n"
            f"📧 {match.external_email}\n"
            f"🆔 Код: {match.student_code}\n"
            f"📊 Тип поиска: {match.match_type}\n\n"
            f"Это вы?",
            reply_markup=_kb_confirm_match()
        )
        
    elif match_status == "uncertain" and len(filtered_matches) <= 3:
        # Несколько вариантов для выбора
        await state.update_data(available_matches=[{
            "student_code": m.student_code,
            "external_email": m.external_email,
            "display_name": m.display_name
        } for m in filtered_matches])
        await state.set_state(SmartReg.choose_match)
        
        await msg.answer(
            f"🤔 Найдено несколько похожих студентов.\n"
            f"Выберите себя из списка:",
            reply_markup=_kb_choose_matches(filtered_matches)
        )
        
    else:
        # Ничего не нашли или слишком много неточных совпадений
        username = msg.from_user.username or "unknown"
        reason = "no_match" if not matches else "multiple_uncertain"
        
        # Сохраняем черновик
        full_name_for_save = f"{lastname} {firstname}"
        add_pending_registration(uid, username, full_name_for_save, group, email, reason)
        
        # Уведомляем owner'а
        await notify_owner_about_problem(
            msg.bot, uid, username, full_name_for_save, group, email, reason
        )
        
        await state.clear()
        
        if reason == "no_match":
            await msg.answer(
                "😔 К сожалению, не удалось найти вас в списке студентов.\n\n"
                "📋 Возможные причины:\n"
                "• Ваш email отличается от указанного в LMS\n"
                "• Вы ещё не добавлены в систему\n"
                "• Опечатка в фамилии или группе\n\n"
                "📧 Ваши данные отправлены преподавателю для проверки.\n"
                "Вы получите уведомление, когда проблема будет решена.",
                reply_markup=_kb_none_found()
            )
        else:
            await msg.answer(
                "🤷‍♂️ Найдено слишком много неточных совпадений.\n\n"
                "📧 Ваши данные отправлены преподавателю для ручной проверки.\n"
                "Вы получите уведомление, когда проблема будет решена.",
                reply_markup=_kb_none_found()
            )

# ---------- Callback handlers ----------
@router.callback_query(SmartReg.confirm_match, F.data == "match::confirm")
async def confirm_match(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    uid = effective_user_id(callback)
    
    # Завершаем регистрацию с выбранным студентом
    await finalize_registration_with_link(
        callback.message, state, data,
        data["selected_student_code"],
        data["selected_external_email"],
        uid
    )
    await callback.answer()

@router.callback_query(SmartReg.confirm_match, F.data == "match::reject")
async def reject_match(callback: CallbackQuery, state: FSMContext):
    log.info("Обработка отклонения совпадения")
    
    data = await state.get_data()
    uid = effective_user_id(callback)
    username = callback.from_user.username or "unknown"
    
    # Формируем полное имя из отдельных полей
    full_name_for_save = f"{data['lastname']} {data['firstname']}"
    
    log.info(f"Отклонение: uid={uid}, full_name={full_name_for_save}")
    
    # Сохраняем как отклонившего варианты
    add_pending_registration(
        uid, username, full_name_for_save, data["group"], 
        data["email"], "rejected_all"
    )
    
    # Уведомляем owner'а
    await notify_owner_about_problem(
        callback.bot, uid, username, full_name_for_save, 
        data["group"], data["email"], "rejected_all"
    )
    
    await state.clear()
    await callback.message.edit_text(
        "❌ Понятно, предложенный вариант не подходит.\n\n"
        "📧 Ваши данные отправлены преподавателю для ручной проверки.\n"
        "Вы получите уведомление, когда проблема будет решена."
    )
    await callback.answer()

@router.callback_query(SmartReg.choose_match, F.data.startswith("choose::"))
async def choose_match(callback: CallbackQuery, state: FSMContext):
    _, choice = callback.data.split("::", 1)
    
    if choice == "none":
        # Пользователь не выбрал ни один вариант
        data = await state.get_data()
        uid = effective_user_id(callback)
        username = callback.from_user.username or "unknown"
        
        full_name_for_save = f"{data['lastname']} {data['firstname']}"
        add_pending_registration(
            uid, username, full_name_for_save, data["group"],
            data["email"], "rejected_all"
        )
        
        await notify_owner_about_problem(
            callback.bot, uid, username, full_name_for_save,
            data["group"], data["email"], "rejected_all"
        )
        
        await state.clear()
        await callback.message.edit_text(
            "❌ Понятно, ни один вариант не подходит.\n\n"
            "📧 Ваши данные отправлены преподавателю для ручной проверки.\n"
            "Вы получите уведомление, когда проблема будет решена."
        )
        await callback.answer()
        return
    
    # Пользователь выбрал конкретного студента
    data = await state.get_data()
    available_matches = data.get("available_matches", [])
    
    selected_match = None
    for match in available_matches:
        if match["student_code"] == choice:
            selected_match = match
            break
    
    if not selected_match:
        await callback.answer("Ошибка: выбранный вариант не найден")
        return
    
    # Завершаем регистрацию с выбранным студентом
    await finalize_registration_with_link(
        callback.message, state, data,
        selected_match["student_code"],
        selected_match["external_email"],
        effective_user_id(callback)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("retry::"))
async def retry_registration(callback: CallbackQuery, state: FSMContext):
    _, retry_type = callback.data.split("::", 1)
    
    if retry_type == "email":
        await state.set_state(SmartReg.email)
        await callback.message.edit_text(
            "📧 Попробуйте ввести другой email адрес:\n"
            "(возможно, у вас несколько email'ов в системе)"
        )
    elif retry_type == "teacher":
        await state.clear()
        await callback.message.edit_text(
            "👨‍🏫 Свяжитесь с преподавателем для решения проблемы.\n"
            "Ваши данные уже отправлены для проверки."
        )
    
    await callback.answer()

# ---------- Финализация регистрации ----------
async def finalize_registration(
    msg: Message, 
    state: FSMContext, 
    data: dict, 
    role: str, 
    status: str, 
    code_used: str,
    skip_roster: bool = False
):
    """Завершает регистрацию без привязки к ростеру"""
    uid = effective_user_id(msg)
    
    # Создаём запись пользователя
    full_name_for_save = f"{data['lastname']} {data['firstname']}"
    user_rec = {
        "user_id": str(uid),
        "role": role,
        "full_name": full_name_for_save,
        "group": data["group"],
        "email": data["email"],
        "status": status,
        "created_at": str(int(time.time())),
        "code_used": code_used,
    }
    upsert_user(user_rec)
    
    await state.clear()
    
    if role == "student":
        await msg.answer("✅ Регистрация завершена! Вы зарегистрированы как студент.")
    elif role == "instructor":
        await msg.answer("✅ Регистрация как преподаватель отправлена на модерацию. Ожидайте подтверждения.")
    elif role == "owner":
        await msg.answer("✅ Добро пожаловать, владелец курса!")

async def finalize_registration_with_link(
    msg: Message,
    state: FSMContext,
    data: dict,
    student_code: str,
    external_email: str,
    uid: int
):
    """Завершает регистрацию студента с привязкой к ростеру"""
    
    # Создаём запись пользователя
    full_name_for_save = f"{data['lastname']} {data['firstname']}"
    user_rec = {
        "user_id": str(uid),
        "role": data["role"],
        "full_name": full_name_for_save,
        "group": data["group"],
        "email": data["email"],
        "status": data["status"],
        "created_at": str(int(time.time())),
        "code_used": data["code_used"],
    }
    upsert_user(user_rec)
    
    # Пытаемся создать привязку к ростеру
    try:
        user_links.upsert_link(uid, student_code, external_email, linked_by="auto", status="active")
    except ValueError as e:
        # Если email уже привязан к другому пользователю
        log.warning(f"Не удалось привязать {uid} к {student_code}: {e}")
        
        await state.clear()
        await msg.edit_text(
            f"⚠️ Проблема с привязкой!\n\n"
            f"✅ Вы зарегистрированы как студент\n"
            f"❌ Но этот email уже привязан к другому аккаунту\n\n"
            f"📧 Обратитесь к преподавателю для решения проблемы.\n"
            f"Возможно, у вас уже есть другой аккаунт в системе."
        )
        
        # Уведомляем owner'а о конфликте
        username = msg.from_user.username if hasattr(msg, 'from_user') else "unknown"
        await notify_owner_about_problem(
            msg.bot, uid, username, full_name_for_save, 
            data["group"], data["email"], "email_conflict"
        )
        return
    
    await state.clear()
    
    # Получаем данные из ростера для красивого сообщения
    roster_data = roster.get_by_student_code(student_code)
    display_name = "Unknown"
    if roster_data:
        if roster_data.get('last_name_ru') and roster_data.get('first_name_ru'):
            display_name = f"{roster_data['last_name_ru']} {roster_data['first_name_ru']}"
            if roster_data.get('middle_name_ru'):
                display_name += f" {roster_data['middle_name_ru']}"
        else:
            display_name = f"{roster_data.get('last_name_en', '')} {roster_data.get('first_name_en', '')}"
    
    await msg.edit_text(
        f"🎉 Регистрация полностью завершена!\n\n"
        f"✅ Вы успешно зарегистрированы как студент\n"
        f"🔗 Привязка к системе: {display_name} ({student_code})\n"
        f"📧 Email: {external_email}\n\n"
        f"Теперь вы можете использовать все функции бота:\n"
        f"• /submit <неделя> - сдавать задания\n"
        f"• /mygrade <неделя> - смотреть оценки\n"
        f"• /whoami - проверить свой статус"
    )

# ---------- Команды для управления owner'ом ----------
@router.message(Command("pending_students"))
async def pending_students(msg: Message):
    if resolve_role(msg) != "owner":
        return await msg.answer("Только для владельца курса.")
    
    from app.storage.pending_registrations import list_pending_registrations, format_pending_for_display
    
    pending_list = list_pending_registrations()
    formatted = format_pending_for_display(pending_list)
    
    await msg.answer(f"📋 ОЖИДАЮЩИЕ РЕГИСТРАЦИИ ({len(pending_list)}):\n\n{formatted}")

@router.message(Command("resolve_pending"))
async def resolve_pending(msg: Message, command: CommandObject):
    if resolve_role(msg) != "owner":
        return await msg.answer("Только для владельца курса.")
    
    user_id = (command.args or "").strip()
    if not user_id.isdigit():
        return await msg.answer("Использование: /resolve_pending <user_id>")
    
    from app.storage.pending_registrations import resolve_pending_registration
    
    if resolve_pending_registration(int(user_id)):
        await msg.answer(f"✅ Регистрация {user_id} помечена как решённая.")
    else:
        await msg.answer(f"❌ Регистрация {user_id} не найдена.")

@router.message(Command("ignore_pending"))
async def ignore_pending(msg: Message, command: CommandObject):
    if resolve_role(msg) != "owner":
        return await msg.answer("Только для владельца курса.")
    
    user_id = (command.args or "").strip()
    if not user_id.isdigit():
        return await msg.answer("Использование: /ignore_pending <user_id>")
    
    from app.storage.pending_registrations import ignore_pending_registration
    
    if ignore_pending_registration(int(user_id)):
        await msg.answer(f"✅ Регистрация {user_id} помечена как игнорируемая.")
    else:
        await msg.answer(f"❌ Регистрация {user_id} не найдена.")