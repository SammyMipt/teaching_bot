from __future__ import annotations

from typing import Any, Dict, List, Optional
import re

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.services.roster_service import RosterService
from app.services.users_service import UsersService
from app.services.audit_service import AuditService

router = Router(name="students_registration")

# ──────────────────────────────────────────────────────────────────────────────
# FSM
# ──────────────────────────────────────────────────────────────────────────────

class StudentRegFSM(StatesGroup):
    waiting_email = State()
    waiting_pick = State()
    waiting_confirm = State()


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _norm(s: Any) -> str:
    if s is None:
        return ""
    return str(s).strip().lower()

def _choose_col(cols: List[str], candidates: List[str]) -> Optional[str]:
    """
    Find a column among `cols` matching any of `candidates` (case-insensitive,
    ignoring spaces, dashes, dots and underscores). Also allows substring match.
    """
    def canon(x: str) -> str:
        x = x.lower()
        x = re.sub(r"[\s._-]+", "", x)
        return x

    ccols = [(c, canon(c)) for c in cols]
    wants = [(w, canon(w)) for w in candidates]
    # exact canonical match
    for orig, c in ccols:
        for _, w in wants:
            if c == w:
                return orig
    # substring canonical match
    for orig, c in ccols:
        for _, w in wants:
            if w in c or c in w:
                return orig
    return None

def _find_email_rows(roster: RosterService, email: str):
    """Return (df, col_email) rows where any email-like column equals normalized email."""
    df = roster.table.read()
    if df is None or df.empty:
        return None, None
    cols = list(df.columns)
    email_col = _choose_col(cols, ["external_email", "email", "e-mail", "mail", "student_email"])
    if not email_col:
        return None, None
    # normalize column values
    norm_vals = df[email_col].apply(_norm)
    mask = norm_vals == _norm(email)
    hits = df[mask]
    return hits, email_col

def _pick_name(row: Dict[str, Any]) -> Dict[str, str]:
    # try ru first, then en, then generic
    f = row.get("first_name_ru") or row.get("first_name") or row.get("first_name_en") or ""
    l = row.get("last_name_ru") or row.get("last_name") or row.get("last_name_en") or ""
    # try to fallback via fuzzy keys
    if not f:
        for k in row.keys():
            if "first" in k.lower() and "name" in k.lower():
                f = row.get(k) or f
    if not l:
        for k in row.keys():
            if "last" in k.lower() and "name" in k.lower():
                l = row.get(k) or l
    return {"first_name": str(f or "").strip(), "last_name": str(l or "").strip()}

def _pick_group(row: Dict[str, Any]) -> str:
    for key in row.keys():
        kl = key.lower()
        if "group" in kl or "группа" in kl:
            return str(row.get(key) or "").strip()
    return "—"

def _get_student_code(row: Dict[str, Any]) -> str:
    # common variants
    for key in row.keys():
        if "student_code" in key.lower() or "student id" in key.lower() or "code" in key.lower():
            v = str(row.get(key) or "").strip()
            if v:
                return v
    return ""


# ──────────────────────────────────────────────────────────────────────────────
# Cancel handlers (work in any state)
# ──────────────────────────────────────────────────────────────────────────────

