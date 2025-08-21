from __future__ import annotations
import os
from app.integrations.storage.base import Storage
from app.integrations.storage.local_storage import LocalDiskStorage
from app.integrations.storage.yandex_disk_stub import YandexDiskStorageStub

def build_storage(kind: str, data_dir: str, yadisk_token: str | None) -> Storage:
    if kind == "local":
        return LocalDiskStorage(os.path.join(data_dir, "storage"))
    elif kind == "yadisk":
        return YandexDiskStorageStub(yadisk_token)
    else:
        raise ValueError(f"Unknown storage kind: {kind}")
