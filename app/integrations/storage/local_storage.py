import os
from .base import Storage

class LocalDiskStorage(Storage):
    def __init__(self, root: str):
        self.root = root
        os.makedirs(self.root, exist_ok=True)

    async def save_bytes(self, path: str, content: bytes) -> str:
        full = os.path.join(self.root, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as f:
            f.write(content)
        return full  # локальный путь
