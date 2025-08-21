from __future__ import annotations
import os
from typing import Optional
from app.repositories.csv_repo import CsvTable

TA_PREFS_COLUMNS = ["ta_id","last_meeting_link","last_location"]

DEFAULT_LOCATION = "Аудитория по расписанию"

class TaPrefsService:
    def __init__(self, data_dir: str):
        self.table = CsvTable(os.path.join(data_dir, "ta_prefs.csv"), TA_PREFS_COLUMNS)

    def get(self, ta_id: str) -> dict:
        ta_id = str(ta_id).strip()
        row = self.table.find(ta_id=ta_id)
        if len(row):
            return row.iloc[0].to_dict()
        return {"ta_id": ta_id, "last_meeting_link": "", "last_location": DEFAULT_LOCATION}

    def set_last_link(self, ta_id: str, link: str):
        ta_id = str(ta_id).strip()
        cur = self.get(ta_id)
        cur["last_meeting_link"] = (link or "").strip()
        self.table.upsert(key_cols=["ta_id"], row=cur)

    def set_last_location(self, ta_id: str, location: str):
        ta_id = str(ta_id).strip()
        cur = self.get(ta_id)
        cur["last_location"] = (location or "").strip() or DEFAULT_LOCATION
        self.table.upsert(key_cols=["ta_id"], row=cur)
