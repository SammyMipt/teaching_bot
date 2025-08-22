from __future__ import annotations
import os
import pandas as pd
from typing import Optional, List, Tuple
from app.repositories.csv_repo import CsvTable
from app.utils.time import now_iso

COLUMNS = ["student_code","week","ta_code","created_at"]

class AssignmentsService:
    def __init__(self, data_dir: str):
        path = os.path.join(data_dir, "assignments.csv")
        self.table = CsvTable(path, COLUMNS)

    def set(self, student_code: str, week: int, ta_code: str) -> None:
        df = self.table.read()
        if df is None or df.empty:
            df = pd.DataFrame(columns=COLUMNS)
        
        # normalize
        sc = str(student_code).strip()
        wk = int(week)
        tc = str(ta_code).strip()

        if not df.empty:
            mask = (df["student_code"].astype(str) == sc) & (df["week"].astype(int) == wk)
            df = df.loc[~mask]  # remove old row if exists
        
        new_row = {"student_code": sc, "week": wk, "ta_code": tc, "created_at": now_iso()}
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        
        with self.table.lock:
            df.to_csv(self.table.path, index=False)

    def get(self, student_code: str, week: int) -> Optional[str]:
        df = self.table.read()
        if df is None or df.empty:
            return None
        sc = str(student_code).strip()
        wk = int(week)
        mask = (df["student_code"].astype(str) == sc) & (df["week"].astype(int) == wk)
        res = df.loc[mask]
        if not res.empty:
            return str(res.iloc[0]["ta_code"])
        return None

    def get_assignment_for_student_code(self, student_code: str, week: int) -> Optional[str]:
        """
        Получить назначение TA для студента по student_code и номеру недели.
        """
        df = self.table.read()
        if df is None or df.empty:
            return None
            
        sc = str(student_code).strip()
        wk = int(week)
        
        mask = (df["student_code"].astype(str) == sc) & (df["week"].astype(int) == wk)
        res = df.loc[mask]
        if not res.empty:
            return str(res.iloc[0]["ta_code"])
        return None

    def get_all_for_student(self, student_code: str) -> List[Tuple[int,str]]:
        df = self.table.read()
        if df is None or df.empty:
            return []
        sc = str(student_code).strip()
        sub = df.loc[df["student_code"].astype(str) == sc]
        items: List[Tuple[int,str]] = []
        for _, r in sub.iterrows():
            try:
                items.append((int(r["week"]), str(r["ta_code"])))
            except Exception:
                continue
        return items