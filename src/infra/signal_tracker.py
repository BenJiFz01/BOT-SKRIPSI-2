"""signal_tracker.py — Background thread monitoring TP/SL real-time."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from loguru import logger

POLL_INTERVAL  = 10
MAX_DURATION_H = 48
_WIB = timezone(timedelta(hours=7))


@dataclass
class TrackedSignal:
    signal_id:  str
    symbol:     str
    direction:  str
    entry:      float
    entry_low:  float
    entry_high: float
    sl:         float
    tp1:        float
    tp2:        float | None
    tp3:        float | None
    start_time: datetime
    is_setup_plan:    bool = False
    entry_zone_hit:   bool = False   # True setelah harga masuk entry zone (untuk setup plan)
    tp1_hit:    bool = False
    tp2_hit:    bool = False
    tp3_hit:    bool = False
    resolved:   bool = False


class SignalTracker:
    """Monitor sinyal PENDING dan auto-update outcome saat TP/SL tersentuh."""

    def __init__(
        self,
        sig_logger,
        get_price_fn:       Callable[[str], tuple[float, float]],
        send_notify_fn:     Callable[[str], None] | None = None,
        refresh_report_fn:  Callable[[], None] | None    = None,
        poll_interval:  int = POLL_INTERVAL,
        max_duration_h: int = MAX_DURATION_H,
    ) -> None:
        self._logger         = sig_logger
        self._get_price      = get_price_fn
        self._notify         = send_notify_fn
        self._refresh_report = refresh_report_fn
        self._poll_interval  = poll_interval
        self._max_hours      = max_duration_h
        self._active: dict[str, TrackedSignal] = {}
        self._lock   = threading.Lock()
        self._stop   = threading.Event()
        self._thread: threading.Thread | None = None
        # Sinyal yang di-load saat startup — tidak kirim notif Telegram untuk ini
        self._startup_signal_ids: set[str] = set()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._load_pending_from_logger()
        self._thread = threading.Thread(target=self._run, name="SignalTracker", daemon=True)
        self._thread.start()
        logger.info(f"SignalTracker started | poll={self._poll_interval}s | tracking={len(self._active)} sinyal pending")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=15)
        logger.info("SignalTracker stopped.")

    def add_signal(self, rec: dict) -> None:
        sid = rec.get("signal_id", "")
        if not sid or float(rec.get("sl", 0) or 0) == 0:
            return
        is_setup = str(rec.get("is_setup_plan", "False")).lower() in ("true", "1", "yes")
        entry     = float(rec.get("entry",      0) or 0)
        entry_low = float(rec.get("entry_low",  0) or 0) or entry
        entry_high= float(rec.get("entry_high", 0) or 0) or entry
        ts = TrackedSignal(
            signal_id   = sid,
            symbol      = rec.get("symbol", "XAUUSD"),
            direction   = rec.get("direction", "BUY"),
            entry       = entry,
            entry_low   = entry_low,
            entry_high  = entry_high,
            sl          = float(rec.get("sl",    0) or 0),
            tp1         = float(rec.get("tp1",   0) or 0),
            tp2         = float(rec.get("tp2",   0) or 0) or None,
            tp3         = float(rec.get("tp3",   0) or 0) or None,
            start_time  = _parse_dt(rec.get("timestamp", "")),
            is_setup_plan   = is_setup,
            entry_zone_hit  = not is_setup,  # live signal langsung aktif, setup plan tunggu zona
        )
        with self._lock:
            self._active[sid] = ts
        logger.debug(f"SignalTracker.add | {sid} | {ts.direction} @ {ts.entry} | setup={is_setup}")

    def get_active_count(self) -> int:
        with self._lock:
            return len(self._active)

    def get_active_summary(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "signal_id": ts.signal_id, "symbol": ts.symbol,
                    "direction": ts.direction, "entry": ts.entry,
                    "sl": ts.sl, "tp1": ts.tp1, "tp2": ts.tp2, "tp3": ts.tp3,
                    "tp1_hit": ts.tp1_hit, "tp2_hit": ts.tp2_hit, "tp3_hit": ts.tp3_hit,
                    "since": ts.start_time.isoformat(),
                }
                for ts in self._active.values()
            ]

    def _load_pending_from_logger(self) -> None:
        try:
            for rec in self._logger.get_trackable():
                self.add_signal(rec)
                sid = rec.get("signal_id", "")
                if sid:
                    self._startup_signal_ids.add(sid)
        except Exception as e:
            logger.warning(f"SignalTracker: gagal load pending: {e}")

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._check_all()
            except Exception as e:
                logger.error(f"SignalTracker error: {e}")
            self._stop.wait(timeout=self._poll_interval)

    def _check_all(self) -> None:
        with self._lock:
            ids = list(self._active.keys())

        for sid in ids:
            with self._lock:
                ts = self._active.get(sid)
            if ts is None or ts.resolved:
                continue
            try:
                bid, ask = self._get_price(ts.symbol)
            except Exception:
                continue
            if bid > 0 and ask > 0:
                self._evaluate(ts, bid, ask)

        with self._lock:
            self._active = {k: v for k, v in self._active.items() if not v.resolved}

    def _evaluate(self, ts: TrackedSignal, bid: float, ask: float) -> None:
        now        = datetime.now(tz=_WIB)
        is_buy     = ts.direction == "BUY"
        check_price = bid if is_buy else ask

        # Expire check
        if (now - ts.start_time).total_seconds() / 3600 > self._max_hours:
            self._resolve(ts, "CANCELLED", (bid + ask) / 2, now, "EXPIRED")
            return

        # Setup plan: tunggu harga masuk entry zone dulu sebelum monitor TP/SL
        # Entry zone = antara entry_low dan entry_high
        if not ts.entry_zone_hit:
            price_mid = (bid + ask) / 2
            in_zone = ts.entry_low <= price_mid <= ts.entry_high
            if in_zone:
                ts.entry_zone_hit = True
                logger.info(f"[TRACKER] Entry zone hit | {ts.signal_id} | price={price_mid:.2f} zone={ts.entry_low:.2f}-{ts.entry_high:.2f}")
            else:
                # Belum masuk zona — cek apakah SL sudah tersentuh sebelum zona (sinyal batal)
                sl_before_entry = (is_buy and check_price <= ts.sl) or (not is_buy and check_price >= ts.sl)
                if sl_before_entry:
                    self._resolve(ts, "CANCELLED", check_price, now, "SL_BEFORE_ENTRY")
                return  # belum masuk zona, belum monitor TP

        sl_hit = (is_buy and check_price <= ts.sl) or (not is_buy and check_price >= ts.sl)

        if sl_hit and not ts.tp1_hit:
            self._resolve(ts, "LOSS", check_price, now)
            return

        if not ts.tp1_hit and ts.tp1 > 0:
            if (is_buy and check_price >= ts.tp1) or (not is_buy and check_price <= ts.tp1):
                ts.tp1_hit = True
                self._logger.update_hit_time(ts.signal_id, "tp1", now.strftime("%Y-%m-%dT%H:%M:%S"))
                self._send_tp_notify("🎯 <b>TP1 TERCAPAI</b>", ts.signal_id, check_price)
                if not ts.tp2:
                    self._resolve(ts, "WIN_TP1", check_price, now)
                    return

        if ts.tp1_hit and not ts.tp2_hit and ts.tp2:
            if (is_buy and check_price >= ts.tp2) or (not is_buy and check_price <= ts.tp2):
                ts.tp2_hit = True
                self._logger.update_hit_time(ts.signal_id, "tp2", now.strftime("%Y-%m-%dT%H:%M:%S"))
                self._send_tp_notify("🎯🎯 <b>TP2 TERCAPAI</b>", ts.signal_id, check_price)
                if not ts.tp3:
                    self._resolve(ts, "WIN_TP2", check_price, now)
                    return

        if ts.tp2_hit and not ts.tp3_hit and ts.tp3:
            if (is_buy and check_price >= ts.tp3) or (not is_buy and check_price <= ts.tp3):
                ts.tp3_hit = True
                self._logger.update_hit_time(ts.signal_id, "tp3", now.strftime("%Y-%m-%dT%H:%M:%S"))
                self._send_tp_notify("🎯🎯🎯 <b>TP3 TERCAPAI — FULL TARGET!</b>", ts.signal_id, check_price)
                self._resolve(ts, "WIN_TP3", check_price, now)
                return

        if ts.tp1_hit and not ts.tp2_hit and sl_hit:
            self._resolve(ts, "WIN_TP1", check_price, now)
        elif ts.tp2_hit and not ts.tp3_hit and sl_hit:
            self._resolve(ts, "WIN_TP2", check_price, now)

    def _send_tp_notify(self, header: str, signal_id: str, price: float) -> None:
        """Kirim notif TP hanya untuk sinyal baru (bukan dari startup)."""
        if self._notify and signal_id not in self._startup_signal_ids:
            self._notify(f"{header}\nID: <code>{signal_id}</code>\nHarga: <code>{price:.2f}</code>")

    def _resolve(self, ts: TrackedSignal, outcome: str, price: float, now: datetime, reason: str = "") -> None:
        ts.resolved  = True
        duration_m   = int((now - ts.start_time).total_seconds() / 60)
        self._logger.update_outcome(
            ts.signal_id, outcome,
            price=price, notes=reason or "Auto-detected by SignalTracker", duration_m=duration_m,
        )
        emoji = {"WIN_TP1": "✅", "WIN_TP2": "✅✅", "WIN_TP3": "✅✅✅", "LOSS": "❌", "CANCELLED": "⚠️"}.get(outcome, "")
        logger.success(f"[TRACKER] {outcome} | {ts.signal_id} | price={price:.2f} | duration={duration_m}m")

        is_new = ts.signal_id not in self._startup_signal_ids
        if self._notify and outcome != "CANCELLED" and is_new:
            self._notify(
                f"{emoji} <b>{outcome}</b>\n"
                f"ID: <code>{ts.signal_id}</code>\n"
                f"Harga resolve: <code>{price:.2f}</code>\n"
                f"Durasi: <code>{duration_m} menit</code>\n"
                f"Pips: <code>{abs(price - ts.entry):.1f}</code>"
            )

        if self._refresh_report:
            try:
                self._refresh_report()
            except PermissionError:
                logger.debug("Tracker report skip: file dibuka di Excel")
            except Exception as e:
                logger.debug(f"Tracker report refresh error: {e}")


def _parse_dt(s: str) -> datetime:
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_WIB)
        return dt
    except Exception:
        return datetime.now(tz=_WIB)
