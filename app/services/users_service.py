from __future__ import annotations
import os
from typing import Optional
import pandas as pd
from app.repositories.csv_repo import CsvTable
from app.utils.time import now_iso

# Строгое соответствие колонкам users.csv (никаких лишних полей)
USERS_COLUMNS = ['tg_id', 'role', 'first_name', 'last_name', 'username', 'email', 'id', 'created_at']

TA_ROLES = ("ta", "owner")  # owner трактуем как TA

class UsersService:
    def __init__(self, data_dir: str):
        self.table = CsvTable(os.path.join(data_dir, "users.csv"), USERS_COLUMNS)

    # ── Queries ────────────────────────────────────────────────────────────────
    def get_by_tg(self, tg_id: int) -> Optional[dict]:
        df = self.table.find(tg_id=tg_id)
        return df.iloc[0].to_dict() if len(df) else None

    def get_by_id(self, entity_id: str) -> Optional[dict]:
        df = self.table.find(id=str(entity_id))
        return df.iloc[0].to_dict() if len(df) else None

    def get_role(self, tg_id: int) -> str:
        row = self.get_by_tg(tg_id)
        return str(row.get("role", "unknown")) if row else "unknown"

    # ── TA helpers ────────────────────────────────────────────────────────────
    def get_ta_id_by_tg(self, tg_id: int) -> Optional[str]:
        """Вернуть внутренний TA id по tg_id (owner тоже считается TA)."""
        row = self.get_by_tg(tg_id)
        if not row:
            return None
        role = str(row.get("role", "")).strip().lower()
        if role not in TA_ROLES:
            return None
        val = str(row.get("id", "")).strip()
        return val or None

    def get_tg_by_ta_id(self, ta_id: str) -> Optional[str]:
        """Вернуть tg_id по внутреннему TA id (owner поддерживается)."""
        df = self.table.find(id=str(ta_id))
        if not len(df):
            return None
        row = df.iloc[0].to_dict()
        role = str(row.get("role", "")).strip().lower()
        if role not in TA_ROLES:
            return None
        tg = str(row.get("tg_id", "")).strip()
        return tg or None

    def get_ta_id_by_code(self, ta_code: str) -> Optional[str]:
        """В текущей схеме ta_code как отдельной колонки нет — используем совпадение по id.
        То есть ta_code == users.id. Поддерживает owner с id 'TA-00'."""
        code = str(ta_code or "").strip()
        if not code:
            return None
        df = self.table.find(id=code)
        if not len(df):
            return None
        row = df.iloc[0].to_dict()
        role = str(row.get("role","")).strip().lower()
        if role not in TA_ROLES:
            return None
        return str(row.get("id","")).strip() or None

    # ── Mutations ─────────────────────────────────────────────────────────────
    def upsert_basic(self, tg_id: int, role: str | None = None,
                     first_name: str = "", last_name: str = "", username: str = "",
                     email: str = "", id: str = "") -> dict:
        existing = self.get_by_tg(tg_id) or {}
        row = {
            "tg_id": tg_id,
            "role": role or existing.get("role", "unknown"),
            "first_name": first_name or existing.get("first_name", ""),
            "last_name": last_name or existing.get("last_name", ""),
            "username": username or existing.get("username", ""),
            "email": email or existing.get("email", ""),
            "id": id or existing.get("id", ""),
            "created_at": existing.get("created_at", now_iso()),
        }
        self.table.upsert("tg_id", row)
        return row

    def register_student(self, tg_id: int, email: str, id: str,
                         first_name: str = "", last_name: str = "", username: str = "") -> dict | None:
        # запрет на привязку одного и того же id к разным tg
        df = self.table.read()
        if not df.empty and "id" in df.columns:
            mask = df["id"].astype(str) == str(id)
            if mask.any():
                owner_tg = df.loc[mask].iloc[0]["tg_id"]
                if str(owner_tg) != str(tg_id):
                    return None
        return self.upsert_basic(
            tg_id=tg_id, role="student",
            first_name=first_name, last_name=last_name, username=username,
            email=email, id=id
        )

    def ensure_owner(self, owner_tg_id: int,
                     first_name: str = "", last_name: str = "", username: str = "") -> None:
        if not owner_tg_id:
            return
        row = self.get_by_tg(owner_tg_id)
        role = (row or {}).get("role", "unknown")
        if role != "owner":
            self.upsert_basic(owner_tg_id, role="owner",
                              first_name=first_name, last_name=last_name, username=username)
