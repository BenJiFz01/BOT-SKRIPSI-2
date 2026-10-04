"""signal_tracker.py — Background thread monitoring TP/SL real-time."""

import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

import pandas as pd
from loguru import logger


from src.utils.time_utils import TZ_WIB, parse_dt_safe
from src.engine.anytf_mta_engine import record_loss, reset_consec_loss

POLL_INTERVAL  = 10
MAX_DURATION_H = 48


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
    atr_value:      float = 0.0
    is_setup_plan:  bool  = False
    entry_zone_hit: bool  = False
    tp1_hit:    bool = False
    tp2_hit:    bool = False
    tp3_hit:    bool = False
    resolved:   bool = False
    breakeven_sl: float | None = None
    trailing_sl:  float | None = None
    spread:       float = 0.30


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
        is_setup   = str(rec.get("is_setup_plan", "False")).lower() in ("true", "1", "yes")
        entry      = float(rec.get("entry",      0) or 0)
        entry_low  = float(rec.get("entry_low",  0) or 0) or entry
        entry_high = float(rec.get("entry_high", 0) or 0) or entry
        atr_value  = float(rec.get("atr_value",  0) or 0)
        direction  = rec.get("direction", "BUY")

        # Non-setup: entry_zone_hit selalu True — harga bisa sudah bergerak jauh
        # dari zona saat bot restart, kalau menunggu zona TP/SL tak pernah dimonitor.
        if is_setup:
            entry_zone_hit = False
        else:
            entry_zone_hit = True

        ts = TrackedSignal(
            signal_id   = sid,
            symbol      = rec.get("symbol", "XAUUSD"),
            direction   = direction,
            entry       = entry,
            entry_low   = entry_low,
            entry_high  = entry_high,
            sl          = float(rec.get("sl",    0) or 0),
            tp1         = float(rec.get("tp1",   0) or 0),
            tp2         = float(rec.get("tp2",   0) or 0) or None,
            tp3         = float(rec.get("tp3",   0) or 0) or None,
            start_time  = parse_dt_safe(rec.get("timestamp", "")),
            atr_value   = atr_value,
            is_setup_plan   = is_setup,
            entry_zone_hit  = entry_zone_hit,
            spread      = float(rec.get("spread", 0.3) or 0.3),
        )
        with self._lock:
            self._active[sid] = ts
        logger.debug(f"SignalTracker.add | {sid} | {ts.direction} @ {ts.entry} | setup={is_setup} atr={atr_value:.4f}")

    def get_active_count(self) -> int:
        with self._lock:
            return len(self._active)

    def _load_pending_from_logger(self) -> None:
        """Load sinyal PENDING dari logger saat startup; sinyal > 2 jam masuk
        _startup_signal_ids (notif Telegram diblokir, dianggap sinyal lama).
        """
        now = datetime.now(tz=TZ_WIB)
        suppress_threshold_hours = 2
        try:
            for rec in self._logger.get_trackable():
                self.add_signal(rec)
                sid = rec.get("signal_id", "")
                if not sid:
                    continue
                ts_str   = rec.get("timestamp", "")
                sig_time = parse_dt_safe(ts_str)
                age_hours = (now - sig_time).total_seconds() / 3600
                if age_hours > suppress_threshold_hours:
                    self._startup_signal_ids.add(sid)
                    logger.debug(f"SignalTracker startup: suppress notif {sid} (usia {age_hours:.1f}j)")
                else:
                    logger.debug(f"SignalTracker startup: keep notif {sid} (usia {age_hours:.1f}j)")
        except Exception as e:
            logger.warning(f"SignalTracker: gagal load pending: {e}")

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                next_interval = self._check_all()
            except Exception as e:
                logger.error(f"SignalTracker error: {e}")
                next_interval = self._poll_interval
            self._stop.wait(timeout=next_interval)

    def _check_all(self) -> float:
        """Check semua sinyal aktif. Returns interval poll berikutnya (adaptive)."""
        with self._lock:
            ids = list(self._active.keys())

        min_interval = self._poll_interval  # default 10 detik
        prices_cache: dict[str, tuple[float, float]] = {}

        for sid in ids:
            with self._lock:
                ts = self._active.get(sid)
            if ts is None or ts.resolved:
                continue

        # Cache harga per symbol
            sym = ts.symbol
            if sym not in prices_cache:
                try:
                    bid, ask = self._get_price(sym)
                    if bid > 0 and ask > 0:
                        prices_cache[sym] = (bid, ask)
                except Exception:
                    continue

            bid, ask = prices_cache.get(sym, (0.0, 0.0))
            if bid <= 0 or ask <= 0:
                continue

            self._evaluate(ts, bid, ask)

            # Adaptive interval: cek seberapa dekat harga ke TP1 atau SL
            if not ts.resolved:
                check_price = bid if ts.direction == "BUY" else ask
                atr_est = ts.atr_value if hasattr(ts, "atr_value") and ts.atr_value > 0 else 5.0
                dist_tp = abs(check_price - ts.tp1) if ts.tp1 > 0 else 999
                dist_sl = abs(check_price - ts.sl)
                min_dist = min(dist_tp, dist_sl)

                if min_dist <= atr_est * 0.5:
                    min_interval = min(min_interval, 1)   # sangat dekat → 1 detik
                elif min_dist <= atr_est * 1.5:
                    min_interval = min(min_interval, 3)   # agak dekat → 3 detik
                else:
                    min_interval = min(min_interval, 10)  # masih jauh → 10 detik

        with self._lock:
            self._active = {k: v for k, v in self._active.items() if not v.resolved}

        return max(1, min_interval)  # minimum 1 detik

    def _evaluate(self, ts: TrackedSignal, bid: float, ask: float) -> None:
        now        = datetime.now(tz=TZ_WIB)
        is_buy     = ts.direction == "BUY"
        check_price = bid if is_buy else ask

    # Setup plan: tunggu harga masuk entry zone dulu
        if not ts.entry_zone_hit:
            price_mid = (bid + ask) / 2
            in_zone = ts.entry_low <= price_mid <= ts.entry_high
            if in_zone:
                ts.entry_zone_hit = True
                logger.info(f"[TRACKER] Entry zone hit | {ts.signal_id} | price={price_mid:.2f} zone={ts.entry_low:.2f}-{ts.entry_high:.2f}")
            else:
                sl_before_entry = (is_buy and check_price <= ts.sl) or (not is_buy and check_price >= ts.sl)
                if sl_before_entry:
                    self._resolve(ts, "CANCELLED", check_price, now, "SL_BEFORE_ENTRY")
                return  # belum masuk zona, belum monitor TP

        # SL efektif = trailing > breakeven > original
        if ts.trailing_sl is not None:
            effective_sl = ts.trailing_sl
        elif ts.breakeven_sl is not None:
            effective_sl = ts.breakeven_sl
        else:
            effective_sl = ts.sl
        
        sl_hit = (is_buy and check_price <= effective_sl) or \
                 (not is_buy and check_price >= effective_sl)

        if sl_hit and not ts.tp1_hit:
            self._resolve(ts, "LOSS", check_price, now)
            return

        if not ts.tp1_hit and ts.tp1 > 0:
            if (is_buy and check_price >= ts.tp1) or (not is_buy and check_price <= ts.tp1):
                ts.tp1_hit = True
                self._logger.update_hit_time(ts.signal_id, "tp1", now.strftime("%Y-%m-%dT%H:%M:%S"))
                self._send_tp_notify("🎯 <b>TP1 TERCAPAI</b>", ts.signal_id, check_price)

                # Breakeven: SL ke entry + spread (hindari keluar rugi kecil)
                is_buy = ts.direction == "BUY"
                if is_buy:
                    ts.breakeven_sl = ts.entry + ts.spread
                else:
                    ts.breakeven_sl = ts.entry - ts.spread
                
                logger.info(
                    f"[TRACKER] Breakeven aktif | {ts.signal_id} | "
                    f"SL lama={ts.sl:.2f} → BE={ts.breakeven_sl:.2f} (entry + spread)"
                )

                if not ts.tp2:
                    self._resolve(ts, "WIN_TP1", check_price, now)
                    return

        if ts.tp1_hit and not ts.tp2_hit and ts.tp2:
            if (is_buy and check_price >= ts.tp2) or (not is_buy and check_price <= ts.tp2):
                ts.tp2_hit = True
                self._logger.update_hit_time(ts.signal_id, "tp2", now.strftime("%Y-%m-%dT%H:%M:%S"))
                self._send_tp_notify("🎯🎯 <b>TP2 TERCAPAI</b>", ts.signal_id, check_price)
                
                # Trailing: SL ke TP1 (lock profit 1.0R untuk posisi tersisa)
                ts.trailing_sl = ts.tp1
                logger.info(
                    f"[TRACKER] Trailing aktif | {ts.signal_id} | "
                    f"SL → TP1={ts.trailing_sl:.2f} (lock 1.0R)"
                )
                
                if not ts.tp3:
                    self._resolve(ts, "WIN_TP2", check_price, now)
                    return

        if ts.tp2_hit and not ts.tp3_hit and ts.tp3:
            if (is_buy and check_price >= ts.tp3) or (not is_buy and check_price <= ts.tp3):
                ts.tp3_hit = True
                self._logger.update_hit_time(ts.signal_id, "tp3", now.strftime("%Y-%m-%dT%H:%M:%S"))
                self._send_tp_notify("TP3 TERCAPAI — FULL TARGET!", ts.signal_id, check_price)
                self._resolve(ts, "WIN_TP3", check_price, now)
                return

        # SL hit setelah TP1/TP2 kena (fallback jika harga balik)
        if ts.tp1_hit and not ts.tp2_hit and sl_hit:
            self._resolve(ts, "WIN_TP1", check_price, now)
            return
        elif ts.tp2_hit and not ts.tp3_hit and sl_hit:
            self._resolve(ts, "WIN_TP2", check_price, now)
            return

    def _send_tp_notify(self, header: str, signal_id: str, price: float) -> None:
        """Kirim notif TP hanya untuk sinyal baru (bukan dari startup), langsung tanpa blocking."""
        if self._notify and signal_id not in self._startup_signal_ids:
            msg = f"{header}\nID: <code>{signal_id}</code>\nHarga: <code>{price:.2f}</code>"
            threading.Thread(
                target=self._notify, args=(msg,), name="TrackerNotify", daemon=True
            ).start()

    def _resolve(self, ts: TrackedSignal, outcome: str, price: float, now: datetime, reason: str = "") -> None:
        ts.resolved  = True
        duration_m   = int((now - ts.start_time).total_seconds() / 60)
        emoji  = {"WIN_TP1": "✅", "WIN_TP2": "✅✅", "WIN_TP3": "✅✅✅", "LOSS": "❌", "CANCELLED": "⚠️"}.get(outcome, "")
        is_new = ts.signal_id not in self._startup_signal_ids

        logger.success(f"[TRACKER] {outcome} | {ts.signal_id} | price={price:.2f} | duration={duration_m}m")

        # Consecutive loss/win tracker — key per mode agar scalping/intraday tak saling blokir
        _tf_from_id = ts.signal_id.split("_")[1] if "_" in ts.signal_id else ""
        _is_scal    = _tf_from_id.upper() in {"M5", "M15"}
        _cb_key     = f"{ts.symbol}_{'scalping' if _is_scal else 'intraday'}"
        if outcome == "LOSS":
            record_loss(_cb_key)
        elif outcome.startswith("WIN"):
            reset_consec_loss(_cb_key)

        # Kirim Telegram dulu — tidak tertahan I/O file
        if self._notify and outcome != "CANCELLED" and is_new:
            try:
                self._notify(
                    f"{emoji} <b>{outcome}</b>\n"
                    f"ID: <code>{ts.signal_id}</code>\n"
                    f"Harga: <code>{price:.2f}</code>\n"
                    f"Durasi: <code>{duration_m} menit</code>\n"
                    f"Pips: <code>{abs(price - ts.entry):.1f}</code>"
                )
            except Exception as e:
                logger.warning(f"Tracker notify error: {e}")

        # Simpan ke file di thread terpisah agar I/O tak memblokir polling
        def _save_async() -> None:
            try:
                self._logger.update_outcome(
                    ts.signal_id, outcome,
                    price=price, notes=reason or "Auto-detected by SignalTracker", duration_m=duration_m,
                )
            except Exception as e:
                logger.warning(f"Tracker save error: {e}")
            if self._refresh_report:
                try:
                    self._refresh_report()
                except PermissionError:
                    logger.debug("Tracker report skip: file dibuka di Excel")
                except Exception as e:
                    logger.debug(f"Tracker report refresh error: {e}")

        threading.Thread(target=_save_async, name="TrackerSave", daemon=True).start()
