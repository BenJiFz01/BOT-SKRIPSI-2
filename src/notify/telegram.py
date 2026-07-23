"""telegram.py — Pengiriman pesan HTML ke Telegram via Bot API."""
from __future__ import annotations

import requests
from loguru import logger


def send_message(token: str, chat_id: str, text: str) -> None:
    """Kirim pesan HTML ke Telegram. Raises HTTPError jika gagal."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id":                  chat_id,
        "text":                     text,
        "parse_mode":               "HTML",
        "disable_web_page_preview": True,
    }
    r = requests.post(url, json=payload, timeout=15)
    if not r.ok:
        logger.error(f"Telegram kirim gagal: {r.status_code} {r.text}")
        r.raise_for_status()
