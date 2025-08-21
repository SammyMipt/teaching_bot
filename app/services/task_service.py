from __future__ import annotations
import os
from app.repositories.csv_repo import CsvTable
from app.utils.ids import new_id

TASK_COLUMNS = ["task_id","week","title","deadline_iso","max_points","description"]

class TaskService:
    def __init__(self, data_dir: str):
        self.table = CsvTable(os.path.join(data_dir, "tasks.csv"), TASK_COLUMNS)

    def list_tasks(self):
        return self.table.read().sort_values(by=["week","deadline_iso"], ascending=[True, True])

    def add_task(self, week: str, title: str, deadline_iso: str, max_points: float, description: str | None = None):
        task = {
            "task_id": new_id("tsk"),
            "week": str(week),
            "title": title,
            "deadline_iso": deadline_iso,
            "max_points": float(max_points),
            "description": description or "",
        }
        self.table.append_row(task)
        return task