@router.message(StateFilter(StudentRegFSM.waiting_email, StudentRegFSM.waiting_pick, StudentRegFSM.waiting_confirm), F.text.casefold() == "/cancel")
@router.message(StateFilter(StudentRegFSM.waiting_email, StudentRegFSM.waiting_pick, StudentRegFSM.waiting_confirm), F.text.casefold() == "cancel")
async def reg_cancel_message(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено. Можно начать заново через /register.")

@router.callback_query(StateFilter(StudentRegFSM.waiting_pick, StudentRegFSM.waiting_confirm), F.data == "reg:cancel")
async def reg_cancel_callback(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Отменено.")
    await cb.answer()


# ──────────────────────────────────────────────────────────────────────────────
# Flow
# ──────────────────────────────────────────────────────────────────────────────

@router.message(F.text == "/register")
async def register_start(message: Message, actor_tg_id: int, users: UsersService, roster: RosterService, state: FSMContext):
    # If already registered as student — short-circuit
    row = users.get_by_tg(actor_tg_id)
    if (row or {}).get("role") == "student":
        await message.answer("Вы уже зарегистрированы как студент.")
        return
    await state.clear()
    await state.set_state(StudentRegFSM.waiting_email)
    await message.answer("Укажите ваш учебный email (как в ростере). Для отмены: /cancel")

@router.message(StudentRegFSM.waiting_email, F.text.len() > 3)
async def register_email(message: Message, state: FSMContext, roster: RosterService):
    email = message.text.strip()
    hits, email_col = _find_email_rows(roster, email)
    if hits is None or email_col is None:
        await message.answer("Не нашёл колонку email в ростере. Сообщите преподавателю.")
        return
    if len(hits) == 0:
        await message.answer("Не нашёл такой email в ростере. Проверьте и отправьте снова, либо /cancel.")
        return
    if len(hits) > 1:
        # ask to pick by student_code
        kb = InlineKeyboardBuilder()
        lines = ["Найдено несколько записей, выберите вашу:"]
        for _, r in hits.iterrows():
            d = r.to_dict()
            sc = _get_student_code(d) or "—"
            name = _pick_name(d)
            fio = f"{name['last_name']} {name['first_name']}".strip() or "—"
            kb.button(text=f"{fio} ({sc})", callback_data=f"reg:pick:{sc}")
        kb.button(text="❌ Отмена", callback_data="reg:cancel")
        await state.update_data(email=email, candidates=hits.to_dict(orient="records"))
        await state.set_state(StudentRegFSM.waiting_pick)
        await message.answer("\n".join(lines), reply_markup=kb.as_markup())
        return

    # single hit
    d = hits.iloc[0].to_dict()
    await state.update_data(email=email, candidate=d)
    name = _pick_name(d)
    group = _pick_group(d)
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подтвердить", callback_data="reg:ok")
    kb.button(text="❌ Отмена", callback_data="reg:cancel")
    fio = f"{name['last_name']} {name['first_name']}".strip() or "—"
    await state.set_state(StudentRegFSM.waiting_confirm)
    await message.answer(f"Нашёл запись в ростере: {fio}\nГруппа: {group}\nПодтвердить привязку?", reply_markup=kb.as_markup())

@router.callback_query(StudentRegFSM.waiting_pick, F.data.startswith("reg:pick:"))
async def register_pick(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    candidates = (data or {}).get("candidates") or []
    sc = cb.data.split(":", 2)[2]
    chosen = None
    for d in candidates:
        if _get_student_code(d) == sc:
            chosen = d
            break
    if not chosen:
        await cb.answer("Не удалось выбрать запись.", show_alert=True)
        return
    await state.update_data(candidate=chosen)
    name = _pick_name(chosen)
    group = _pick_group(chosen)
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подтвердить", callback_data="reg:ok")
    kb.button(text="❌ Отмена", callback_data="reg:cancel")
    fio = f"{name['last_name']} {name['first_name']}".strip() or "—"
    await state.set_state(StudentRegFSM.waiting_confirm)
    await cb.message.edit_text(f"Вы выбрали: {fio}\nГруппа: {group}\nПодтвердить привязку?", reply_markup=kb.as_markup())
    await cb.answer()

@router.callback_query(StudentRegFSM.waiting_confirm, F.data == "reg:ok")
async def register_ok(cb: CallbackQuery, actor_tg_id: int, users: UsersService, roster: RosterService, state: FSMContext, audit: AuditService):
    data = await state.get_data()
    cand = (data or {}).get("candidate") or {}
    email = (data or {}).get("email") or ""

    names = _pick_name(cand)
    student_code = _get_student_code(cand)

    # Upsert student into users.csv
    linked = users.register_student(
        tg_id=actor_tg_id,
        email=email,
        student_code=student_code,
        first_name=names["first_name"],
        last_name=names["last_name"],
        username=cb.from_user.username or ""
    )
    if not linked:
        audit.log(actor_tg_id=cb.from_user.id, action="student_register_already_linked", target=email, meta=cand)
        await state.clear()
        await cb.message.edit_text("Эта запись уже привязана к другому аккаунту. Обратитесь к преподавателю.")
        await cb.answer()
        return

    # Optional: mark in roster (if service supports it)
    try:
        if hasattr(roster, "link_student_account"):
            roster.link_student_account(
                tg_id=actor_tg_id,
                email=email,
                student_code=student_code,
                first_name=names["first_name"],
                last_name=names["last_name"],
                username=cb.from_user.username or ""
            )
    except Exception:
        pass

    audit.log(actor_tg_id=cb.from_user.id, action="student_register_success", target=email, meta=linked)
    await state.clear()
    fio = f"{names['last_name']} {names['first_name']}".strip() or "—"
    await cb.message.edit_text(f"Готово! Привязано к: {fio}. Ваша роль — student.")
    await cb.answer()
