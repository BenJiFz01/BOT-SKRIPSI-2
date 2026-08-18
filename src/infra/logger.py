"""logger.py — Konfigurasi loguru untuk console dan file."""

import sys
from pathlib import Path

from loguru import logger

LOG_FILE = Path("logs/app.log")

# Format console — lebih ringkas, tanpa nama modul
_FMT_CONSOLE = (
    "<green>{time:HH:mm:ss}</green> "
    "| <level>{level:<8}</level> "
    "| {message}"
)

# Format file — lengkap dengan nama modul dan baris untuk debugging
_FMT_FILE = (
    "{time:YYYY-MM-DD HH:mm:ss} "
    "| {level:<8} "
    "| {name}:{line} "
    "| {message}"
)


def setup_logger(console_level: str = "INFO") -> None:
    """
    Inisialisasi loguru.
    - Console : level INFO ke atas (WARNING, ERROR, SUCCESS tampil berwarna)
    - File     : level DEBUG ke atas, rotasi harian, retensi 7 hari
    Detail reject reason (level DEBUG) hanya masuk ke file, tidak bising di terminal.
    """
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logger.remove()

    logger.add(
        sys.stderr,
        level   = console_level,
        format  = _FMT_CONSOLE,
        colorize= True,
    )
    logger.add(
        LOG_FILE,
        level    = "DEBUG",
        rotation = "1 day",
        retention= "7 days",
        format   = _FMT_FILE,
        encoding = "utf-8",
    )
