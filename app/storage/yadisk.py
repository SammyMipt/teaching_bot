import os
import re
from functools import lru_cache
from typing import List, Tuple
from concurrent.futures import ThreadPoolExecutor

from webdav3.client import Client
from app.core.config import settings

# пул потоков для синхронного клиента webdav3
_executor = ThreadPoolExecutor(max_workers=4)

def _sanitize(name: str) -> str:
    name = (name or "").strip().replace(" ", "_")
    name = re.sub(r"[^A-Za-zА-Яа-я0-9_\-\.]", "", name)
    return name[:100] or "untitled"

@lru_cache(maxsize=1)
def get_webdav() -> Client:
    options = {
        "webdav_hostname": settings.YD_WEBDAV_URL,
        "webdav_login": settings.YD_LOGIN,
        "webdav_password": settings.YD_PASSWORD,
        # "timeout": 30,
        # "verify": True,  # при проблемах TLS можно временно выключить (НЕ в проде)
    }
    return Client(options)

def ensure_dirs(client: Client, path: str):
    parts = [p for p in (path or "").strip("/").split("/") if p]
    cur = ""
    for p in parts:
        cur = f"{cur}/{p}" if cur else f"/{p}"
        if not client.check(cur):
            client.mkdir(cur)

def build_remote_path(user_id: int, week: str, filename: str) -> str:
    week = _sanitize(week)
    filename = _sanitize(filename)
    return f"/submissions/{user_id}/week_{week}/{filename}"

def upload_sync(local_path: str, remote_path: str):
    c = get_webdav()
    ensure_dirs(c, remote_path.rsplit("/", 1)[0])
    c.upload_sync(remote_path=remote_path, local_path=local_path)

async def upload_async(local_path: str, remote_path: str):
    from asyncio import get_running_loop
    loop = get_running_loop()
    await loop.run_in_executor(_executor, upload_sync, local_path, remote_path)

def list_week_files(user_id: int, week: str) -> List[str]:
    """Вернёт полные remote-пути файлов за неделю (без директорий)."""
    c = get_webdav()
    root = f"/submissions/{user_id}/week_{_sanitize(week)}"
    if not c.check(root):
        return []
    items = c.list(root)
    files: List[str] = []
    for p in items:
        if p.endswith("/"):
            continue
        if p.startswith("/"):
            files.append(p)
        else:
            files.append(f"{root}/{p}")
    return files

def download_to_tmp(remote_path: str) -> str:
    """Скачивает remote-файл в temp и возвращает локальный путь."""
    c = get_webdav()
    import tempfile
    fd, tmp_path = tempfile.mkstemp()
    os.close(fd)
    c.download_sync(remote_path=remote_path, local_path=tmp_path)
    return tmp_path

def health_check_verbose() -> Tuple[bool, str]:
    c = get_webdav()
    try:
        ensure_dirs(c, "/submissions")
        _ = c.list("/")
        return True, "OK"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
