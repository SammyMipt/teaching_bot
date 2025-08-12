import sys, pathlib, pytest
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path, monkeypatch):
    from app.storage import users, grades
    users.CSV_PATH = str(tmp_path / "users.csv")
    grades.CSV_PATH = str(tmp_path / "grades.csv")
    yield
