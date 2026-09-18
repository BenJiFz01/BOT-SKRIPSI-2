"""telegram.py — Kirim pesan HTML ke Telegram Bot API."""

import html
import re

import requests
from loguru import logger


def _sanitize_html(text: str) -> str:
    """Escape karakter < > & yang bukan bagian dari tag HTML valid Telegram."""
    _ALLOWED_TAGS = re.compile(
        r'<(/?)(?:b|i|u|s|code|pre|a|tg-spoiler)(?:\s[^>]*)?>',
        re.IGNORECASE,
    )
    result   = []
    last_end = 0
    for m in _ALLOWED_TAGS.finditer(text):
        segment = text[last_end:m.start()]
        segment = segment.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        result.append(segment)
        result.append(m.group(0))
        last_end = m.end()
    tail = text[last_end:]
    tail = tail.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    result.append(tail)
    return "".join(result)


def send_message(token: str, chat_id: str, text: str) -> None:
    """
    Kirim pesan HTML ke chat_id via Telegram Bot API.
    Tidak melempar exception — error di-log sebagai warning.
    Jika HTML parsing gagal (400), retry dengan plain text.
    """
    url       = f"https://api.telegram.org/bot{token}/sendMessage"
    safe_text = _sanitize_html(text)

    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": safe_text, "parse_mode": "HTML"},
            timeout=10,
        )
        if resp.ok:
            return
        if resp.status_code == 400:
            logger.warning(f"Telegram HTML parse error, retry plain: {resp.text[:120]}")
            resp2 = requests.post(
                url,
                json={"chat_id": chat_id, "text": html.unescape(safe_text)},
                timeout=10,
            )
            if not resp2.ok:
                logger.warning(f"Telegram plain text gagal {resp2.status_code}: {resp2.text[:80]}")
        else:
            logger.warning(f"Telegram error {resp.status_code}: {resp.text[:120]}")
    except requests.exceptions.Timeout:
        logger.warning("Telegram timeout")
    except requests.exceptions.ConnectionError:
        logger.warning("Telegram connection error")
    except Exception as e:
        logger.warning(f"Telegram error: {e}")
