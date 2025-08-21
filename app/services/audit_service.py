from __future__ import annotations
import os, json
from app.repositories.csv_repo import CsvTable
from app.utils.ids import new_id
from app.utils.time import now_iso

AUDIT_COLUMNS = ["event_id","ts","actor_tg_id","action","target","meta_json"]

class AuditService:
    def __init__(self, data_dir: str):
        self.table = CsvTable(os.path.join(data_dir, "audit.csv"), AUDIT_COLUMNS)

    def log(self, actor_tg_id: int, action: str, target: str = "", meta: dict | None = None):
        row = {
            "event_id": new_id("evt"),
            "ts": now_iso(),
            "actor_tg_id": actor_tg_id,
            "action": action,
            "target": target,
            "meta_json": json.dumps(meta or {}, ensure_ascii=False),
        }
        self.table.append_row(row)
        return row
