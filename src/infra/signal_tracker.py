"""signal_tracker.py — Background thread monitoring TP/SL real-time."""

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
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
    early_be_hit: bool  = False
    timeframe:    str   = ""
    spread:       float = 0.30
    sl_source:    str   = ""
    min_price_seen: float = 0.0
    max_price_seen: float = 0.0
    crossed_rollover: bool = False
    # Observasi 12 bar M5 (60 menit) pasca-SL
    post_sl_monitoring: bool = False
    post_sl_expiry: datetime | None = None
    post_sl_tp1_hit: bool | None = None


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
        self._post_sl_active: dict[str, TrackedSignal] = {}
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

        # Pulihkan status BE / trailing / TP-hit jika ada dari restart sebelumnya
        be_val = rec.get("breakeven_sl")
        be_sl  = float(be_val) if be_val is not None and float(be_val) > 0 else None
        tr_val = rec.get("trailing_sl")
        tr_sl  = float(tr_val) if tr_val is not None and float(tr_val) > 0 else None

        tp1_hit = bool(rec.get("tp1_hit")) or bool(rec.get("tp1_hit_time"))
        tp2_hit = bool(rec.get("tp2_hit")) or bool(rec.get("tp2_hit_time"))
        tp3_hit = bool(rec.get("tp3_hit")) or bool(rec.get("tp3_hit_time"))
        early_be = bool(rec.get("early_be_hit", False))

        spread_val = float(rec.get("entry_spread") or rec.get("spread", 0.3) or 0.3)
        state_updated = False
        if tp1_hit and be_sl is None:
            be_sl = round(entry + spread_val, 5) if direction == "BUY" else round(entry - spread_val, 5)
            state_updated = True
        if tp2_hit and tr_sl is None:
            tp1_val = float(rec.get("tp1", 0) or 0)
            if tp1_val > 0:
                tr_sl = tp1_val
                state_updated = True
        if state_updated:
            try:
                self._logger.update_tracker_state(
                    sid,
                    breakeven_sl=be_sl,
                    trailing_sl=tr_sl,
                    early_be_hit=early_be,
                )
            except Exception:
                pass

        min_px = float(rec.get("min_price_seen") or entry)
        max_px = float(rec.get("max_price_seen") or entry)
        if min_px <= 0: min_px = entry
        if max_px <= 0: max_px = entry

        tf = str(rec.get("timeframe") or rec.get("tf") or "")
        if not tf and "_" in sid:
            parts = sid.split("_")
            if len(parts) >= 2 and parts[1] in ("M5", "M15", "H1", "H4", "D1"):
                tf = parts[1]

        ts = TrackedSignal(
            signal_id       = sid,
            symbol          = rec.get("symbol", "XAUUSD"),
            direction       = direction,
            entry           = entry,
            entry_low       = entry_low,
            entry_high      = entry_high,
            sl              = float(rec.get("sl",    0) or 0),
            tp1             = float(rec.get("tp1",   0) or 0),
            tp2             = float(rec.get("tp2",   0) or 0) or None,
            tp3             = float(rec.get("tp3",   0) or 0) or None,
            start_time      = parse_dt_safe(rec.get("timestamp", "")),
            atr_value       = atr_value,
            is_setup_plan   = is_setup,
            entry_zone_hit  = entry_zone_hit,
            tp1_hit         = tp1_hit,
            tp2_hit         = tp2_hit,
            tp3_hit         = tp3_hit,
            breakeven_sl    = be_sl,
            trailing_sl     = tr_sl,
            early_be_hit    = early_be,
            timeframe       = tf,
            spread          = float(rec.get("entry_spread") or rec.get("spread", 0.3) or 0.3),
            sl_source       = str(rec.get("sl_source") or rec.get("sl_method") or ""),
            min_price_seen  = min_px,
            max_price_seen  = max_px,
            crossed_rollover= bool(rec.get("crossed_rollover", False)),
        )
        with self._lock:
            self._active[sid] = ts
        logger.debug(f"SignalTracker.add | {sid} | {ts.direction} @ {ts.entry} | setup={is_setup} atr={atr_value:.4f} BE={be_sl} Trail={tr_sl}")

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

        # Periksa sinyal pasca-SL (observasi 12 bar M5 / 60 menit)
        now_check = datetime.now(tz=TZ_WIB)
        self._check_post_sl(prices_cache, now_check)

        return max(1, min_interval)  # minimum 1 detik

    def _check_post_sl(self, prices_cache: dict[str, tuple[float, float]], now: datetime) -> None:
        """Observasi 12 candle M5 (60 mnt) pasca-SL: apakah harga akhirnya capai TP1."""
        with self._lock:
            p_ids = list(self._post_sl_active.keys())
        for sid in p_ids:
            with self._lock:
                ts = self._post_sl_active.get(sid)
            if not ts:
                continue
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
            check_price = bid if ts.direction == "BUY" else ask
            hit_tp1 = (ts.direction == "BUY" and check_price >= ts.tp1) or \
                      (ts.direction == "SELL" and check_price <= ts.tp1)
            if hit_tp1:
                logger.info(f"[POST-SL MONITOR] {ts.signal_id} mencapai TP1 ({ts.tp1:.2f}) dalam 12 bar M5 pasca-SL! (px={check_price:.2f})")
                self._logger.update_post_sl_hit(ts.signal_id, True)
                with self._lock:
                    self._post_sl_active.pop(sid, None)
            elif ts.post_sl_expiry and now >= ts.post_sl_expiry:
                self._logger.update_post_sl_hit(ts.signal_id, False)
                with self._lock:
                    self._post_sl_active.pop(sid, None)

    def _evaluate(self, ts: TrackedSignal, bid: float, ask: float) -> None:
        now        = datetime.now(tz=TZ_WIB)
        is_buy     = ts.direction == "BUY"
        check_price = bid if is_buy else ask

        # Tracking MAE / MFE harga ekstrem sepanjang transaksi
        if ts.min_price_seen <= 0 or bid < ts.min_price_seen:
            ts.min_price_seen = bid
        if ts.max_price_seen <= 0 or ask > ts.max_price_seen:
            ts.max_price_seen = ask

        # Deteksi rollover spread spike:
        # 1. Spread saat ini >= 3.0 pt (normal XAU/USD ~0.30 pt; lonjakan malam hari)
        # 2. Jam rollover harian WIB: 03:55-05:30 WIB (21:55-22:30 UTC)
        curr_spread = abs(ask - bid)
        is_rollover_time = (now.hour == 4) or (now.hour == 3 and now.minute >= 55) or (now.hour == 5 and now.minute <= 30)
        if curr_spread >= 3.0 or is_rollover_time:
            ts.crossed_rollover = True

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

        # Early Breakeven (Proteksi Dini Khusus Timeframe Intraday / H1):
        # Jika harga bergerak searah profit >= 50% jarak TP1, aktifkan BE lebih awal
        # guna melindungi posisi dari pembalikan harga tajam (deep retracement).
        _is_intraday_tf = (
            ts.timeframe.upper() in ("H1", "H4") or
            "_H1_" in ts.signal_id or
            "_H4_" in ts.signal_id
        )
        if _is_intraday_tf and not ts.tp1_hit and ts.breakeven_sl is None and ts.tp1 > 0:
            target_dist = abs(ts.tp1 - ts.entry)
            early_threshold = 0.50 * target_dist
            favorable = (check_price - ts.entry) if is_buy else (ts.entry - check_price)
            if favorable >= early_threshold:
                if is_buy:
                    ts.breakeven_sl = ts.entry + ts.spread
                else:
                    ts.breakeven_sl = ts.entry - ts.spread
                ts.early_be_hit = True
                tag_tf = ts.timeframe.upper() if ts.timeframe.upper() in ("H1", "H4") else "H1"
                logger.info(
                    f"[TRACKER] Early Breakeven aktif ({tag_tf}) | {ts.signal_id} | "
                    f"profit={favorable:.2f}pt >= {early_threshold:.2f}pt | "
                    f"SL lama={ts.sl:.2f} → BE={ts.breakeven_sl:.2f}"
                )
                self._send_tp_notify(f"🛡️ <b>EARLY BREAKEVEN AKTIF ({tag_tf})</b>", ts.signal_id, check_price)
                self._logger.update_tracker_state(
                    ts.signal_id,
                    breakeven_sl=ts.breakeven_sl,
                    trailing_sl=ts.trailing_sl,
                    early_be_hit=ts.early_be_hit,
                    crossed_rollover=ts.crossed_rollover,
                    min_price_seen=ts.min_price_seen,
                    max_price_seen=ts.max_price_seen,
                )

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
            if ts.breakeven_sl is not None:
                self._resolve(ts, "BREAKEVEN", check_price, now, reason="Early BE Hit")
            else:
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
                self._logger.update_tracker_state(
                    ts.signal_id,
                    breakeven_sl=ts.breakeven_sl,
                    trailing_sl=ts.trailing_sl,
                    early_be_hit=ts.early_be_hit,
                    crossed_rollover=ts.crossed_rollover,
                    min_price_seen=ts.min_price_seen,
                    max_price_seen=ts.max_price_seen,
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
                self._logger.update_tracker_state(
                    ts.signal_id,
                    breakeven_sl=ts.breakeven_sl,
                    trailing_sl=ts.trailing_sl,
                    early_be_hit=ts.early_be_hit,
                    crossed_rollover=ts.crossed_rollover,
                    min_price_seen=ts.min_price_seen,
                    max_price_seen=ts.max_price_seen,
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
        emoji  = {"WIN_TP1": "✅", "WIN_TP2": "✅✅", "WIN_TP3": "✅✅✅", "LOSS": "❌", "CANCELLED": "⚠️", "BREAKEVEN": "🛡️"}.get(outcome, "")
        is_new = ts.signal_id not in self._startup_signal_ids

        # Level harga eksekusi terencana (SL/TP struktural), bukan sekadar harga tick observasi
        if outcome == "WIN_TP1":
            planned_exit = ts.tp1
        elif outcome == "WIN_TP2":
            planned_exit = ts.tp2 if ts.tp2 else ts.tp1
        elif outcome == "WIN_TP3":
            planned_exit = ts.tp3 if ts.tp3 else (ts.tp2 or ts.tp1)
        elif outcome == "BREAKEVEN":
            planned_exit = ts.breakeven_sl if ts.breakeven_sl is not None else ts.entry
        elif outcome == "LOSS":
            planned_exit = ts.sl
        else:
            planned_exit = price

        # Kalkulasi MAE & MFE dalam satuan ATR
        is_buy = ts.direction == "BUY"
        adverse_pts = max(0.0, ts.entry - ts.min_price_seen) if is_buy else max(0.0, ts.max_price_seen - ts.entry)
        favorable_pts = max(0.0, ts.max_price_seen - ts.entry) if is_buy else max(0.0, ts.entry - ts.min_price_seen)
        mae_atr = round(adverse_pts / ts.atr_value, 2) if ts.atr_value > 0 else 0.0
        mfe_atr = round(favorable_pts / ts.atr_value, 2) if ts.atr_value > 0 else 0.0

        # Jika LOSS, mulai observasi 12 candle M5 (60 menit) pasca-SL: apakah harga capai TP1
        if outcome == "LOSS" and ts.tp1 > 0:
            ts.post_sl_monitoring = True
            ts.post_sl_expiry = now + timedelta(minutes=60)
            ts.post_sl_tp1_hit = False
            with self._lock:
                self._post_sl_active[ts.signal_id] = ts

        logger.success(
            f"[TRACKER] {outcome} | {ts.signal_id} | planned_exit={planned_exit:.2f} (obs={price:.2f}) | "
            f"MAE={mae_atr:.2f}xATR MFE={mfe_atr:.2f}xATR | duration={duration_m}m"
        )

        # Consecutive loss/win tracker — key per mode agar scalping/intraday tak saling blokir
        _tf_from_id = ts.signal_id.split("_")[1] if "_" in ts.signal_id else ""
        _is_scal    = _tf_from_id.upper() in {"M5", "M15"}
        _cb_key     = f"{ts.symbol}_{'scalping' if _is_scal else 'intraday'}"
        if outcome == "LOSS":
            record_loss(_cb_key)
        elif outcome.startswith("WIN") or outcome == "BREAKEVEN":
            reset_consec_loss(_cb_key)

        # Kirim Telegram dulu — tidak tertahan I/O file
        if self._notify and outcome != "CANCELLED" and is_new:
            try:
                self._notify(
                    f"{emoji} <b>{outcome}</b>\n"
                    f"ID: <code>{ts.signal_id}</code>\n"
                    f"Harga: <code>{planned_exit:.2f}</code>\n"
                    f"Durasi: <code>{duration_m} menit</code>\n"
                    f"Pips: <code>{abs(planned_exit - ts.entry):.1f}</code>"
                )
            except Exception as e:
                logger.warning(f"Tracker notify error: {e}")

        # Simpan ke file di thread terpisah agar I/O tak memblokir polling
        note_str = reason or "Auto-detected by SignalTracker"
        if abs(price - planned_exit) > 0.01:
            note_str += f" | obs_px={price:.2f}"
        if ts.crossed_rollover:
            note_str += " | ROLLOVER"

        def _save_async() -> None:
            try:
                self._logger.update_outcome(
                    ts.signal_id, outcome,
                    price=planned_exit,
                    notes=note_str,
                    duration_m=duration_m,
                    breakeven_sl=ts.breakeven_sl,
                    trailing_sl=ts.trailing_sl,
                    crossed_rollover=ts.crossed_rollover,
                    mae_atr=mae_atr,
                    mfe_atr=mfe_atr,
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
