"""main.py — Entry point bot trading DSS Forex.

Jalankan: python -m src.main
Loop: candle close → evaluate_any_tf_mta() → sinyal ke Telegram → tracker pantau outcome.
"""
import re
import time
import requests
from datetime import datetime

import MetaTrader5 as mt5
import pandas as pd
import pytz
from loguru import logger

from src.config.settings import load_settings
from src.engine.anytf_mta_engine import evaluate_any_tf_mta
from src.features.indicators import add_indicators
from src.features.patterns import add_patterns
from src.features.news_filter import fetch_news_events, format_news_summary, is_news_blackout
from src.features.session import is_active_session
from src.infra.logger import setup_logger
from src.infra.reject_tracker import RejectTracker
from src.infra.report.generator import generate_report
from src.infra.health_server import HealthServer
from src.infra.scheduler import CandleCloseWatcher
from src.infra.signal_logger import SignalLogger
from src.infra.signal_tracker import SignalTracker
from src.mt5.connector import connect, shutdown, is_connected, ensure_connected
from src.mt5.market_data import ensure_symbol, fetch_ohlc, check_feed_stale
from src.notify.telegram import send_message
from src.notify.templates import format_signal


# Reject label utilities


def _extract(s: str, open_: str, close_: str) -> str:
    try:
        return s[s.index(open_) + len(open_): s.rindex(close_)]
    except (ValueError, IndexError):
        return ""


