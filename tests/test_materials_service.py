import os, sys, pathlib
import asyncio
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
from app.repositories.materials_repo import MaterialsRepo
from app.services.materials_service import MaterialsService
from app.integrations.storage.local_storage import LocalDiskStorage
from app.services.audit_service import AuditService

def test_upload_and_history(tmp_path):
    data_dir = tmp_path / "data"
    os.makedirs(data_dir, exist_ok=True)
    repo = MaterialsRepo(str(data_dir))
    storage = LocalDiskStorage(str(tmp_path / "storage"))
    audit = AuditService(str(data_dir))
    svc = MaterialsService(repo, storage, audit)

    async def run():
        content1 = b"hello"
        m1 = await svc.upload_material("W01", "prep", content1, actor_id=1)
        active = svc.list_active("W01")
        assert active[0]["material_id"] == m1["material_id"]

        m1b = await svc.upload_material("W01", "prep", content1, actor_id=1)
        assert m1b["material_id"] == m1["material_id"]
        assert len(svc.history("W01", "prep")) == 1

        content2 = b"world"
        m2 = await svc.upload_material("W01", "prep", content2, actor_id=1)
        active2 = svc.list_active("W01")
        assert active2[0]["material_id"] == m2["material_id"]
        hist = svc.history("W01", "prep")
        assert len(hist) >= 2

    asyncio.run(run())
