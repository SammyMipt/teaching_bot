from __future__ import annotations
import os
from app.repositories.csv_repo import CsvTable
from app.utils.ids import new_id
from app.utils.time import now_iso
from datetime import datetime, timedelta
import pandas as pd

SLOT_COLUMNS = [
    "slot_id","ta_id","date","time_from","time_to",
    "mode","location","meeting_link","duration_min","capacity",
    "status","created_at","canceled_by","canceled_at","cancel_reason"
]

class SlotService:
    def __init__(self, data_dir: str):
        self.table = CsvTable(os.path.join(data_dir, "slots.csv"), SLOT_COLUMNS)

    def add_slot(self, ta_id: int, date: str, time_from: str, time_to: str,
             mode: str, location: str, meeting_link: str = "", duration_min: int | None = None,
             capacity: int = 1):
        if not duration_min:
            # посчитать из time_from/time_to
            dt1 = datetime.fromisoformat(f"{date} {time_from}")
            dt2 = datetime.fromisoformat(f"{date} {time_to}")
            duration_min = max(1, int((dt2 - dt1).total_seconds() // 60))

        row = {
            "slot_id": new_id("slt"),
            "ta_id": ta_id,
            "date": date, "time_from": time_from, "time_to": time_to,
            "mode": mode, "location": location,
            "meeting_link": meeting_link,
            "duration_min": int(duration_min),
            "capacity": int(capacity),
            "status": "free",
            "created_at": now_iso(),
            "canceled_by": "", "canceled_at": "", "cancel_reason": ""
        }
        self.table.append_row(row)
        return row


    def list_free_with_bookings(self, bookings) -> pd.DataFrame:
        """bookings: BookingService"""
        df = self.table.read()
        if df.empty:
            return df
        df = df[df["status"] != "canceled"]
        b = bookings.read()
        if b.empty:
            df["booked_count"] = 0
        else:
            active = b[b["status"] == "active"].groupby("slot_id").size().rename("booked_count")
            df = df.merge(active, how="left", left_on="slot_id", right_index=True)
            df["booked_count"] = df["booked_count"].fillna(0).astype(int)
        df["free_left"] = (df["capacity"].astype(int) - df["booked_count"].astype(int))
        df = df[df["free_left"] > 0]
        return df.sort_values(by=["date","time_from"])


    def list_for_teacher(self, ta_id: int):
        df = self.table.find(ta_id=ta_id)
        return df.sort_values(by=["date","time_from"])

    def book(self, slot_id: str, student_tg_id: int):
        df = self.table.read()
        mask = df["slot_id"].astype(str) == str(slot_id)
        if not mask.any():
            return None
        df.loc[mask, "booked_by"] = str(student_tg_id)
        df.loc[mask, "status"] = "booked"
        self.table.write(df)
        return df.loc[mask].iloc[0].to_dict()

    def _overlaps(self, a_start: str, a_end: str, b_start: str, b_end: str) -> bool:
        return not (a_end <= b_start or b_end <= a_start)

    def _has_conflict(self, ta_id: int, date: str, start: str, end: str) -> bool:
        df = self.table.find(ta_id=ta_id, date=date)
        if df.empty:
            return False
        df = df[df["status"] != "canceled"]
        for _, r in df.iterrows():
            if self._overlaps(start, end, r["time_from"], r["time_to"]):
                return True
        return False
    
    def add_window(
        self, ta_id: int, date: str, start_time: str, end_time: str,
        duration_min: int, capacity: int, mode: str, location: str, meeting_link: str
    ):
        # лимиты: duration<=120, окно<=6 часов, capacity<=20
        if duration_min < 5 or duration_min > 120:
            return {"ok": False, "error": "Неверная длительность (5..120 минут)"}
        dt_start = datetime.fromisoformat(f"{date} {start_time}")
        dt_end   = datetime.fromisoformat(f"{date} {end_time}")
        if dt_end <= dt_start:
            return {"ok": False, "error": "Время окончания должно быть позже начала"}
        if (dt_end - dt_start) > timedelta(hours=6):
            return {"ok": False, "error": "Окно приёма не более 6 часов"}
        if capacity < 1 or capacity > 20:
            return {"ok": False, "error": "Ёмкость 1..20"}

        created, skipped = [], []
        cur = dt_start
        while cur + timedelta(minutes=duration_min) <= dt_end:
            s = cur.strftime("%H:%M")
            e = (cur + timedelta(minutes=duration_min)).strftime("%H:%M")
            if self._has_conflict(ta_id, date, s, e):
                skipped.append(f"{s}-{e}")
            else:
                row = self.add_slot(
                    ta_id=ta_id,
                    date=date, time_from=s, time_to=e,
                    mode=mode, location=location, meeting_link=meeting_link,
                    duration_min=duration_min, capacity=capacity
                )
                created.append(row["slot_id"])
            cur += timedelta(minutes=duration_min)

        return {"ok": True, "created": created, "skipped": skipped}

    def get_by_id(self, slot_id: str):
        """
        Возвращает (ok: bool, row: dict)
        """
        df = self.table.read()
        if "slot_id" not in df.columns or df.empty:
            return False, {}
        row = df.loc[df["slot_id"] == slot_id]
        if row.empty:
            return False, {}
        return True, row.iloc[0].to_dict()

    def _ensure_is_open_column(self, df):
        if "is_open" not in df.columns:
            df["is_open"] = True
        return df


    def _read_df(self):
        """Чтение таблицы с гарантией наличия колонок is_open/status."""
        df = self.table.read()
        if df is None:
            import pandas as pd
            df = pd.DataFrame()
        # создаём недостающие колонки
        if "slot_id" not in df.columns:
            return df  # пусть будет пусто; get_by_id вернёт not ok
        if "is_open" not in df.columns:
            df["is_open"] = True
        if "status" not in df.columns:
            df["status"] = "active"
        return df

    def get_by_id(self, slot_id: str):
        """
        Возвращает (ok: bool, row: dict) по slot_id.
        """
        df = self._read_df()
        if df.empty or "slot_id" not in df.columns:
            return False, {}
        row = df.loc[df["slot_id"] == slot_id]
        if row.empty:
            return False, {}
        return True, row.iloc[0].to_dict()

    def set_open(self, slot_id: str, is_open: bool) -> bool:
        """
        Переключает доступность записи (is_open).
        """
        df = self._read_df()
        if df.empty or "slot_id" not in df.columns:
            return False
        mask = df["slot_id"] == slot_id
        if not mask.any():
            return False
        df.loc[mask, "is_open"] = bool(is_open)
        self.table.write(df)
        return True

    def cancel_slot(self, slot_id: str) -> bool:
        """
        Помечает слот отменённым (status='canceled').
        """
        df = self._read_df()
        if df.empty or "slot_id" not in df.columns:
            return False
        mask = df["slot_id"] == slot_id
        if not mask.any():
            return False
        df.loc[mask, "status"] = "canceled"
        # по желанию сразу закрыть запись
        if "is_open" in df.columns:
            df.loc[mask, "is_open"] = False
        self.table.write(df)
        return True

