import csv
import os
import time
from typing import Optional, Dict, List

CSV_PATH = "data/users.csv"
FIELDS = ["user_id","role","full_name","group","email","status","created_at","code_used"]

def ensure_csv():
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    if not os.path.exists(CSV_PATH):
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writeheader()

def get_user(user_id: int) -> Optional[Dict[str,str]]:
    ensure_csv()
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["user_id"] == str(user_id):
                return r
    return None

def upsert_user(user: Dict[str,str]) -> None:
    ensure_csv()
    rows: List[Dict[str,str]] = []
    found = False
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["user_id"] == user["user_id"]:
                rows.append(user)
                found = True
            else:
                rows.append(r)
    if not found:
        rows.append(user)
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

def list_pending_instructors() -> List[Dict[str,str]]:
    ensure_csv()
    out: List[Dict[str,str]] = []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["role"] == "instructor" and r["status"] == "pending":
                out.append(r)
    return out
