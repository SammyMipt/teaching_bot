from __future__ import annotations
import os, logging
from app.repositories.csv_repo import CsvTable
from app.utils.ids import new_id
from app.utils.time import now_iso
from app.integrations.storage.base import Storage

SUBMISSION_COLUMNS = ["submission_id","task_id","student_code","tg_id","submitted_at","file_path","comment"]

log = logging.getLogger(__name__)

class SubmissionService:
    def __init__(self, data_dir: str, storage: Storage):
        self.table = CsvTable(os.path.join(data_dir, "submissions.csv"), SUBMISSION_COLUMNS)
        self.storage = storage

    async def save_submission(self, tg_id: int, student_code: str, task_id: str, file_name: str, file_bytes: bytes, comment: str = ""):
        rel_path = os.path.join("submissions", student_code or str(tg_id), task_id, file_name)
        saved_path = await self.storage.save_bytes(rel_path, file_bytes)
        row = {
            "submission_id": new_id("sub"),
            "task_id": task_id,
            "student_code": student_code,
            "tg_id": tg_id,
            "submitted_at": now_iso(),
            "file_path": saved_path,
            "comment": comment,
        }
        log.info("Submission saved", extra=row)
        self.table.append_row(row)
        return row
