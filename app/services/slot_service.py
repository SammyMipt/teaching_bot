from __future__ import annotations
import os
from typing import Optional, Dict, Any
import pandas as pd
from app.repositories.csv_repo import CsvTable
from app.utils.ids import new_id
from app.utils.time import now_iso

SLOTS_COLUMNS = [
    "slot_id", "ta_id", "date", "time_from", "time_to", 
    "mode", "location", "meeting_link", "duration_min", 
    "capacity", "status", "created_at", "canceled_by", 
    "canceled_at", "cancel_reason"
]

class SlotService:
    def __init__(self, data_dir: str):
        self.table = CsvTable(os.path.join(data_dir, "slots.csv"), SLOTS_COLUMNS)

    def _read_df(self) -> pd.DataFrame:
        return self.table.read()

    def add_slot(self, ta_id: str, date: str, time_from: str, time_to: str,
                 mode: str = "online", location: str = "", meeting_link: str = "",
                 duration_min: int = 15, capacity: int = 1) -> dict:
        row = {
            "slot_id": new_id("slt"),
            "ta_id": ta_id,
            "date": date,
            "time_from": time_from,
            "time_to": time_to,
            "mode": mode,
            "location": location,
            "meeting_link": meeting_link,
            "duration_min": duration_min,
            "capacity": capacity,
            "status": "free",
            "created_at": now_iso(),
            "canceled_by": "",
            "canceled_at": "",
            "cancel_reason": ""
        }
        self.table.append_row(row)
        return row

    def list_for_teacher(self, ta_id: str) -> pd.DataFrame:
        df = self._read_df()
        if df.empty or "ta_id" not in df.columns:
            return pd.DataFrame()
        return df[df["ta_id"] == ta_id].copy()

    def list_free_with_bookings(self, bookings_service) -> pd.DataFrame:
        """Возвращает свободные слоты с информацией о бронированиях"""
        df = self._read_df()
        if df.empty:
            return pd.DataFrame()
        
        # Простая фильтрация - показываем не отмененные слоты
        available_df = df[df["status"] != "canceled"].copy()
        if available_df.empty:
            return available_df
            
        # Добавляем информацию о бронированиях
        booking_counts = {}
        for slot_id in available_df["slot_id"]:
            try:
                bookings_df = bookings_service.list_for_slot(slot_id)
                booking_counts[slot_id] = len(bookings_df) if not bookings_df.empty else 0
            except:
                booking_counts[slot_id] = 0
        
        available_df["booked_count"] = available_df["slot_id"].map(booking_counts).fillna(0)
        return available_df

    def get_slot_by_id(self, slot_id: str) -> tuple[bool, dict]:
        """Возвращает (found, slot_dict)"""
        df = self._read_df()
        if df.empty or "slot_id" not in df.columns:
            return False, {}
        row = df.loc[df["slot_id"] == slot_id]
        if row.empty:
            return False, {}
        return True, row.iloc[0].to_dict()

    def set_open(self, slot_id: str, is_open: bool) -> bool:
        """Переключает доступность записи (открыт/закрыт)"""
        df = self._read_df()
        if df.empty or "slot_id" not in df.columns:
            return False
        mask = df["slot_id"] == slot_id
        if not mask.any():
            return False
        
        # Меняем статус между free и closed
        new_status = "free" if is_open else "closed"
        df.loc[mask, "status"] = new_status
        self.table.write(df)
        return True

    def cancel_slot(self, slot_id: str, canceled_by: str = "", reason: str = "") -> bool:
        """Помечает слот отменённым"""
        df = self._read_df()
        if df.empty or "slot_id" not in df.columns:
            return False
        mask = df["slot_id"] == slot_id
        if not mask.any():
            return False
        
        df.loc[mask, "status"] = "canceled"
        df.loc[mask, "canceled_by"] = canceled_by
        df.loc[mask, "canceled_at"] = now_iso()
        df.loc[mask, "cancel_reason"] = reason
        self.table.write(df)
        return True