
import csv
import os
import time
from typing import Optional, List, Dict

CSV_PATH = "data/grades.csv"
FIELDS = ["user_id","week","score","comment","timestamp"]

def ensure_csv():
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    if not os.path.exists(CSV_PATH):
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writeheader()

def add_or_update_grade(user_id: int, week: str, score: float, comment: str = ""):
    ensure_csv()
    rows: List[Dict[str,str]] = []
    found = False
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            if r["user_id"] == str(user_id) and r["week"] == week:
                r["score"] = str(score)
                r["comment"] = comment
                r["timestamp"] = str(int(time.time()))
                found = True
            rows.append(r)
    if not found:
        rows.append({
            "user_id": str(user_id),
            "week": week,
            "score": str(score),
            "comment": comment,
            "timestamp": str(int(time.time())),
        })
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

def get_grade(user_id: int, week: str) -> Optional[Dict[str,str]]:
    ensure_csv()
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["user_id"] == str(user_id) and r["week"] == week:
                return r
    return None
