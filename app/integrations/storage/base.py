from typing import Protocol

class Storage(Protocol):
    async def save_bytes(self, path: str, content: bytes) -> str:
        """Сохранить и вернуть путь/URL"""
        ...
