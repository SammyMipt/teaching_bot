from app.storage.users import get_user, upsert_user, list_pending_instructors

def test_user_register_student():
    upsert_user({
        "user_id": "555555", "role": "student", "full_name": "Test Student",
        "group": "B1", "email": "s@example.com", "status": "active",
        "created_at": "1234567890", "code_used": "PHYS-2025",
    })
    got = get_user(555555)
    assert got is not None and got["role"] == "student" and got["status"] == "active"

def test_user_register_instructor_pending_then_approve():
    upsert_user({
        "user_id": "777777", "role": "instructor", "full_name": "TA Person",
        "group": "TA", "email": "ta@example.com", "status": "pending",
        "created_at": "1234567899", "code_used": "TA-2025",
    })
    assert any(p["user_id"] == "777777" for p in list_pending_instructors())
    rec = get_user(777777); rec["status"] = "active"; upsert_user(rec)
    assert not any(p["user_id"] == "777777" for p in list_pending_instructors())
