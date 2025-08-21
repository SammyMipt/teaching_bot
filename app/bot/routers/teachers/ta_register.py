from __future__ import annotations
from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from app.services.ta_requests_service import TaRequestsService
from app.services.audit_service import AuditService

router = Router(name="teachers_ta_register")

class TaRegFSM(StatesGroup):
    waiting_name = State()

@router.message(F.text.startswith("/register_ta"))
async def register_ta(message: Message, state: FSMContext,
                      ta_requests: TaRequestsService, audit: AuditService, ta_invite_code: str | None):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /register_ta [invite_code]")
        return
    code = parts[1].strip()
    if not ta_invite_code or code != ta_invite_code:
        audit.log(actor_tg_id=message.from_user.id, action="ta_register_bad_code",
                  target=str(message.from_user.id), meta={"code": code})
        await message.answer("Код неверный. Обратитесь к владельцу курса.")
        return
    await state.set_state(TaRegFSM.waiting_name)
    await message.answer("Код принят. Введите вашу Фамилию и Имя (через пробел).")

@router.message(TaRegFSM.waiting_name, F.text)
async def ta_save_name(message: Message, state: FSMContext,
                       ta_requests: TaRequestsService, audit: AuditService):
    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.answer("Пожалуйста, укажите Фамилию и Имя через пробел.")
        return
    last_name = parts[0]
    first_name = " ".join(parts[1:])
    ta_requests.create_pending(message.from_user.id, first_name=first_name, last_name=last_name)
    audit.log(actor_tg_id=message.from_user.id, action="ta_register_pending",
              target=str(message.from_user.id), meta={"first_name": first_name, "last_name": last_name})
    await state.clear()
    await message.answer("Заявка принята. Ожидайте подтверждения владельцем курса.")