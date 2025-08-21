from __future__ import annotations
import os
import pandas as pd
from filelock import FileLock
from typing import Iterable

class CsvTable:
    def __init__(self, path: str, columns: list[str]):
        self.path = path
        self.columns = columns
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.lock = FileLock(self.path + ".lock")
        if not os.path.exists(self.path):
            df = pd.DataFrame(columns=self.columns)
            with self.lock:
                df.to_csv(self.path, index=False)

    def read(self) -> pd.DataFrame:
        with self.lock:
            if not os.path.exists(self.path):
                return pd.DataFrame(columns=self.columns)
            return pd.read_csv(self.path)

    def write(self, df: pd.DataFrame) -> None:
        # ensure schema before write
        for c in self.columns:
            if c not in df.columns:
                df[c] = None
        df = df[self.columns]
        with self.lock:
            df.to_csv(self.path, index=False)

    def append_row(self, row: dict) -> None:
        df = self.read()
        for c in self.columns:
            if c not in df.columns:
                df[c] = None
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        self.write(df)

    def upsert(self, key_cols: Iterable[str], row: dict) -> None:
        df = self.read()
        if df.empty:
            self.append_row(row)
            return
        mask = None
        for k in key_cols:
            if k not in df.columns:
                df[k] = None
            m = df[k].astype(str) == str(row.get(k, ""))
            mask = m if mask is None else (mask & m)
        if mask is not None and mask.any():
            for col, val in row.items():
                if col not in df.columns:
                    df[col] = None
                df.loc[mask, col] = val
            self.write(df)
        else:
            self.append_row(row)

    def find(self, **conds) -> pd.DataFrame:
        df = self.read()
        if df.empty:
            return df
        mask = None
        for k, v in conds.items():
            if k not in df.columns:
                return df.iloc[0:0]
            m = df[k].astype(str) == str(v)
            mask = m if mask is None else (mask & m)
        return df[mask] if mask is not None else df
