from __future__ import annotations
import asyncio, logging, os
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import load_config
from app.logger import setup_logging

# Services
from app.services.roster_service import RosterService
from app.services.task_service import TaskService
from app.services.storage_service import build_storage
from app.services.submission_service import SubmissionService
from app.services.grade_service import GradeService
from app.services.slot_service import SlotService
from app.services.feedback_service import FeedbackService
from app.services.audit_service import AuditService
from app.services.ta_requests_service import TaRequestsService
from app.services.users_service import UsersService
from app.services.ta_prefs_service import TaPrefsService
from app.services.booking_service import BookingService
from app.services.assignments_service import AssignmentsService

# Middlewares
from app.bot.middlewares.actor_middleware import ActorMiddleware
from app.bot.middlewares.role_middleware import RoleMiddleware

# Routers
from app.bot.routers.common import router as common_router
from app.bot.routers.students import router as students_router
from app.bot.routers.teachers import router as teachers_router
from app.bot.routers.owner import router as owner_router

async def main() -> None:
    cfg = load_config()
    setup_logging(cfg.log_level)
    log = logging.getLogger("main")
    os.makedirs(cfg.data_dir, exist_ok=True)

    bot = Bot(token=cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    # Services
    roster = RosterService(cfg.data_dir)
    tasks = TaskService(cfg.data_dir)
    storage = build_storage(cfg.storage_kind, cfg.data_dir, cfg.yadisk_token)
    submissions = SubmissionService(cfg.data_dir, storage)
    grades = GradeService(cfg.data_dir)
    slots = SlotService(cfg.data_dir)
    feedback = FeedbackService(cfg.data_dir)
    audit = AuditService(cfg.data_dir)
    ta_requests = TaRequestsService(cfg.data_dir)
    users = UsersService(cfg.data_dir)
    ta_prefs = TaPrefsService(cfg.data_dir)
    bookings = BookingService(cfg.data_dir)
    assignments = AssignmentsService(cfg.data_dir)

    # Bootstrap owner (если в проекте есть ensure_owner)
    try:
        users.ensure_owner(cfg.owner_tg_id)
    except Exception:
        pass
    log.info("Owner TG resolved to: %s", cfg.owner_tg_id or "0 (not set)")

    # Middlewares: сначала Actor, потом Role
    dp.message.middleware(ActorMiddleware())
    dp.callback_query.middleware(ActorMiddleware())

    dp.message.middleware(RoleMiddleware(users, cfg.owner_tg_id))
    dp.callback_query.middleware(RoleMiddleware(users, cfg.owner_tg_id))

    # DI
    dp["roster"] = roster
    dp["tasks"] = tasks
    dp["submissions"] = submissions
    dp["grades"] = grades
    dp["slots"] = slots
    dp["feedback"] = feedback
    dp["audit"] = audit
    dp["ta_requests"] = ta_requests
    dp["users"] = users
    dp["ta_prefs"] = ta_prefs
    dp["bookings"] = bookings
    dp["owner_id"] = cfg.owner_tg_id
    dp["ta_invite_code"] = cfg.ta_invite_code
    dp["assignments"] = assignments


    # Routers
    dp.include_router(common_router)
    dp.include_router(students_router)
    dp.include_router(teachers_router)
    dp.include_router(owner_router)

    me = await bot.get_me()
    log.info("Starting bot as @%s id=%s", me.username, me.id)
    try:
        await dp.start_polling(bot, polling_timeout=60, allowed_updates=["message", "callback_query"])
    finally:
        log.info("Bot stopped")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
