from datetime import datetime, timezone

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def parse_time_range(s: str):
    # "HH:MM-HH:MM" -> ("HH:MM","HH:MM")
    s = s.strip()
    start, end = s.split("-")
    return start.strip(), end.strip()
