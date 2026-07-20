"""
main.py
=======
Entry point bot trading DSS Forex.

Cara menjalankan (dari root project):
    python -m src.main

Alur eksekusi:
    1. Setup logger dan baca konfigurasi
    2. Koneksi ke MetaTrader 5
    3. Kirim notifikasi "BOT ONLINE" ke Telegram
    4. Loop: setiap POLL_SECONDS detik, cek candle close per TF
    5. Jika ada candle close -> evaluasi sinyal semua TF
    6. Jika sinyal valid -> log ke CSV + kirim ke Telegram
"""
from __future__ import annotations

import time

from loguru import logger

from src.config.settings import load_settings
from src.engine.signal_engine import evaluate_signal
from src.features.indicators import add_indicators
from src.features.patterns import add_patterns
from src.infra.logger import setup_logger
from src.infra.scheduler import CandleCloseWatcher
from src.infra.signal_logger import SignalLogger
from src.mt5.connector import connect, shutdown
from src.mt5.market_data import ensure_symbol, fetch_ohlc
from src.notify.telegram import send_message
from src.notify.templates import format_signal


def _fetch_prepare(symbol: str, tf: str, bars: int):
    """Ambil data OHLC dari MT5, tambahkan indikator dan pattern."""
    df = fetch_ohlc(symbol, tf, bars).sort_values("time").reset_index(drop=True)
    df = add_indicators(df)
    df = add_patterns(df)
    return df


def main() -> None:
    setup_logger()
    logger.info("Logger aktif")

    s = load_settings()
    logger.info(
        f"BOT START | symbols={s.symbols} TFs={s.timeframes} "
        f"bars={s.bars} poll={s.poll_seconds}s"
    )
    logger.info(
        f"PARAMS | RR>={s.min_rr} trigger>={s.min_trigger_score}/6 "
        f"conf>={s.min_confluence_score} cooldown={s.cooldown_bars}bar "
        f"session_filter={s.session_filter}"
    )

    sig_logger = SignalLogger()
    logger.info("SignalLogger aktif -> logs/signal_history.csv")

    watcher = CandleCloseWatcher()

    try:
        acc = connect(s.mt5_login, s.mt5_password, s.mt5_server)
        logger.info(f"MT5 terhubung | login={acc.login} server={acc.server}")

        send_message(
            s.telegram_token,
            s.telegram_chat_id,
            (
                "<b>BOT TRADING ONLINE</b>\n\n"
                f"Account  : <code>{acc.login}</code>\n"
                f"Server   : <code>{acc.server}</code>\n"
                f"Symbols  : {', '.join(s.symbols)}\n"
                f"TFs      : {', '.join(s.timeframes)}\n\n"
                f"RR>={s.min_rr} | Trigger>={s.min_trigger_score}/6 "
                f"| Conf>={s.min_confluence_score} "
                f"| Cooldown={s.cooldown_bars}bar "
                f"| Session={'ON' if s.session_filter else 'OFF'}"
            ),
        )

        while True:
            for symbol in s.symbols:
                ensure_symbol(symbol)

                for trigger_tf in s.timeframes:
                    tf_u = trigger_tf.upper()

                    try:
                        df_trigger = _fetch_prepare(symbol, tf_u, s.bars)
                    except Exception as e:
                        logger.error(f"Fetch error {symbol} {tf_u}: {e}")
                        continue

                    event = watcher.check(symbol, tf_u, df_trigger)
                    if event is None:
                        continue

                    logger.info(f"[CLOSE] {symbol} {tf_u} | {event.closed_time}")

                    # Kumpulkan data semua TF untuk analisis HTF
                    data_by_tf = {tf_u: df_trigger}
                    for tf in s.timeframes:
                        tf2 = tf.upper()
                        if tf2 == tf_u:
                            continue
                        try:
                            data_by_tf[tf2] = _fetch_prepare(symbol, tf2, s.bars)
                        except Exception as e:
                            logger.debug(f"Fetch {tf2} gagal: {e}")

                    sig = evaluate_signal(
                        data_by_tf           = data_by_tf,
                        symbol               = symbol,
                        trigger_tf           = tf_u,
                        enabled_tfs          = s.timeframes,
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
                        sl_pips              = s.sl_pips,
                        tp1_pips             = s.tp1_pips,
                        tp2_pips             = s.tp2_pips,
                        tp3_pips             = s.tp3_pips,
                        pip_size             = s.pip_size,
                        session_filter       = s.session_filter,
                    )

                    if sig is None:
                        why = data_by_tf.get(tf_u, {}).attrs.get("reject_reason", "UNKNOWN")
                        logger.warning(f"[NO SIGNAL] {symbol} {tf_u} | {why}")
                        continue

                    signal_id = sig_logger.log_signal(sig)
                    logger.success(
                        f"[SIGNAL] {sig.symbol} {sig.tf} {sig.direction} "
                        f"RR={sig.rr:.2f} T={sig.trigger_score}/6 "
                        f"C={sig.confluence_score} ID={signal_id}"
                    )

                    send_message(
                        s.telegram_token,
                        s.telegram_chat_id,
                        format_signal(sig, signal_id=signal_id),
                    )

            time.sleep(s.poll_seconds)

    except KeyboardInterrupt:
        logger.info("Bot dihentikan oleh user.")
    except Exception:
        logger.exception("FATAL ERROR")
    finally:
        shutdown()
        logger.info("MT5 disconnected.")


if __name__ == "__main__":
    main()
