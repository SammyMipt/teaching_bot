import logging, os
from logging.handlers import RotatingFileHandler

def setup_logging(level: str = "INFO") -> None:
    os.makedirs("logs", exist_ok=True)
    fmt = '%(asctime)s | %(levelname)s | %(name)s | %(message)s'
    datefmt = '%Y-%m-%d %H:%M:%S'
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=fmt,
        datefmt=datefmt,
        handlers=[
            logging.StreamHandler(),
            RotatingFileHandler("logs/bot.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        ]
    )
    logging.getLogger("aiogram").setLevel(logging.INFO)
