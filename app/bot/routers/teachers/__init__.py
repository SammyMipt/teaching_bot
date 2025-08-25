from aiogram import Router
from .slots_admin import router as slots_admin_router
from .ta_register import router as ta_register_router
from .schedule import router as schedule_router
from .slots_manage import router as slots_manage_router
from .professor_main import router as professor_main_router
from .materials_router import router as materials_router

router = Router(name="teachers_root")

router.include_router(professor_main_router)

router.include_router(materials_router)
router.include_router(ta_register_router)
router.include_router(slots_admin_router)
router.include_router(schedule_router)
router.include_router(slots_manage_router)