# tests/test_grades.py
from app.storage.grades import add_or_update_grade, get_grade

def test_grades_add_and_update():
    # добавление
    add_or_update_grade(555555, "5", 8.5, "Хорошо")
    rec = get_grade(555555, "5")
    assert rec is not None
    assert rec["score"] == "8.5"
    assert rec["comment"] == "Хорошо"

    # обновление
    add_or_update_grade(555555, "5", 9.0, "Отлично")
    rec2 = get_grade(555555, "5")
    assert rec2["score"] == "9.0"
    assert rec2["comment"] == "Отлично"
