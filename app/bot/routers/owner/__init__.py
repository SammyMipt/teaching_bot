from __future__ import annotations
from aiogram import Router
from .roles import router as roles_router
from .ta_requests import router as ta_requests_router
from .assignments_admin import router as assignments_admin_router
from .weeks_admin import router as weeks_admin_router  # Новый роутер
try:
    from .dev_impersonate import router as dev_impersonate_router
except Exception:
    dev_impersonate_router = None

router = Router(name="owner_root")
router.include_router(roles_router)
router.include_router(ta_requests_router)
router.include_router(assignments_admin_router)
router.include_router(weeks_admin_router)  # Подключаем управление неделями
if dev_impersonate_router:
    router.include_router(dev_impersonate_router)