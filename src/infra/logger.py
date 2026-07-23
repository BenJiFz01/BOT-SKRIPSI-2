"""logger.py — Setup loguru untuk logging ke konsol dan file."""
from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger


def setup_logger() -> None:
    """Setup logger: konsol INFO+, file DEBUG+ (rotasi 5 MB, retensi 7 hari)."""
    Path("logs").mkdir(parents=True, exist_ok=True)
    logger.remove()

    logger.add(
        sys.stdout,
        level="INFO",
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{module}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
    )

    logger.add(
        "logs/app.log",
        level="DEBUG",
        rotation="5 MB",
        retention="7 days",
        enqueue=True,
        backtrace=True,
        diagnose=False,
        encoding="utf-8",
        format=(
            "{time:YYYY-MM-DD HH:mm:ss} | "
            "{level: <8} | "
            "{module}:{line} - "
            "{message}"
        ),
    )
