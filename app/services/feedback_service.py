from __future__ import annotations
import os
from app.repositories.csv_repo import CsvTable
from app.utils.ids import new_id
from app.utils.time import now_iso

FEEDBACK_COLUMNS = ["feedback_id","student_tg_id","text","created_at","category"]

class FeedbackService:
    def __init__(self, data_dir: str):
        self.table = CsvTable(os.path.join(data_dir, "feedback.csv"), FEEDBACK_COLUMNS)

    def add(self, student_tg_id: int, text: str, category: str = "general"):
        row = {
            "feedback_id": new_id("fbk"),
            "student_tg_id": student_tg_id,
            "text": text,
            "created_at": now_iso(),
            "category": category
        }
        self.table.append_row(row)
        return row
