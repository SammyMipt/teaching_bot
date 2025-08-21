from dataclasses import dataclass
from typing import Optional

@dataclass
class UserProfile:
    tg_id: int
    student_code: Optional[str] = None
    role: str = "unknown"
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    group: Optional[str] = None

@dataclass
class Task:
    task_id: str
    week: str
    title: str
    deadline_iso: str
    max_points: float
    description: str | None = None
