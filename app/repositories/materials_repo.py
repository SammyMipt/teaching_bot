from __future__ import annotations
import os
from typing import Optional
from app.repositories.csv_repo import CsvTable
from app.utils.time import now_iso

MATERIAL_COLUMNS = [
    "material_id","week","type","visibility","file_ref","link","size_bytes",
    "checksum","state","uploaded_by","created_at","updated_at"
]

class MaterialsRepo:
    def __init__(self, data_dir: str):
        path = os.path.join(data_dir, "materials.csv")
        self.table = CsvTable(path, MATERIAL_COLUMNS)

    def insert(self, row: dict) -> dict:
        self.table.append_row(row)
        return row

    def find_active(self, week: str, mtype: str) -> Optional[dict]:
        df = self.table.find(week=week, type=mtype, state="active")
        if df.empty:
            return None
        return df.to_dict("records")[0]

    def archive(self, material_id: str) -> bool:
        df = self.table.read()
        if df.empty:
            return False
        mask = df["material_id"] == material_id
        if not mask.any():
            return False
        df.loc[mask, "state"] = "archived"
        df.loc[mask, "updated_at"] = now_iso()
        self.table.write(df)
        return True

    def list_active(self, week: str) -> list[dict]:
        df = self.table.find(week=week, state="active")
        return df.to_dict("records") if not df.empty else []

    def history(self, week: str, mtype: str) -> list[dict]:
        df = self.table.find(week=week, type=mtype)
        if df.empty:
            return []
        df = df.sort_values("created_at")
        return df.to_dict("records")

    def get(self, material_id: str) -> Optional[dict]:
        df = self.table.find(material_id=material_id)
        if df.empty:
            return None
        return df.to_dict("records")[0]

    def update_state(self, material_id: str, state: str) -> bool:
        df = self.table.read()
        if df.empty:
            return False
        mask = df["material_id"] == material_id
        if not mask.any():
            return False
        df.loc[mask, "state"] = state
        df.loc[mask, "updated_at"] = now_iso()
        self.table.write(df)
        return True

    def delete(self, material_id: str) -> bool:
        df = self.table.read()
        if df.empty:
            return False
        mask = df["material_id"] == material_id
        if not mask.any():
            return False
        df = df[~mask]
        self.table.write(df)
        return True
