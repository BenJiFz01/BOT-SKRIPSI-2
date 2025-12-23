from __future__ import annotations

import os
import sys
import time
import traceback
from loguru import logger

from src.config.settings import load_settings
from src.infra.logger import setup_logger
from src.mt5.connector import connect, shutdown
from src.mt5.market_data import ensure_symbol, fetch_ohlc
from src.features.indicators import add_indicators
from src.features.patterns import add_patterns
from src.infra.scheduler import CandleCloseWatcher
from src.engine.signal_engine import evaluate_signal
from src.notify.telegram import send_message
from src.notify.templates import format_signal


def _fetch_prepare(symbol: str, tf: str, bars: int):
    df = fetch_ohlc(symbol, tf, bars).sort_values("time").reset_index(drop=True)
    df = add_indicators(df)
    df = add_patterns(df)
    return df


def main() -> None:
    print("MAIN STARTED", flush=True)
    print("PY:", sys.executable, flush=True)
    print("CWD:", os.getcwd(), flush=True)

    setup_logger()
    logger.info("LOGGER OK")

    s = load_settings()
    logger.info(
        f"SETTINGS symbols={s.symbols} TFs={s.timeframes} "
        f"BARS={s.bars} MIN_RR={s.min_rr} poll={s.poll_seconds}s"
    )

    watcher = CandleCloseWatcher()

    try:
        acc = connect(s.mt5_login, s.mt5_password, s.mt5_server)
        logger.info(f"MT5 CONNECTED login={acc.login} server={acc.server}")

        send_message(
            s.telegram_token,
            s.telegram_chat_id,
            (
                "🚀 *BOT TRADING IS ONLINE*\n\n"
                f"Account: `{acc.login}`\n"
                f"Server: `{acc.server}`\n"
                f"Symbols: {', '.join(s.symbols)}\n"
                f"TFs: {', '.join(s.timeframes)}\n"
                f"BARS: `{s.bars}` | MIN_RR: `{s.min_rr}`\n"
            ),
        )

        while True:
            for symbol in s.symbols:
                ensure_symbol(symbol)

                for trigger_tf in s.timeframes:
                    tf_u = trigger_tf.upper()

                    # ===== FETCH DATA TRIGGER TF (SEKALI) =====
                    df_trigger = _fetch_prepare(symbol, tf_u, s.bars)

                    event = watcher.check(symbol, tf_u, df_trigger)
                    if event is None:
                        continue  # anti spam: tidak log tiap tick

                    # ===== EVENT PENTING: CANDLE CLOSE =====
                    logger.info(f"[CLOSE] {symbol} {tf_u} time={event.closed_time}")

                    # ===== PREPARE DATA SEMUA TF =====
                    data_by_tf: dict[str, any] = {tf_u: df_trigger}
                    missing_tf: list[str] = []

                    for tf in s.timeframes:
                        tf2 = tf.upper()
                        if tf2 == tf_u:
                            continue
                        try:
                            data_by_tf[tf2] = _fetch_prepare(symbol, tf2, s.bars)
                        except Exception:
                            missing_tf.append(tf2)

                    if missing_tf:
                        logger.warning(f"[SKIP] {symbol} {tf_u} missing TF data: {missing_tf}")
                        continue

                    # ===== EVALUATE SIGNAL =====
                    sig = evaluate_signal(
                        data_by_tf=data_by_tf,
                        symbol=symbol,
                        trigger_tf=tf_u,
                        enabled_tfs=s.timeframes,
                        min_rr=s.min_rr,
                        min_confirm_votes=1,
                    )

                    # ===== HASIL ENGINE (TIDAK SPAM) =====
                    if sig is None:
                        # ambil alasan reject dari attrs yang diset oleh anytf engine
                        why = data_by_tf[tf_u].attrs.get("reject_reason", "UNKNOWN_REJECT")
                        logger.warning(f"[NO SIGNAL] {symbol} {tf_u} | {why}")
                        continue

                    # ===== SIGNAL VALID =====
                    logger.success(
                        f"[SIGNAL] {sig.symbol} {sig.tf} {sig.direction} RR={sig.rr:.2f}"
                    )

                    # detail alasan sinyal hanya DEBUG (tidak muncul kalau level INFO)
                    logger.debug(f"SIGNAL DETAIL: {sig.reason}")

                    msg = format_signal(sig)
                    send_message(s.telegram_token, s.telegram_chat_id, msg)

            time.sleep(s.poll_seconds)

    except KeyboardInterrupt:
        logger.warning("STOPPED by user (Ctrl+C)")

    except Exception:
        logger.exception("FATAL ERROR")

    finally:
        shutdown()
        logger.info("MT5 SHUTDOWN")


if __name__ == "__main__":
    main()
