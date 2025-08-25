from __future__ import annotations
from app.services.audit_service import AuditService

def log_event(audit: AuditService, actor_id: int, event: str, payload: dict | None = None, target: str = ""):
    return audit.log(actor_tg_id=actor_id, action=event, target=target, meta=payload or {})
