from __future__ import annotations
import os
from app.repositories.csv_repo import CsvTable
from app.utils.ids import new_id
from app.utils.time import now_iso

GRADE_COLUMNS = ["grade_id","task_id","student_code","points","comment","graded_by","graded_at"]

class GradeService:
    def __init__(self, data_dir: str):
        self.table = CsvTable(os.path.join(data_dir, "grades.csv"), GRADE_COLUMNS)

    def set_grade(self, task_id: str, student_code: str, points: float, comment: str, graded_by: int):
        row = {
            "grade_id": new_id("grd"),
            "task_id": task_id,
            "student_code": student_code,
            "points": float(points),
            "comment": comment,
            "graded_by": graded_by,
            "graded_at": now_iso(),
        }
        self.table.append_row(row)
        return row

    def list_grades_for_student(self, student_code: str):
        df = self.table.find(student_code=student_code)
        return df.sort_values(by=["graded_at"], ascending=False)
