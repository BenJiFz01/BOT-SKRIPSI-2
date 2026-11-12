"""news_filter.py — Filter kalender ekonomi (Forex Factory feed).

Mengunduh data kalender ekonomi dari FairEconomy (Forex Factory JSON/XML/CSV feed),
menyimpan cache lokal, dan mendeteksi jendela waktu berita berdampak tinggi
(High-Impact USD) untuk menahan pembuatan sinyal trading XAU/USD.
"""
from __future__ import annotations

import csv
import io
import json
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from loguru import logger

# Endpoint FairEconomy dengan prioritas: XML & CSV sangat stabil dan tidak sering kena rate-limit CloudFront
_ENDPOINTS = [
    ("https://nfs.faireconomy.media/ff_calendar_thisweek.xml", "xml"),
    ("https://nfs.faireconomy.media/ff_calendar_thisweek.csv", "csv"),
    ("https://nfs.faireconomy.media/ff_calendar_thisweek.json", "json"),
]
_CACHE_FILE = Path("logs/news_calendar.json")
_CACHE_TTL_SEC = 3600  # Refresh setiap 1 jam agar update rilis berita selalu tepat waktu

_NEWS_CACHE: list[dict[str, Any]] = []
_LAST_FETCH_TIME: float = 0.0
_LAST_FETCH_DAY: str = ""
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml,text/csv,application/json;q=0.9,*/*;q=0.8",
}


def _parse_iso_event(raw: dict[str, Any]) -> dict[str, Any] | None:
    try:
        title = str(raw.get("title", "")).strip()
        country = str(raw.get("country", "")).strip().upper()
        impact = str(raw.get("impact", "")).strip().capitalize()
        date_str = str(raw.get("date", "")).strip()
        if not title or not country or not date_str:
            return None

        # Parse ISO date with timezone (e.g. 2026-11-03T10:16:00-05:00) ke UTC
        dt = datetime.fromisoformat(date_str).astimezone(timezone.utc)
        return {
            "title": title,
            "country": country,
            "impact": impact,
            "time_utc": dt,
            "forecast": str(raw.get("forecast", "") or "").strip(),
            "previous": str(raw.get("previous", "") or "").strip(),
        }
    except Exception:
        return None


def _parse_xml_events(content: bytes) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    root = ET.fromstring(content)
    for ev in root.findall("event"):
        try:
            title = (ev.findtext("title") or "").strip()
            country = (ev.findtext("country") or "").strip().upper()
            impact = (ev.findtext("impact") or "").strip().capitalize()
            date_s = (ev.findtext("date") or "").strip()
            time_s = (ev.findtext("time") or "").strip()
            if not title or not country or not date_s or not time_s:
                continue

            # FairEconomy XML date='11-06-2026', time='1:30pm' (waktu UTC)
            dt = datetime.strptime(f"{date_s} {time_s}", "%m-%d-%Y %I:%M%p").replace(tzinfo=timezone.utc)
            results.append({
                "title": title,
                "country": country,
                "impact": impact,
                "time_utc": dt,
                "forecast": (ev.findtext("forecast") or "").strip(),
                "previous": (ev.findtext("previous") or "").strip(),
            })
        except Exception:
            continue
    return results


def _parse_csv_events(text: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        try:
            title = (row.get("Title") or "").strip()
            country = (row.get("Country") or "").strip().upper()
            impact = (row.get("Impact") or "").strip().capitalize()
            date_s = (row.get("Date") or "").strip()
            time_s = (row.get("Time") or "").strip()
            if not title or not country or not date_s or not time_s:
                continue

            dt = datetime.strptime(f"{date_s} {time_s}", "%m-%d-%Y %I:%M%p").replace(tzinfo=timezone.utc)
            results.append({
                "title": title,
                "country": country,
                "impact": impact,
                "time_utc": dt,
                "forecast": (row.get("Forecast") or "").strip(),
                "previous": (row.get("Previous") or "").strip(),
            })
        except Exception:
            continue
    return results


def _save_cache(events: list[dict[str, Any]]) -> None:
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        serializable = []
        for e in events:
            item = dict(e)
            item["time_utc"] = e["time_utc"].isoformat()
            serializable.append(item)
        _CACHE_FILE.write_text(json.dumps(serializable, indent=2), encoding="utf-8")
    except Exception as e:
        logger.debug(f"Gagal menyimpan cache berita: {e}")


def _load_cache() -> list[dict[str, Any]]:
    if not _CACHE_FILE.exists():
        return []
    try:
        raw_list = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        results = []
        for r in raw_list:
            if "time_utc" in r:
                r_copy = dict(r)
                r_copy["time_utc"] = datetime.fromisoformat(r["time_utc"])
                results.append(r_copy)
            elif (ev := _parse_iso_event(r)) is not None:
                results.append(ev)
        return results
    except Exception:
        return []


def fetch_news_events(force: bool = False, timeout: int = 10) -> list[dict[str, Any]]:
    """Ambil daftar berita dari cache lokal atau feed online jika cache kadaluarsa."""
    global _NEWS_CACHE, _LAST_FETCH_TIME, _LAST_FETCH_DAY

    now = time.time()
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day_changed = (_LAST_FETCH_DAY != "" and today_str != _LAST_FETCH_DAY)

    # Jika force=True atau hari berganti atau memori kosong atau TTL habis, fetch ulang
    if not force and not day_changed and _NEWS_CACHE and (now - _LAST_FETCH_TIME < _CACHE_TTL_SEC):
        return _NEWS_CACHE
    if not force and not _NEWS_CACHE and _CACHE_FILE.exists():
        try:
            mtime = _CACHE_FILE.stat().st_mtime
            if now - mtime < _CACHE_TTL_SEC:
                cached = _load_cache()
                if cached:
                    _NEWS_CACHE = cached
                    _LAST_FETCH_TIME = mtime
                    return _NEWS_CACHE
        except Exception as e:
            logger.debug(f"Gagal membaca cache berita lokal: {e}")

    # Coba endpoint berurutan (XML -> CSV -> JSON)
    for url, fmt in _ENDPOINTS:
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=timeout)
            if resp.status_code == 200:
                parsed: list[dict[str, Any]] = []
                if fmt == "xml":
                    parsed = _parse_xml_events(resp.content)
                elif fmt == "csv":
                    parsed = _parse_csv_events(resp.text)
                elif fmt == "json":
                    raw_list = resp.json()
                    parsed = [ev for r in raw_list if (ev := _parse_iso_event(r)) is not None]

                if parsed:
                    _save_cache(parsed)
                    _NEWS_CACHE = parsed
                    _LAST_FETCH_TIME = now
                    _LAST_FETCH_DAY = today_str
                    logger.info(f"Kalender berita terupdate via {fmt.upper()}: {len(_NEWS_CACHE)} event dimuat.")
                    return _NEWS_CACHE
                logger.debug(f"Feed {fmt} returned status {resp.status_code}")
        except Exception as e:
            logger.debug(f"Gagal fetch {fmt} ({url}): {e}")

    # Fallback ke cache disk yang lama jika semua fetch online gagal
    if not _NEWS_CACHE:
        cached = _load_cache()
        if cached:
            _NEWS_CACHE = cached
            logger.warning(f"Menggunakan cache berita lama: {len(_NEWS_CACHE)} event.")
            return _NEWS_CACHE

    return _NEWS_CACHE


def is_news_blackout(
    dt: datetime | None = None,
    buffer_before_min: int = 30,
    buffer_after_min: int = 30,
    currency: str = "USD",
    impact_levels: tuple[str, ...] | list[str] = ("High",),
) -> tuple[bool, dict[str, Any] | None]:
    """Periksa apakah waktu dt berada dalam jendela waktu blackout berita.

    Returns:
        (True, info_event) jika masuk jendela blackout; (False, None) jika aman.
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    events = fetch_news_events()
    curr_target = currency.upper().strip()
    impact_set = {imp.strip().capitalize() for imp in impact_levels}

    for ev in events:
        if ev["country"] != curr_target:
            continue
        if ev["impact"] not in impact_set:
            continue

        ev_time: datetime = ev["time_utc"]
        window_start = ev_time - timedelta(minutes=buffer_before_min)
        window_end = ev_time + timedelta(minutes=buffer_after_min)

        if window_start <= dt <= window_end:
            diff_min = (dt - ev_time).total_seconds() / 60.0
            info = {
                "title": ev["title"],
                "country": ev["country"],
                "impact": ev["impact"],
                "time_utc": ev_time,
                "diff_minutes": round(diff_min, 1),
                "forecast": ev.get("forecast", ""),
                "previous": ev.get("previous", ""),
            }
            return True, info

    return False, None


def get_upcoming_news(
    dt: datetime | None = None,
    hours_ahead: float = 24.0,
    currency: str = "USD",
    impact_levels: tuple[str, ...] | list[str] = ("High",),
) -> list[dict[str, Any]]:
    """Daftar berita mendatang dalam rentang hours_ahead jam."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    limit_time = dt + timedelta(hours=hours_ahead)
    events = fetch_news_events()
    curr_target = currency.upper().strip()
    impact_set = {imp.strip().capitalize() for imp in impact_levels}

    matched: list[dict[str, Any]] = []
    for ev in events:
        if ev["country"] != curr_target or ev["impact"] not in impact_set:
            continue
        ev_time = ev["time_utc"]
        if dt <= ev_time <= limit_time:
            matched.append(ev)

    matched.sort(key=lambda x: x["time_utc"])
    return matched


def format_news_summary(
    dt: datetime | None = None,
    hours_ahead: float = 24.0,
    currency: str = "USD",
    impact_levels: tuple[str, ...] | list[str] = ("High",),
) -> str:
    """Format ringkasan berita mendatang ke string waktu WIB dengan bahasa Indonesia yang jelas."""
    events = get_upcoming_news(dt=dt, hours_ahead=hours_ahead, currency=currency, impact_levels=impact_levels)
    if not events:
        return f"Tidak ada berita {currency} {','.join(impact_levels)} dalam {int(hours_ahead)} jam ke depan."

    lines = [f"📅 <b>Berita {currency} ({','.join(impact_levels)}) {int(hours_ahead)} Jam Ke Depan:</b>"]
    wib_tz = timezone(timedelta(hours=7))
    now_wib = (datetime.now(timezone.utc) if dt is None else dt).astimezone(wib_tz)
    today_day = now_wib.date()

    nama_hari = {
        0: "Senin", 1: "Selasa", 2: "Rabu", 3: "Kamis",
        4: "Jumat", 5: "Sabtu", 6: "Minggu"
    }

    for ev in events:
        ev_wib = ev["time_utc"].astimezone(wib_tz)
        t_wib = ev_wib.strftime("%H:%M WIB")
        ev_day = ev_wib.date()

        # Jika hari ini, cukup tampilkan jam. Jika besok/beda hari, sebutkan nama hari agar tidak rancu.
        if ev_day == today_day:
            waktu_label = t_wib
        else:
            hari_str = nama_hari.get(ev_wib.weekday(), ev_wib.strftime("%a"))
            waktu_label = f"{hari_str}, {ev_wib.strftime('%d/%m')} {t_wib}"

        f_val = ev.get("forecast")
        p_val = ev.get("previous")
        extra_parts = []
        if f_val:
            extra_parts.append(f"Frc: {f_val}")
        if p_val:
            extra_parts.append(f"Prev: {p_val}")
        extra = f" ({', '.join(extra_parts)})" if extra_parts else ""
        lines.append(f"• <b>{waktu_label}</b> — {ev['title']}{extra}")

    return "\n".join(lines)
