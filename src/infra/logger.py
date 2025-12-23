from __future__ import annotations

import sys
from pathlib import Path
from loguru import logger


def setup_logger() -> None:

    # pastikan folder logs ada
    Path("logs").mkdir(parents=True, exist_ok=True)

    # hapus default handler loguru
    logger.remove()

    # ===== CONSOLE LOGGER =====
    logger.add(
        sys.stdout,
        level="INFO",
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{module}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
    )

    # ===== FILE LOGGER (ALL LEVELS) =====
    logger.add(
        "logs/app.log",
        level="DEBUG",          # DEBUG, INFO, SUCCESS, WARNING, ERROR
        rotation="5 MB",
        retention="7 days",
        enqueue=True,           # 🔥 penting untuk Windows
        backtrace=True,
        diagnose=False,
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
            "{level: <8} | "
            "{module}:{function}:{line} - "
            "{message}"
        ),
    )
