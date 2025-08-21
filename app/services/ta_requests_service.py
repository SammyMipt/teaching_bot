from __future__ import annotations
import os
from app.repositories.csv_repo import CsvTable
from app.utils.ids import new_id
from app.utils.time import now_iso

TA_REQ_COLUMNS = ["req_id","tg_id","status","created_at","decided_at","first_name","last_name"]

class TaRequestsService:
    def __init__(self, data_dir: str):
        self.table = CsvTable(os.path.join(data_dir, "ta_requests.csv"), TA_REQ_COLUMNS)

    def create_pending(self, tg_id: int, first_name: str = "", last_name: str = "") -> dict:
        row = {
            "req_id": new_id("tar"),
            "tg_id": tg_id,
            "status": "pending",
            "created_at": now_iso(),
            "decided_at": "",
            "first_name": first_name,
            "last_name": last_name,
        }
        self.table.append_row(row)
        return row

    def set_status(self, tg_id: int, status: str):
        df = self.table.read()
        if df.empty:
            # если нет записи — создадим
            self.create_pending(tg_id)
            df = self.table.read()
        mask = df["tg_id"].astype(str) == str(tg_id)
        if not mask.any():
            # нет — создадим, затем обновим
            self.create_pending(tg_id)
            df = self.table.read()
            mask = df["tg_id"].astype(str) == str(tg_id)
        df.loc[mask, "status"] = status
        df.loc[mask, "decided_at"] = now_iso()
        self.table.write(df)

    def get_status(self, tg_id: int) -> str:
        df = self.table.read()
        mask = df["tg_id"].astype(str) == str(tg_id)
        if not mask.any():
            return "none"
        return df.loc[mask].iloc[0]["status"]

    def get_by_tg(self, tg_id: int) -> dict | None:
        df = self.table.find(tg_id=tg_id)
        return df.iloc[0].to_dict() if len(df) else None

    def list_pending(self):
        df = self.table.find(status="pending")
        return df.sort_values(by=["created_at"])