def _short_reject(raw: str) -> str:
    """Reject reason satu baris untuk terminal log."""
    if not raw or raw in ("INIT", "OK"):
        return raw
    u = raw.upper()

    if u.startswith("NOT_ENOUGH_BARS"):
        return f"Data kurang: {_extract(raw, '(', ')')} bar"
    if u.startswith("ATR_TOO_LOW_SCALPING"):
        atr  = re.search(r"atr=([0-9.]+)", raw)
        mn   = re.search(r"min=([0-9.]+)", raw)
        a    = atr.group(1) if atr else "?"
        m    = mn.group(1)  if mn  else "?"
        return f"ATR scalping terlalu kecil: {a} (min {m} poin) — pasar terlalu flat"
    if u.startswith("ATR_INVALID"):
        return "ATR tidak valid"
    if u.startswith("ATR_TOO_LOW"):
        return f"ATR terlalu kecil: {_extract(raw, '(', ')')}"
    if u.startswith("COOLDOWN"):
        return f"Cooldown: {_extract(raw, '(', ')')}"
    if u.startswith("OUT_OF_SESSION"):
        return f"Luar sesi: {_extract(raw, '(', ')')}"
    if u.startswith("DAILY_LIMIT"):
        mode = "scalping" if "SCALPING" in u else "intraday"
        count = _extract(raw, "(", ")")
        return f"Batas harian {mode}: {count}"
    if u.startswith("BIAS_FAIL+CT_FAIL"):
        ema  = re.search(r"ema=([A-Z_]+)", raw)
        macd = re.search(r"macd=([A-Z_]+)", raw)
        parts = []
        if ema:  parts.append(f"EMA:{ema.group(1)}")
        if macd: parts.append(f"MACD:{macd.group(1)}")
        return "Bias+CT gagal: " + " | ".join(parts) if parts else "Bias+CT gagal"
    if u.startswith("BIAS_FAIL"):
        detail = _extract(raw, "(", ")")
        parts  = [f"{tf}→{b.lower()}" for item in detail.split()
                  if ":" in item for tf, b in [item.split(":", 1)]]
        return "Bias: " + ", ".join(parts) if parts else f"Bias: {detail[:60]}"
    if u.startswith("TRIGGER_FAIL"):
        sc = re.search(r"score=(\d+)/(\d+)", raw)
        dr = re.search(r"dir=(\w+)", raw)
        if sc:
            skor      = sc.group(1)
            threshold = sc.group(2)
            arah      = dr.group(1) if dr else ""
            return f"Trigger gagal: {skor}/6 (min={threshold}) {arah}".strip()
        return "Trigger gagal"
    if u.startswith("CONFLUENCE_FAIL"):
        sc = re.search(r"conf=(\d+)/(\d+)", raw)
        if sc:
            skor      = sc.group(1)
            threshold = sc.group(2)
            notes = re.search(r"\[(.*?)\]", raw)
            extra = ""
            if notes:
                tags = [n.strip() for n in notes.group(1).split(",")
                        if any(k in n for k in ("Sweep", "FVG"))]
                if tags:
                    extra = " [" + ",".join(tags) + "]"
            return f"Confluence rendah: {skor} (min={threshold}){extra}"
        return "Confluence gagal"
    if u.startswith("SNR_BLOCKED"):
        return "SNR blocked: jalan terblokir"
    if "SNR_WEAK" in u:
        return "SNR lemah: level 2-touch berkontribusi 30% (optimal: 5+ touch)"
    if "MOM_RECOVERY_FAIL" in u:
        detail = re.search(r"MOM_RECOVERY_FAIL:([^\]]+)", raw)
        if detail:
            return f"Momentum Recovery gagal: {detail.group(1)}"
        return "Momentum Recovery: syarat tidak terpenuhi"
    if "MOM_RECOVERY" in u:
        arah   = re.search(r"MOM_RECOVERY:(BULL|BEAR)\(([^)]+)\)", raw)
        if arah:
            dir_label = "BUY" if arah.group(1) == "BULL" else "SELL"
            return f"Momentum Recovery {dir_label}: {arah.group(2)}"
        arah2 = re.search(r"MOM_RECOVERY:(BULL|BEAR)", raw)
        dir_label = ("BUY" if arah2 and arah2.group(1) == "BULL" else "SELL") if arah2 else "?"
        return f"Momentum Recovery: H1 NEUTRAL, impulse lokal → {dir_label}"
    if u.startswith("MARKET_TRANSITION"):
        adx = re.search(r"adx_(\w+)=([0-9.]+)", raw)
        if adx:
            return f"Transisi pasar: ADX {adx.group(1)}={adx.group(2)} (tren melemah, tunda Continuation)"
        return "Transisi pasar: tren di TF penentu melemah"
    if u.startswith("ASIAN_NO_KEY_LEVEL"):
        return "Asian: tidak ada level kunci (wajib SNR/SND)"
    if u.startswith("RR_FAIL"):
        rr  = re.search(r"rr=([0-9.None]+)", raw)
        mn  = re.search(r"min=([0-9.]+)", raw)
        return f"RR terlalu rendah: {rr.group(1) if rr else '?'} (min {mn.group(1) if mn else '?'})"
    if u.startswith("NEWS_BLACKOUT"):
        title = _extract(raw, "(", "|") or _extract(raw, "(", ")")
        diff = re.search(r"diff=([+-]?[0-9.]+)m", raw)
        diff_str = f" ({diff.group(1)}m)" if diff else ""
        return f"News Blackout: {title or 'USD News'}{diff_str}"
    if u.startswith("BROKER_FEED_STALE"):
        lag = re.search(r"lag=([0-9.]+)s", raw)
        return f"Broker Freeze: Kuotasi macet ({lag.group(1)}s)" if lag else "Broker Freeze: Kuotasi macet"
    if u.startswith("SLTP_NONE"):
        return "SL/TP tidak dapat dihitung"
    return raw.split(":")[0]


def _short_reject_with_df(raw: str, df: pd.DataFrame | None = None) -> str:
    if not raw or raw in ("INIT", "OK"):
        return raw
    u = raw.upper()
    if u.startswith("CT_EMA200_FAIL") or u.startswith("EMA200_WAJIB"):
        # CT_EMA200_FAIL tidak memuat dir= di raw — baca dari df, fallback "CT"
        dir_match = re.search(r"dir=(\w+)", raw)
        if df is not None and len(df) >= 2:
            try:
                last   = df.iloc[-2]
                close  = float(last.get("close", 0))
                ema200 = last.get("ema_200")
                if ema200 is not None and not pd.isna(ema200):
                    ema200    = float(ema200)
                    side      = "di bawah" if close < ema200 else "di atas"
                    dir_label = dir_match.group(1) if dir_match else "CT"
                    return f"EMA200: close={close:.1f} {side} EMA200={ema200:.1f} — {dir_label} ditolak"
            except Exception:
                pass
        dir_label = dir_match.group(1) if dir_match else "CT"
        return f"EMA200 berlawanan — {dir_label} ditolak"
    if u.startswith("LATE_ENTRY"):
        dist = re.search(r"dist=([0-9.]+)", raw)
        mx   = re.search(r"max=([0-9.]+)", raw)
        d    = dist.group(1) if dist else "?"
        m    = mx.group(1)   if mx   else "?"
        return f"Late entry: harga sudah jauh {d} dari trigger (max {m})"
    return _short_reject(raw)


