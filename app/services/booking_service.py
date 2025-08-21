from __future__ import annotations
import os
from typing import Optional
from app.repositories.csv_repo import CsvTable
from app.utils.ids import new_id
from app.utils.time import now_iso
import pandas as pd

BOOKING_COLUMNS = ["booking_id","slot_id","student_tg_id","created_at","status"]  # status: active|canceled

class BookingService:
    def __init__(self, data_dir: str):
        self.table = CsvTable(os.path.join(data_dir, "bookings.csv"), BOOKING_COLUMNS)

    def read(self) -> pd.DataFrame:
        return self.table.read()

    def count_for_slot(self, slot_id: str) -> int:
        df = self.read()
        if df.empty:
            return 0
        df = df[(df["slot_id"].astype(str) == str(slot_id)) & (df["status"] == "active")]
        return len(df)

    def list_for_slot(self, slot_id: str):
        """
        Вернёт DataFrame со всеми бронями по слоту.
        Ожидаемые поля: booking_id, slot_id, student_tg_id, created_at ...
        """
        return self.table.find(slot_id=slot_id)

    def has_booking(self, slot_id: str, student_tg_id: int) -> bool:
        df = self.read()
        if df.empty:
            return False
        df = df[(df["slot_id"].astype(str) == str(slot_id)) &
                (df["student_tg_id"].astype(str) == str(student_tg_id)) &
                (df["status"] == "active")]
        return len(df) > 0

    def create(self, slot_id: str, student_tg_id: int) -> dict:
        row = {
            "booking_id": new_id("bkg"),
            "slot_id": slot_id,
            "student_tg_id": student_tg_id,
            "created_at": now_iso(),
            "status": "active",
        }
        self.table.append_row(row)
        return row

    def cancel(self, booking_id: str):
        df = self.read()
        if df.empty:
            return
        mask = df["booking_id"].astype(str) == str(booking_id)
        if mask.any():
            df.loc[mask, "status"] = "canceled"
            self.table.write(df)
