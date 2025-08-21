import logging
from .base import Storage

log = logging.getLogger(__name__)

class YandexDiskStorageStub(Storage):
    def __init__(self, token: str | None):
        self.token = token

    async def save_bytes(self, path: str, content: bytes) -> str:
        # Заглушка: в реальной версии — загрузка через REST API Я.Диска
        log.info("YandexDiskStorageStub.save_bytes called",
                 extra={"path": path, "bytes": len(content)})
        return f"yadisk://{path}"
