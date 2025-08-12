from app.storage.grades import add_or_update_grade, get_grade

def test_grades_add_and_update():
    add_or_update_grade(555555, "5", 8.5, "Хорошо")
    rec = get_grade(555555, "5")
    assert rec and rec["score"] == "8.5" and rec["comment"] == "Хорошо"
    add_or_update_grade(555555, "5", 9.0, "Отлично")
    rec2 = get_grade(555555, "5")
    assert rec2 and rec2["score"] == "9.0" and rec2["comment"] == "Отлично"
