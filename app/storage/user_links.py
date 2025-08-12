import csv, os, time
from typing import Optional, Dict, List

CSV_PATH = "data/user_links.csv"
FIELDS = ["user_id","student_code","external_email","linked_by","linked_at","status"]

def ensure_csv():
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    if not os.path.exists(CSV_PATH):
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writeheader()

def upsert_link(user_id: int, student_code: str, external_email: str, linked_by="auto", status="active"):
    ensure_csv()
    rows: List[Dict[str,str]] = []
    found = False
    ext = (external_email or "").strip().lower()
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            # запретим один и тот же email разным user_id
            if (r.get("external_email") or "").strip().lower() == ext and r["user_id"] != str(user_id):
                raise ValueError("Этот email уже привязан к другому Telegram-аккаунту.")
            if r["user_id"] == str(user_id):
                r.update({
                    "student_code": student_code,
                    "external_email": external_email,
                    "linked_by": linked_by,
                    "linked_at": str(int(time.time())),
                    "status": status,
                })
                rows.append(r)
                found = True
            else:
                rows.append(r)
    if not found:
        rows.append({
            "user_id": str(user_id),
            "student_code": student_code,
            "external_email": external_email,
            "linked_by": linked_by,
            "linked_at": str(int(time.time())),
            "status": status,
        })
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader(); w.writerows(rows)

def get_link_by_user(user_id: int) -> Optional[Dict[str,str]]:
    ensure_csv()
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["user_id"] == str(user_id):
                return r
    return None

def get_link_by_email(email: str) -> Optional[Dict[str,str]]:
    ensure_csv()
    e = (email or "").strip().lower()
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if (r.get("external_email") or "").strip().lower() == e:
                return r
    return None

def resolve_user_id_by_student_code(student_code: str) -> Optional[int]:
    ensure_csv()
    code = (student_code or "").strip()
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("student_code") == code:
                return int(r["user_id"])
    return None

def resolve_student_code_by_user_id(user_id: int) -> Optional[str]:
    rec = get_link_by_user(user_id)
    return rec["student_code"] if rec else None
