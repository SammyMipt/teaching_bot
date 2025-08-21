from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from app.services.ta_requests_service import TaRequestsService
from app.services.audit_service import AuditService
from app.services.users_service import UsersService

router = Router(name="owner_ta_requests")

def ta_req_kb(tg_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Approve", callback_data=f"ta:approve:{tg_id}")
    kb.button(text="❌ Deny", callback_data=f"ta:deny:{tg_id}")
    return kb.as_markup()

@router.message(F.text == "/ta_pending")
async def ta_pending(message: Message, owner_id: int, ta_requests: TaRequestsService):
    if message.from_user.id != owner_id:
        await message.answer("Только для владельца курса.")
        return

    df = ta_requests.list_pending()
    if df.empty:
        await message.answer("Нет ожидающих заявок.")
        return

    lines = ["Ожидают подтверждения:"]
    for _, r in df.iterrows():
        tg_id = int(r["tg_id"])
        req_id = r["req_id"]
        first_name = r.get("first_name", "") if isinstance(r, dict) else r["first_name"]
        last_name = r.get("last_name", "") if isinstance(r, dict) else r["last_name"]
        fio = f"{last_name} {first_name}".strip() or "(имя не указано)"
        lines.append(f"- {fio} | tg_id={tg_id} | req_id={req_id}")
    await message.answer("\n".join(lines))

    # Карточки
    for _, r in df.iterrows():
        tg_id = int(r["tg_id"])
        req_id = r["req_id"]
        first_name = r.get("first_name", "") if isinstance(r, dict) else r["first_name"]
        last_name = r.get("last_name", "") if isinstance(r, dict) else r["last_name"]
        fio = f"{last_name} {first_name}".strip() or "(имя не указано)"
        text = f"Заявка #{req_id}\nКандидат на TA: {fio}\n tg_id={tg_id}"
        await message.answer(text, reply_markup=ta_req_kb(tg_id))

@router.callback_query(F.data.startswith("ta:approve:"))
async def cb_ta_approve(cb: CallbackQuery, owner_id: int,
                        ta_requests: TaRequestsService, users: UsersService, audit: AuditService):
    if cb.from_user.id != owner_id:
        await cb.answer("Только владелец курса.", show_alert=True)
        return
    try:
        tg_id = int(cb.data.split(":")[-1])
    except Exception:
        await cb.answer("Некорректные данные.", show_alert=True); return
    ta_requests.set_status(tg_id, "approved")
    req = ta_requests.get_by_tg(tg_id)
    first_name = (req or {}).get("first_name", "")
    last_name = (req or {}).get("last_name", "")
    users.upsert_basic(tg_id=tg_id, role="ta", first_name=first_name, last_name=last_name)
    audit.log(actor_tg_id=cb.from_user.id, action="ta_approved", target=str(tg_id),
              meta={"first_name": first_name, "last_name": last_name})
    await cb.message.edit_text(f"✅ TA подтверждён: {last_name} {first_name} (tg_id={tg_id})")
    await cb.answer("Подтверждено")

@router.callback_query(F.data.startswith("ta:deny:"))
async def cb_ta_deny(cb: CallbackQuery, owner_id: int,
                     ta_requests: TaRequestsService, audit: AuditService):
    if cb.from_user.id != owner_id:
        await cb.answer("Только владелец курса.", show_alert=True)
        return
    try:
        tg_id = int(cb.data.split(":")[-1])
    except Exception:
        await cb.answer("Некорректные данные.", show_alert=True); return
    ta_requests.set_status(tg_id, "denied")
    audit.log(actor_tg_id=cb.from_user.id, action="ta_denied", target=str(tg_id))
    await cb.message.edit_text(f"❌ Заявка отклонена (tg_id={tg_id})")
    await cb.answer("Отклонено")