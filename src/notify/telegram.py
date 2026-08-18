"""telegram.py — Kirim pesan teks HTML ke Telegram Bot API."""

import requests
from loguru import logger


def send_message(token: str, chat_id: str, text: str) -> None:
    """Kirim pesan HTML ke chat_id. Lempar exception jika gagal."""
    url  = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=10)
    if not resp.ok:
        logger.warning(f"Telegram error {resp.status_code}: {resp.text[:120]}")
        resp.raise_for_status()
