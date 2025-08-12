import csv
from typing import Optional

CSV_PATH = "data/instructor_map.csv"

def get_instructor_for_student_code(week: str, student_code: str) -> Optional[int]:
    wk = str(week)
    sc = (student_code or "").strip()
    try:
        with open(CSV_PATH, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("week") == wk and (r.get("student_code") or "").strip() == sc:
                    try:
                        return int(r["instructor_id"])
                    except:  # noqa
                        return None
    except FileNotFoundError:
        return None
    return None
