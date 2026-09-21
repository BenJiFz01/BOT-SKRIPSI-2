"""main.py — Entry point bot trading DSS Forex.

Jalankan: python -m src.main

Alur:
  1. Fetch OHLCV + indikator untuk semua TF
  2. Pada setiap candle close → evaluate_any_tf_mta()
  3. Kirim sinyal ke Telegram
  4. Tracker memantau outcome sinyal yang terkirim
"""
import re
import time
from datetime import datetime

import MetaTrader5 as mt5
import pandas as pd
import pytz
from loguru import logger

from src.config.settings import load_settings
from src.engine.anytf_mta_engine import evaluate_any_tf_mta
from src.features.indicators import add_indicators
from src.features.patterns import add_patterns
from src.infra.logger import setup_logger
from src.infra.reject_tracker import RejectTracker
from src.infra.report.generator import generate_report
from src.infra.scheduler import CandleCloseWatcher
from src.infra.signal_logger import SignalLogger
from src.infra.signal_tracker import SignalTracker
from src.mt5.connector import connect, shutdown
from src.mt5.market_data import ensure_symbol, fetch_ohlc
from src.notify.telegram import send_message
from src.notify.templates import format_signal


# ── Reject label utilities ────────────────────────────────────────────────────


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
            return f"Confluence rendah: {skor} (min={threshold})"
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
    if u.startswith("SLTP_NONE"):
        return "SL/TP tidak dapat dihitung"

    return raw.split(":")[0]


def _short_reject_with_df(raw: str, df: pd.DataFrame | None = None) -> str:
    if not raw or raw in ("INIT", "OK"):
        return raw
    u = raw.upper()
    if u.startswith("CT_EMA200_FAIL") or u.startswith("EMA200_WAJIB"):
        # CT_EMA200_FAIL tidak menyertakan dir= di raw, tapi bisa dibaca dari df
        # Jika tidak ada, tampilkan "CT" sebagai label (bukan "?")
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


# ── Utilities ─────────────────────────────────────────────────────────────────

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


# ── Main loop ─────────────────────────────────────────────────────────────────

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
        f"PARAMS SCALPING | RR_struct>={s.scalping_min_rr} TP1={s.scalping_tp1_atr_mult}×ATR "
        f"CT_RR>={s.scalping_counter_trend_min_rr} "
        f"trig>={s.scalping_min_trigger_score} conf>={s.scalping_min_confluence_score} "
        f"cooldown M5={s.scalping_cooldown_bars_m5}bar M15={s.scalping_cooldown_bars_m15}bar"
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

    try:
        acc = connect(s.mt5_login, s.mt5_password, s.mt5_server, s.mt5_terminal_path)
        logger.info(f"MT5 terhubung | login={acc.login} server={acc.server}")
        tracker.start()

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
                f"| Cooldown={s.cooldown_bars}bar\n"
                f"<b>Scalping</b>: RR_struct>={s.scalping_min_rr} | TP1={s.scalping_tp1_atr_mult}×ATR "
                f"| CT_RR>={s.scalping_counter_trend_min_rr} "
                f"| Trig>={s.scalping_min_trigger_score} | Conf>={s.scalping_min_confluence_score}\n"
                f"Session  : {'ON' if s.session_filter else 'OFF'}\n"
                f"Tracker  : ON ({tracker.get_active_count()} sinyal pending)"
            ),
        )

        while True:
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
                    continue   # tidak ada candle close — lanjut ke symbol berikutnya
                               # TANPA sleep terpisah; satu-satunya sleep ada di bawah while True

                bid, ask = _get_mt5_tick(symbol)
                tfs_closing = ", ".join(last_events.keys())
                logger.info(f"{symbol} | Candle close: {tfs_closing} | bid={bid:.2f} ask={ask:.2f}")
                reject_tracker.record_candle()
                signal_count = 0

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
                            scalping_min_rr              = s.scalping_min_rr,
                            scalping_counter_trend_min_rr= s.scalping_counter_trend_min_rr,
                            market_transition_adx_block  = s.market_transition_adx_block,
                            market_transition_adx_gray   = s.market_transition_adx_gray,
                            scalping_h1_only             = s.scalping_h1_only,
                            intraday_require_d1          = s.intraday_require_d1,
                        )
                    except Exception as eval_err:
                        # Exception di satu TF/candle tidak boleh mematikan seluruh bot.
                        # Log sebagai error, skip candle ini, lanjut ke TF berikutnya.
                        logger.error(f"[EVAL ERROR] {symbol} {tf_u_norm}: {eval_err}", exc_info=True)
                        continue

                    if sig is None:
                        raw    = data_norm.get(tf_u_norm, pd.DataFrame()).attrs.get("reject_reason", "UNKNOWN")
                        df_cur = data_norm.get(tf_u_norm)
                        logger.info(f"{symbol} {tf_u_norm:<3} ✗  {_short_reject_with_df(raw, df_cur)}")
                        logger.debug(f"{tf_u_norm} raw: {raw[:200]}")
                        reject_tracker.record_reject(symbol=symbol, tf=tf_u_norm, raw=raw, df=df_cur)
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
            time.sleep(s.poll_seconds)

    except KeyboardInterrupt:
        logger.info("Bot dihentikan (Ctrl+C).")
    except Exception:
        logger.exception("FATAL ERROR — bot berhenti tidak terduga")
    finally:
        tracker.stop()
        shutdown()
        logger.info("MT5 disconnected. Bot selesai.")


if __name__ == "__main__":
    main()
