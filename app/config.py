from __future__ import annotations

import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Config:
    bot_token: str
    owner_tg_id: int
    data_dir: str
    storage_kind: str
    log_level: str
    yadisk_token: str | None
    ta_invite_code: str | None

def _read_owner_tg_id() -> int:
    """
    Robust owner id resolution:
    - PRIMARY: OWNER_TG_ID
    - FALLBACKS: OWNER_ID, OWNER, ADMIN_TG_ID
    Trims spaces and ignores non-digit garbage.
    """
    candidates = ["OWNER_TG_ID", "OWNER_ID", "OWNER", "ADMIN_TG_ID"]
    for key in candidates:
        raw = os.getenv(key)
        if not raw:
            continue
        s = raw.strip()
        # allow accidental quotes or comments like '123 # me'
        s = s.strip('\'"').split()[0]
        if s.isdigit():
            try:
                return int(s)
            except Exception:
                pass
    return 0

def load_config() -> Config:
    from dotenv import load_dotenv
    load_dotenv()

    token = (os.getenv("BOT_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is not set in environment")

    owner = _read_owner_tg_id()
    data_dir = os.getenv("DATA_DIR", "./data")
    storage_kind = (os.getenv("STORAGE_KIND", "local") or "local").lower()
    log_level = (os.getenv("LOG_LEVEL", "INFO") or "INFO").upper()
    yadisk_token = os.getenv("YADISK_TOKEN") or None
    ta_invite_code = os.getenv("TA_INVITE_CODE") or None

    os.makedirs(data_dir, exist_ok=True)

    return Config(
        bot_token=token,
        owner_tg_id=owner,
        data_dir=data_dir,
        storage_kind=storage_kind,
        log_level=log_level,
        yadisk_token=yadisk_token,
        ta_invite_code=ta_invite_code,
    )