def _fetch_prepare(symbol: str, tf: str, bars: int) -> pd.DataFrame:
    df = fetch_ohlc(symbol, tf, bars).sort_values("time").reset_index(drop=True)
    df = add_indicators(df, tf=tf)
    df = add_patterns(df)
    return df


def _get_mt5_tick(symbol: str) -> tuple[float, float]:
    tick = mt5.symbol_info_tick(symbol)
    return (tick.bid, tick.ask) if tick else (0.0, 0.0)


def _refresh_report(sig_logger: SignalLogger) -> None:
    try:
        generate_report(sig_logger, silent=True)
    except PermissionError:
        logger.debug("Report skip: file sedang dibuka di Excel")
    except Exception as e:
        logger.debug(f"Report refresh gagal: {e}")


def main() -> None:
    setup_logger()
    logger.info("Logger aktif")

    s = load_settings()
    logger.info(
        f"BOT START | symbols={s.symbols} TFs={s.timeframes} "
        f"bars={s.bars} poll={s.poll_seconds}s"
    )
    logger.info(
        f"PARAMS | RR>={s.min_rr} trig>={s.min_trigger_score} "
        f"conf>={s.min_confluence_score} votes>={s.min_confirm_votes} "
        f"cooldown={s.cooldown_bars}bar session={s.session_filter}"
    )
    logger.info(
        f"PARAMS SCALPING | TP={s.scalping_tp1_rr}R/{s.scalping_tp2_rr}R/{s.scalping_tp3_rr}R "
        f"SL_mult={s.scalping_sl_atr_mult}×ATR clamp=[{s.scalping_min_spread_mult}×spread, {s.scalping_max_atr_mult}×ATR] "
        f"SL_MIN_POINTS={s.sl_min_points}pt SL_OOB_MODE={s.sl_oob_mode} "
        f"ATR>={s.scalping_atr_min_points}pt spread={s.spread}pt "
        f"OE>={s.scalping_overextend_atr_mult}×ATR "
        f"PB={'ON' if s.scalping_pullback_enabled else 'OFF'} "
        f"Sweep={'ON' if s.scalping_sweep_enabled else 'OFF'} FVG={'ON' if s.scalping_fvg_enabled else 'OFF'} "
        f"trig>={s.scalping_min_trigger_score} conf>={s.scalping_min_confluence_score} "
        f"cooldown M5={s.scalping_cooldown_bars_m5}bar M15={s.scalping_cooldown_bars_m15}bar"
    )
    logger.info(
        f"PARAMS INTRADAY | TP={s.intraday_tp1_rr}R/{s.intraday_tp2_rr}R/{s.intraday_tp3_rr}R "
        f"SL_mult={s.intraday_sl_atr_mult}×ATR clamp=[{s.intraday_min_spread_mult}×spread, {s.intraday_max_atr_mult}×ATR]"
    )
    logger.info(
        f"PARAMS GATES | VETO+FLIP={'ON' if s.ltf_veto_enabled else 'OFF'} "
        f"flip_trig>={s.flip_min_trigger} FLIP_key={'ON' if s.flip_require_key_level else 'OFF'} "
        f"H1_key={'ON' if s.h1_require_key_level else 'OFF'} "
        f"PB_floor={s.scalping_pullback_min_trigger} "
        f"RangeQual_key={'ON' if s.range_quality_key_level else 'OFF'}"
    )

    sig_logger     = SignalLogger()
    reject_tracker = RejectTracker(interval_minutes=30)
    logger.info("SignalLogger aktif → logs/signal_history.csv")

    def _notify(msg: str) -> None:
        try:
            send_message(s.telegram_token, s.telegram_chat_id, msg)
        except Exception as e:
            logger.warning(f"Notify error: {e}")

    tracker = SignalTracker(
        sig_logger        = sig_logger,
        get_price_fn      = _get_mt5_tick,
        send_notify_fn    = _notify,
        refresh_report_fn = lambda: _refresh_report(sig_logger),
    )
    watcher = CandleCloseWatcher()
    health  = HealthServer()
    health.start()

    def _alert_offline(reason: str) -> None:
        try:
            send_message(
                s.telegram_token, s.telegram_chat_id,
                f"<b>🔴 BOT OFFLINE</b>\n\n"
                f"Status   : <code>OFF ({reason})</code>\n"
                f"Waktu    : <code>{datetime.now(pytz.UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}</code>\n"
                f"Server   : <code>{s.mt5_server}</code>",
            )
        except Exception as e:
            logger.warning(f"Alert offline gagal: {e}")

    # Heartbeat monitoring ke Healthchecks.io
    heartbeat_url  = s.healthcheck_ping_url.strip()
    heartbeat_ts   = 0.0
    HEARTBEAT_INTERVAL = 60.0  # 60 detik → Healthchecks Period=5m & Grace=5m aman

    def _heartbeat_ping() -> None:
        nonlocal heartbeat_ts
        if not heartbeat_url:
            return
        now = time.time()
        if now - heartbeat_ts < HEARTBEAT_INTERVAL:
            return
        heartbeat_ts = now
        try:
            requests.get(heartbeat_url, timeout=10)
        except Exception as e:
            logger.warning(f"Heartbeat ping gagal: {e}")

    try:
        acc = connect(s.mt5_login, s.mt5_password, s.mt5_server, s.mt5_terminal_path)
        logger.info(f"MT5 terhubung | login={acc.login} server={acc.server}")
        tracker.start()
        if s.news_filter_enabled:
            fetch_news_events()
            logger.info("News Filter aktif (Forex Factory USD High-Impact)")
        send_message(
            s.telegram_token, s.telegram_chat_id,
            (
                "<b>BOT TRADING ONLINE</b>\n\n"
                f"Account  : <code>{acc.login}</code>\n"
                f"Server   : <code>{acc.server}</code>\n"
                f"Symbols  : {', '.join(s.symbols)}\n"
                f"TFs      : {', '.join(s.timeframes)}\n\n"
                f"<b>Intraday</b>: RR>={s.min_rr} | Trig>={s.min_trigger_score} "
                f"| Conf>={s.min_confluence_score} "
                f"| D1_anchor={'ON' if s.intraday_require_d1 else 'OFF'} "
                f"| Cooldown={s.cooldown_bars}bar\n"
                f"<b>Scalping</b>: TP={s.scalping_tp1_rr}R/{s.scalping_tp2_rr}R/{s.scalping_tp3_rr}R "
                f"| SLM5<={s.max_sl_m5}pt | ATR>={s.scalping_atr_min_points}pt | OE>={s.scalping_overextend_atr_mult}×ATR "
                f"| PB={'ON' if s.scalping_pullback_enabled else 'OFF'} "
                f"| Trig>={s.scalping_min_trigger_score} | Conf>={s.scalping_min_confluence_score}\n"
                f"Session  : {'ON' if s.session_filter else 'OFF'} | "
                f"News: {'ON (' + s.news_currency + ' ' + ','.join(s.news_impact_levels) + ' ±' + str(s.news_buffer_before_min) + 'm)' if s.news_filter_enabled else 'OFF'}\n"
                f"Tracker  : ON ({tracker.get_active_count()} sinyal pending)"
            ),
        )

        _news_blackout_notified: set[str] = set()
        _last_morning_briefing_date: str = ""
        _last_stale_reconnect_time: float = 0.0
        _STALE_RECONNECT_COOLDOWN_SEC: float = 120.0

        while True:
            # Watchdog Koneksi MT5 (Auto-Reconnect jika terminal freeze / putus)
            if not is_connected():
                logger.warning("Koneksi MT5 terputus/freeze! Memulai auto-reconnect...")
                if ensure_connected(s.mt5_login, s.mt5_password, s.mt5_server, s.mt5_terminal_path):
                    logger.info("Koneksi MT5 berhasil dipulihkan secara otomatis.")
                else:
                    logger.error("Auto-reconnect MT5 gagal. Menunggu sebelum mencoba kembali...")
                    time.sleep(s.poll_seconds)
                    continue

            # Morning News Briefing jam 07:00-08:00 WIB (sekali per hari)
            if s.news_filter_enabled:
                _wib_now = datetime.now(pytz.timezone("Asia/Jakarta"))
                _today_str = _wib_now.strftime("%Y-%m-%d")
                if _today_str != _last_morning_briefing_date and (7 <= _wib_now.hour <= 8):
                    _last_morning_briefing_date = _today_str
                    try:
                        # Paksa refresh feed online saat pagi hari agar jadwal hari ini 100% akurat
                        fetch_news_events(force=True)
                        _briefing = format_news_summary(
                            dt=datetime.now(pytz.UTC),
                            hours_ahead=18.0,
                            currency=s.news_currency,
                            impact_levels=s.news_impact_levels,
                        )
                        _hari_id = {
                            "Monday": "Senin", "Tuesday": "Selasa", "Wednesday": "Rabu",
                            "Thursday": "Kamis", "Friday": "Jumat", "Saturday": "Sabtu", "Sunday": "Minggu"
                        }.get(_wib_now.strftime("%A"), _wib_now.strftime("%A"))
                        _tgl_str = f"{_hari_id}, {_wib_now.strftime('%d %B %Y')}"

                        send_message(
                            s.telegram_token, s.telegram_chat_id,
                            (
                                f"🌅 <b>MORNING ECONOMIC BRIEFING</b>\n\n"
                                f"Hari / Tgl : <code>{_tgl_str}</code>\n\n"
                                f"{_briefing}\n\n"
                                f"<i>Sistem otomatis menahan sinyal ±{s.news_buffer_before_min} menit sebelum & sesudah berita.</i>"
                            ),
                        )
                        logger.info(f"Morning briefing berita terkirim ke Telegram ({_tgl_str})")
                    except Exception as _br_err:
                        logger.warning(f"Gagal mengirim morning briefing: {_br_err}")

            for symbol in s.symbols:
                ensure_symbol(symbol)

                data_by_tf: dict[str, pd.DataFrame] = {}
                last_events: dict[str, object]      = {}

                for trigger_tf in s.timeframes:
                    tf_u = trigger_tf.upper()
                    try:
                        df = _fetch_prepare(symbol, tf_u, s.bars)
                        data_by_tf[tf_u] = df
                    except Exception as e:
                        logger.error(f"[FETCH ERROR] {symbol} {tf_u}: {e}")
                        continue
                    event = watcher.check(symbol, tf_u, df)
                    if event is not None:
                        last_events[tf_u] = event

                if not last_events:
                    continue

                bid, ask = _get_mt5_tick(symbol)
                tfs_closing = ", ".join(last_events.keys())
                logger.info(f"{symbol} | Candle close: {tfs_closing} | bid={bid:.2f} ask={ask:.2f}")
                reject_tracker.record_candle()
                signal_count = 0

                # Manajemen Notifikasi News Blackout Terpusat (Aktif & Selesai)
                if s.news_filter_enabled:
                    _bo_active, _bo_info = is_news_blackout(
                        dt=datetime.now(pytz.UTC),
                        buffer_before_min=s.news_buffer_before_min,
                        buffer_after_min=s.news_buffer_after_min,
                        currency=s.news_currency,
                        impact_levels=s.news_impact_levels,
                    )
                    if _bo_active and _bo_info:
                        _ev_key = _bo_info.get("title", "News")
                        if _ev_key not in _news_blackout_notified:
                            _news_blackout_notified.add(_ev_key)
                            _wib_tz = pytz.timezone("Asia/Jakarta")
                            _now_wib = datetime.now(pytz.UTC).astimezone(_wib_tz).strftime("%H:%M WIB")
                            send_message(
                                s.telegram_token, s.telegram_chat_id,
                                (
                                    f"📰 <b>NEWS BLACKOUT AKTIF</b>\n\n"
                                    f"Event    : <b>{_ev_key}</b>\n"
                                    f"Impact   : <code>USD High</code>\n"
                                    f"Buffer   : ±{s.news_buffer_before_min} menit\n"
                                    f"Waktu    : <code>{_now_wib}</code>\n\n"
                                    f"⏸ Sinyal ditahan hingga jendela blackout selesai."
                                ),
                            )
                            logger.info(f"Notifikasi blackout terkirim ke Telegram: {_ev_key}")
                    elif not _bo_active and _news_blackout_notified:
                        _cleared = ", ".join(_news_blackout_notified)
                        _news_blackout_notified.clear()
                        send_message(
                            s.telegram_token, s.telegram_chat_id,
                            (
                                f"✅ <b>NEWS BLACKOUT SELESAI</b>\n\n"
                                f"Event    : {_cleared}\n"
                                f"Status   : Sinyal kembali aktif."
                            ),
                        )
                        logger.info(f"News blackout selesai: {_cleared}")
                for tf_u in last_events:
                    tf_u_norm = tf_u.upper()
                    enabled_u = [t.upper() for t in s.timeframes]
                    data_norm = {k.upper(): v for k, v in data_by_tf.items()}
                    _sl_cap   = {
                        "M5":  s.max_sl_m5,  "M15": s.max_sl_m15,
                        "H1":  s.max_sl_h1,  "H4":  s.max_sl_h4,
                        "D1":  s.max_sl_d1,
                    }
                    _max_sl = _sl_cap.get(tf_u_norm, s.max_sl_points)
                    # Cek apakah feed kuotasi broker freeze/stale sebelum analisa
                    _feed_stale = False
                    _feed_lag = 0.0
                    if is_active_session(datetime.now(pytz.utc), tf=tf_u_norm):
                        _feed_stale, _feed_lag = check_feed_stale(symbol, max_lag_sec=60)
                        if _feed_stale:
                            logger.warning(
                                f"[FEED FREEZE] Kuotasi {symbol} macet (lag={_feed_lag:.0f}s > 60s) saat sesi aktif!"
                            )
                            _now_sec = time.time()
                            if _now_sec - _last_stale_reconnect_time > _STALE_RECONNECT_COOLDOWN_SEC:
                                _last_stale_reconnect_time = _now_sec
                                logger.info("Mencoba auto-reconnect MT5 untuk me-refresh kuotasi data yang macet...")
                                if ensure_connected(s.mt5_login, s.mt5_password, s.mt5_server, s.mt5_terminal_path):
                                    logger.info("Koneksi MT5 berhasil di-refresh setelah kuotasi macet.")
                                else:
                                    logger.warning("Auto-reconnect MT5 saat kuotasi macet belum berhasil.")

                    try:
                        sig = evaluate_any_tf_mta(
                            data_by_tf           = data_norm,
                            symbol               = symbol,
                            trigger_tf           = tf_u_norm,
                            enabled_tfs          = enabled_u,
                            min_rr               = s.min_rr,
                            min_confirm_votes    = s.min_confirm_votes,
                            min_trigger_score    = s.min_trigger_score,
                            min_confluence_score = s.min_confluence_score,
                            cooldown_bars        = s.cooldown_bars,
                            atr_min_pct          = s.atr_min_pct,
                            sl_atr_mult          = s.sl_atr_mult,
                            tp1_rr               = s.tp1_rr,
                            tp2_rr               = s.tp2_rr,
                            tp3_rr               = s.tp3_rr,
                            max_sl_points        = _max_sl,
                            sl_pips              = s.sl_pips,
                            tp1_pips             = s.tp1_pips,
                            tp2_pips             = s.tp2_pips,
                            tp3_pips             = s.tp3_pips,
                            pip_size             = s.pip_size,
                            session_filter       = s.session_filter,
                            counter_trend_enabled        = s.counter_trend_enabled,
                            min_counter_confluence       = s.min_counter_confluence,
                            counter_trend_min_rr         = s.counter_trend_min_rr,
                            counter_trend_tfs            = s.counter_trend_tfs,
                            scalping_min_trigger_score   = s.scalping_min_trigger_score,
                            scalping_min_confluence_score= s.scalping_min_confluence_score,
                            scalping_atr_min_points      = s.scalping_atr_min_points,
                            scalping_sl_atr_mult         = s.scalping_sl_atr_mult,
                            scalping_cooldown_bars       = s.scalping_cooldown_bars,
                            scalping_cooldown_bars_m5    = s.scalping_cooldown_bars_m5,
                            scalping_cooldown_bars_m15   = s.scalping_cooldown_bars_m15,
                            scalping_tp1_rr              = s.scalping_tp1_rr,
                            scalping_tp2_rr              = s.scalping_tp2_rr,
                            scalping_tp3_rr              = s.scalping_tp3_rr,
                            scalping_tp1_atr_mult        = s.scalping_tp1_atr_mult,
                            scalping_overextend_atr_mult  = s.scalping_overextend_atr_mult,
                            scalping_pullback_enabled  = s.scalping_pullback_enabled,
                            scalping_sweep_enabled   = s.scalping_sweep_enabled,
                            scalping_fvg_enabled     = s.scalping_fvg_enabled,
                            momentum_ema200_tolerance= s.momentum_ema200_tolerance,
                            range_rejection_enabled  = s.range_rejection_enabled,
                            scalping_min_rr              = s.scalping_min_rr,
                            scalping_counter_trend_min_rr= s.scalping_counter_trend_min_rr,
                            market_transition_adx_block  = s.market_transition_adx_block,
                            market_transition_adx_gray   = s.market_transition_adx_gray,
                            scalping_h1_only             = s.scalping_h1_only,
                            intraday_require_d1          = s.intraday_require_d1,
                            ltf_veto_enabled             = s.ltf_veto_enabled,
                            flip_min_trigger             = s.flip_min_trigger,
                            flip_require_key_level       = s.flip_require_key_level,
                            h1_require_key_level         = s.h1_require_key_level,
                            scalping_pullback_min_trigger= s.scalping_pullback_min_trigger,
                            range_quality_key_level       = s.range_quality_key_level,
                            spread                       = s.spread,
                            news_filter_enabled          = s.news_filter_enabled,
                            news_buffer_before_min       = s.news_buffer_before_min,
                            news_buffer_after_min        = s.news_buffer_after_min,
                            news_impact_levels           = s.news_impact_levels,
                            news_currency                = s.news_currency,
                            broker_feed_stale            = _feed_stale,
                            broker_feed_lag              = _feed_lag,
                            cfg_tag                      = f"atrmin{s.scalping_atr_min_points:.1f}|slmin{s.sl_min_points:.1f}|oob={s.sl_oob_mode}",
                        )
                    except Exception as eval_err:
                        # Tangani error evaluasi per timeframe agar bot tetap berjalan
                        logger.error(f"[EVAL ERROR] {symbol} {tf_u_norm}: {eval_err}", exc_info=True)
                        continue

                    if sig is None:
                        raw    = data_norm.get(tf_u_norm, pd.DataFrame()).attrs.get("reject_reason", "UNKNOWN")
                        df_cur = data_norm.get(tf_u_norm)
                        logger.info(f"{symbol} {tf_u_norm:<3} ✗  {_short_reject_with_df(raw, df_cur)}")
                        logger.debug(f"{tf_u_norm} raw: {raw[:200]}")
                        reject_tracker.record_reject(symbol=symbol, tf=tf_u_norm, raw=raw, df=df_cur)

                        # Log reject jika terjadi news blackout
                        if raw.startswith("NEWS_BLACKOUT") and s.news_filter_enabled:
                            logger.debug(f"Sinyal {symbol} {tf_u_norm} ditolak karena: {raw}")
                    else:
                        signal_count += 1
                        signal_id = sig_logger.log_signal(sig)
                        mode_str = "REVERSAL" if sig.signal_mode == "REVERSAL" else sig.trade_mode.upper()
                        logger.info(
                            f"{symbol} {tf_u_norm} 🚀 {sig.direction} [{mode_str}]"
                            f"  entry={sig.entry:.2f}  sl={sig.sl:.2f}  tp1={sig.tp:.2f}"
                            f"  RR={sig.rr:.2f}"
                            f"  trig={sig.trigger_score}/{sig.trigger_max}"
                            f"  conf={sig.confluence_score}"
                        )
                        rec = sig_logger.get_by_id(signal_id)
                        if rec:
                            tracker.add_signal(rec)
                        _refresh_report(sig_logger)
                        send_message(
                            s.telegram_token, s.telegram_chat_id,
                            format_signal(sig, signal_id=signal_id),
                        )

                if signal_count > 0:
                    reject_tracker.record_signal()

            reject_tracker.maybe_print_summary(
                symbol=s.symbols[0] if s.symbols else "XAUUSD"
            )
            _heartbeat_ping()
            time.sleep(s.poll_seconds)

    except KeyboardInterrupt:
        logger.info("Bot dihentikan (Ctrl+C).")
        _alert_offline("dibentikan manual (Ctrl+C)")
    except Exception:
        logger.exception("FATAL ERROR — bot berhenti tidak terduga")
        _alert_offline("crash tidak terduga")
    finally:
        tracker.stop()
        health.stop()
        shutdown()
        logger.info("MT5 disconnected. Bot selesai.")


if __name__ == "__main__":
    main()
