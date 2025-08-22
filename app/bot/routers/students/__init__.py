from aiogram import Router
from .registration import router as registration_router
from .submissions import router as submissions_router
from .grades import router as grades_router
from .slots import router as slots_router
from .feedback import router as feedback_router
from .week_booking import router as week_booking_router
from .week_master import router as week_master_router  # Новый мастер

router = Router(name="students_root")
router.include_router(registration_router)
router.include_router(submissions_router)
router.include_router(grades_router)
router.include_router(slots_router)
router.include_router(feedback_router)
router.include_router(week_booking_router)
router.include_router(week_master_router)  # Подключаем новый мастер