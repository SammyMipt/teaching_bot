from __future__ import annotations
import os
from typing import Any
from app.repositories.materials_repo import MaterialsRepo
from app.integrations.storage.base import Storage
from app.utils.checksums import sha256_bytes
from app.utils.ids import new_id
from app.utils.time import now_iso
from app.utils.logs import log_event
from app.services.audit_service import AuditService

MAX_SIZE_BYTES = 100 * 1024 * 1024

class MaterialsService:
    def __init__(self, repo: MaterialsRepo, storage: Storage, audit: AuditService, size_limit: int = MAX_SIZE_BYTES):
        self.repo = repo
        self.storage = storage
        self.audit = audit
        self.size_limit = size_limit

    async def upload_material(self, week: str, mtype: str, source: Any, actor_id: int):
        visibility = "teacher" if mtype == "teacher" else "student"
        now = now_iso()
        if isinstance(source, dict) and source.get("link"):
            link = source["link"]
            active = self.repo.find_active(week, mtype)
            if active and active.get("link") == link:
                log_event(self.audit, actor_id, "OWNER_MATERIAL_UPLOAD", {"material_id": active["material_id"], "idempotent": True})
                return active
            if active:
                self.repo.archive(active["material_id"])
            row = {
                "material_id": new_id("mat"),
                "week": week,
                "type": mtype,
                "visibility": visibility,
                "file_ref": "",
                "link": link,
                "size_bytes": 0,
                "checksum": "",
                "state": "active",
                "uploaded_by": actor_id,
                "created_at": now,
                "updated_at": now,
            }
            self.repo.insert(row)
            log_event(self.audit, actor_id, "OWNER_MATERIAL_UPLOAD", {"material_id": row["material_id"]})
            return row
        else:
            data = source if isinstance(source, bytes) else open(source, "rb").read()
            size = len(data)
            if size > self.size_limit:
                raise ValueError("E_SIZE_LIMIT")
            checksum = sha256_bytes(data)
            active = self.repo.find_active(week, mtype)
            if active and active.get("checksum") == checksum:
                log_event(self.audit, actor_id, "OWNER_MATERIAL_UPLOAD", {"material_id": active["material_id"], "idempotent": True})
                return active
            if active:
                self.repo.archive(active["material_id"])
            material_id = new_id("mat")
            path = os.path.join(week, f"{material_id}")
            try:
                file_ref = await self.storage.save_bytes(path, data)
            except Exception as e:
                raise IOError("E_STORAGE_IO") from e
            row = {
                "material_id": material_id,
                "week": week,
                "type": mtype,
                "visibility": visibility,
                "file_ref": file_ref,
                "link": "",
                "size_bytes": size,
                "checksum": checksum,
                "state": "active",
                "uploaded_by": actor_id,
                "created_at": now,
                "updated_at": now,
            }
            self.repo.insert(row)
            log_event(self.audit, actor_id, "OWNER_MATERIAL_UPLOAD", {"material_id": material_id})
            return row

    def list_active(self, week: str) -> list[dict]:
        return self.repo.list_active(week)

    def history(self, week: str, mtype: str) -> list[dict]:
        return self.repo.history(week, mtype)

    def download(self, material_id: str):
        rec = self.repo.get(material_id)
        if not rec:
            raise ValueError("E_NOT_FOUND")
        if rec.get("link"):
            return {"link": rec["link"]}
        if rec.get("file_ref") and os.path.exists(rec["file_ref"]):
            with open(rec["file_ref"], "rb") as f:
                return f.read()
        raise ValueError("E_NOT_FOUND")

    def soft_delete(self, material_id: str, actor_id: int):
        rec = self.repo.get(material_id)
        if not rec:
            raise ValueError("E_NOT_FOUND")
        if rec["state"] != "active":
            raise ValueError("E_STATE_INVALID")
        self.repo.update_state(material_id, "archived")
        log_event(self.audit, actor_id, "OWNER_MATERIAL_SOFT_DELETE", {"material_id": material_id})

    def hard_delete(self, material_id: str, actor_id: int):
        rec = self.repo.get(material_id)
        if not rec:
            raise ValueError("E_NOT_FOUND")
        if rec["state"] != "archived":
            raise ValueError("E_STATE_INVALID")
        self.repo.delete(material_id)
        log_event(self.audit, actor_id, "OWNER_MATERIAL_HARD_DELETE", {"material_id": material_id})
