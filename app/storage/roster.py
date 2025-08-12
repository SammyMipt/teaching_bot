import csv
from functools import lru_cache

ROSTER_PATH = "data/roster.csv"

@lru_cache(maxsize=1)
def _load_roster_cached():
    rows = []
    try:
        with open(ROSTER_PATH, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        pass
    return rows

def reload_roster_cache():
    _load_roster_cached.cache_clear()

def load_roster():
    return _load_roster_cached()

def get_by_email(email: str):
    if not email:
        return None
    e = email.strip().lower()
    for r in load_roster():
        if (r.get("external_email") or "").strip().lower() == e:
            return r
    return None

def get_by_student_code(code: str):
    code = (code or "").strip()
    for r in load_roster():
        if r.get("student_code") == code:
            return r
    return None

def find_candidates(last_name: str, group: str | None = None, email_part: str | None = None):
    q_last = (last_name or "").strip().lower()
    q_group = (group or "").strip().lower() if group else None
    q_email = (email_part or "").strip().lower() if email_part else None
    out = []
    for r in load_roster():
        ln_ru = (r.get("last_name_ru") or "").strip().lower()
        ln_en = (r.get("last_name_en") or "").strip().lower()
        if q_last and q_last not in ln_ru and q_last not in ln_en:
            continue
        if q_group and q_group != (r.get("group") or "").strip().lower():
            continue
        if q_email and q_email not in (r.get("external_email") or "").strip().lower():
            continue
        out.append(r)
    return out
