from __future__ import annotations
import os
from typing import Optional
from app.repositories.csv_repo import CsvTable

ROSTER_COLUMNS = [
    "student_code","external_email","last_name_ru","first_name_ru","middle_name_ru",
    "last_name_en","first_name_en","middle_name_en","group","tg_id","role"
]

class RosterService:
    def __init__(self, data_dir: str):
        self.table = CsvTable(os.path.join(data_dir, "roster.csv"), ROSTER_COLUMNS)

    def get_by_tg(self, tg_id: int) -> Optional[dict]:
        df = self.table.find(tg_id=tg_id)
        return df.iloc[0].to_dict() if len(df) else None

    def get_by_email(self, email: str) -> Optional[dict]:
        df = self.table.find(external_email=email.strip())
        return df.iloc[0].to_dict() if len(df) else None

    def get_role(self, tg_id: int) -> str:
        row = self.get_by_tg(tg_id)
        return str(row.get("role", "unknown")) if row else "unknown"

    def link_student_by_email(self, tg_id: int, email: str) -> dict | None:
        """
        Найти запись по email и привязать tg_id + роль=student, если tg_id пуст.
        Если запись не найдена или tg_id уже занят — вернуть None.
        """
        row = self.get_by_email(email)
        if not row:
            return None
        if str(row.get("tg_id") or "").strip():
            # Уже привязано — запрещаем
            return None
        row["tg_id"] = tg_id
        row["role"] = "student"
        # upsert по student_code (он уникальный в твоей выгрузке)
        self.table.upsert(key_cols=["student_code"], row=row)
        return row

    def set_role(self, tg_id: int, role: str):
        self.table.upsert(key_cols=["tg_id"], row={"tg_id": tg_id, "role": role})

    def ensure_row_for_ta(self, tg_id: int, first_name: str = "", last_name: str = ""):
        """
        Чтобы TA тоже были видны в одной таблице, создаём (или апдейтим) строку с tg_id и role=ta.
        student_code/email могут быть пустыми.
        """
        self.table.upsert(
            key_cols=["tg_id"],
            row={"tg_id": tg_id, "role": "ta", "first_name_ru": first_name, "last_name_ru": last_name}
        )
