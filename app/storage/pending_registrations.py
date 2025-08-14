"""
Система хранения черновиков регистраций для проблемных случаев
"""
import csv
import os
import time
from typing import Optional, Dict, List
from dataclasses import dataclass, asdict

@dataclass
class PendingRegistration:
    user_id: str
    telegram_username: str
    full_name: str
    group: str
    email: str
    reason: str  # "no_match", "rejected_all", "multiple_uncertain"
    created_at: str
    status: str  # "pending", "resolved", "ignored"
    notes: str = ""

CSV_PATH = "data/pending_registrations.csv"
FIELDS = ["user_id", "telegram_username", "full_name", "group", "email", "reason", "created_at", "status", "notes"]

def ensure_csv():
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    if not os.path.exists(CSV_PATH):
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writeheader()

def add_pending_registration(
    user_id: int,
    telegram_username: str,
    full_name: str,
    group: str,
    email: str,
    reason: str
) -> None:
    """Добавляет черновик регистрации"""
    ensure_csv()
    
    pending = PendingRegistration(
        user_id=str(user_id),
        telegram_username=telegram_username or "unknown",
        full_name=full_name,
        group=group,
        email=email,
        reason=reason,
        created_at=str(int(time.time())),
        status="pending"
    )
    
    # Проверяем, нет ли уже записи для этого пользователя
    existing = get_pending_registration(user_id)
    if existing:
        # Обновляем существующую запись
        update_pending_registration(user_id, asdict(pending))
    else:
        # Добавляем новую
        with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writerow(asdict(pending))

def get_pending_registration(user_id: int) -> Optional[Dict[str, str]]:
    """Получает черновик регистрации по user_id"""
    ensure_csv()
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["user_id"] == str(user_id):
                return row
    return None

def list_pending_registrations() -> List[Dict[str, str]]:
    """Возвращает все неразрешённые черновики"""
    ensure_csv()
    pending = []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["status"] == "pending":
                pending.append(row)
    return pending

def update_pending_registration(user_id: int, updates: Dict[str, str]) -> bool:
    """Обновляет черновик регистрации"""
    ensure_csv()
    rows = []
    found = False
    
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["user_id"] == str(user_id):
                row.update(updates)
                found = True
            rows.append(row)
    
    if found:
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
    
    return found

def resolve_pending_registration(user_id: int, notes: str = "") -> bool:
    """Помечает черновик как разрешённый"""
    return update_pending_registration(user_id, {
        "status": "resolved",
        "notes": notes
    })

def ignore_pending_registration(user_id: int, notes: str = "") -> bool:
    """Помечает черновик как игнорируемый"""
    return update_pending_registration(user_id, {
        "status": "ignored", 
        "notes": notes
    })

def get_pending_count() -> int:
    """Возвращает количество ожидающих черновиков"""
    return len(list_pending_registrations())

def format_pending_for_display(pending_list: List[Dict[str, str]]) -> str:
    """Форматирует список черновиков для отображения"""
    if not pending_list:
        return "Нет ожидающих регистраций."
    
    lines = []
    for i, p in enumerate(pending_list[:20], 1):  # Лимит 20
        created_time = time.strftime("%d.%m %H:%M", time.localtime(int(p["created_at"])))
        reason_text = {
            "no_match": "не найден в ростере",
            "rejected_all": "отклонил все варианты", 
            "multiple_uncertain": "слишком много вариантов",
            "email_conflict": "email уже привязан"
        }.get(p["reason"], p["reason"])
        
        lines.append(
            f"{i}. 👤 {p['full_name']} (@{p['telegram_username']})\n"
            f"   🎓 {p['group']} | 📧 {p['email']}\n"
            f"   ❗ {reason_text} | 🕐 {created_time}\n"
            f"   🆔 user_id: {p['user_id']}\n"
        )
    
    if len(pending_list) > 20:
        lines.append(f"\n... и ещё {len(pending_list) - 20} записей")
    
    return "\n".join(lines)