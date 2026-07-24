"""
main.py — Entry point bot trading DSS Forex.

Jalankan: python -m src.main
"""
from __future__ import annotations

import time

import MetaTrader5 as mt5
from loguru import logger

from src.config.settings import load_settings
from src.engine.anytf_mta_engine import evaluate_any_tf_mta, scan_setup_plan
from src.features.indicators import add_indicators
from src.features.patterns import add_patterns
from src.infra.logger import setup_logger
from src.infra.laporan_excel import generate_report
from src.infra.scheduler import CandleCloseWatcher
from src.infra.signal_logger import SignalLogger
from src.infra.signal_tracker import SignalTracker
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


def _get_mt5_price(symbol: str) -> tuple[float, float]:
    """Ambil harga bid/ask terbaru dari MT5. Returns (bid, ask), keduanya 0.0 jika gagal."""
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return 0.0, 0.0
    return tick.bid, tick.ask


def _refresh_report(sig_logger: SignalLogger) -> None:
    """Update laporan Excel secara diam-diam. Skip jika file sedang dibuka di Excel."""
    try:
        generate_report(sig_logger, silent=True)
    except PermissionError:
        logger.debug("Report skip: laporan_trading.xlsx sedang dibuka di Excel")
    except Exception as e:
        logger.debug(f"Report refresh gagal (non-fatal): {e}")


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

    def _notify_fn(msg: str) -> None:
        """Kirim notifikasi tracker outcome ke Telegram."""
        try:
            send_message(s.telegram_token, s.telegram_chat_id, msg)
        except Exception as e:
            logger.warning(f"Tracker notify error: {e}")

    tracker = SignalTracker(
        sig_logger        = sig_logger,
        get_price_fn      = _get_mt5_price,
        send_notify_fn    = _notify_fn,
        refresh_report_fn = lambda: _refresh_report(sig_logger),
    )

    watcher = CandleCloseWatcher()

    # Cooldown setup plan — key=(symbol,tf,direction), value=datetime terakhir kirim
    _setup_plan_sent: dict[tuple, object] = {}

    try:
        acc = connect(s.mt5_login, s.mt5_password, s.mt5_server)
        logger.info(f"MT5 terhubung | login={acc.login} server={acc.server}")

        # Start tracker setelah MT5 terhubung (butuh price feed)
        tracker.start()

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
                f"| Session={'ON' if s.session_filter else 'OFF'}\n"
                f"Tracker  : ON ({tracker.get_active_count()} sinyal pending)"
            ),
        )

        while True:
            for symbol in s.symbols:
                ensure_symbol(symbol)

                # Kumpulkan data semua TF sekali per symbol per loop
                data_by_tf: dict = {}
                last_events: dict[str, object] = {}

                for trigger_tf in s.timeframes:
                    tf_u = trigger_tf.upper()
                    try:
                        df_trigger = _fetch_prepare(symbol, tf_u, s.bars)
                        data_by_tf[tf_u] = df_trigger
                    except Exception as e:
                        logger.error(f"Fetch error {symbol} {tf_u}: {e}")
                        continue

                    event = watcher.check(symbol, tf_u, df_trigger)
                    if event is not None:
                        last_events[tf_u] = event

                # ── Proses setiap TF yang ada candle close ─────────────────
                # Tracking sinyal live yang keluar di loop ini untuk deduplication setup plan
                _live_signals_this_loop: set[tuple] = set()

                for tf_u, event in last_events.items():
                    logger.info(f"[CLOSE] {symbol} {tf_u} | {event.closed_time}")
                    tf_u_norm  = tf_u.upper()
                    enabled_u  = [t.upper() for t in s.timeframes]
                    data_norm  = {k.upper(): v for k, v in data_by_tf.items()}

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
                        max_sl_points        = s.max_sl_points,
                        sl_pips              = s.sl_pips,
                        tp1_pips             = s.tp1_pips,
                        tp2_pips             = s.tp2_pips,
                        tp3_pips             = s.tp3_pips,
                        pip_size             = s.pip_size,
                        session_filter       = s.session_filter,
                        counter_trend_enabled  = s.counter_trend_enabled,
                        min_counter_confluence = s.min_counter_confluence,
                        counter_trend_min_rr   = s.counter_trend_min_rr,
                        counter_trend_tfs      = s.counter_trend_tfs,
                        scalping_min_trigger_score    = s.scalping_min_trigger_score,
                        scalping_min_confluence_score = s.scalping_min_confluence_score,
                        scalping_sl_atr_mult          = s.scalping_sl_atr_mult,
                        scalping_cooldown_bars         = s.scalping_cooldown_bars,
                        scalping_max_sl_points        = s.scalping_max_sl_points,
                        scalping_tp1_rr               = s.scalping_tp1_rr,
                        scalping_tp2_rr               = s.scalping_tp2_rr,
                        scalping_tp3_rr               = s.scalping_tp3_rr,
                    )

                    if sig is None:
                        why = data_norm.get(tf_u_norm, {}).attrs.get("reject_reason", "UNKNOWN")
                        logger.warning(f"[NO SIGNAL] {symbol} {tf_u} | {why}")
                    else:
                        # Log sinyal ke CSV/JSON
                        signal_id = sig_logger.log_signal(sig)
                        logger.success(
                            f"[SIGNAL] {sig.symbol} {sig.tf} {sig.direction} "
                            f"RR={sig.rr:.2f} T={sig.trigger_score}/6 "
                            f"C={sig.confluence_score} mode={sig.signal_mode} "
                            f"trade={sig.trade_mode} ID={signal_id}"
                        )

                        # Track untuk deduplication setup plan di loop ini
                        _live_signals_this_loop.add((symbol, sig.tf, sig.direction))

                        # Tambah ke tracker untuk monitoring otomatis
                        rec = sig_logger.get_by_id(signal_id)
                        if rec:
                            tracker.add_signal(rec)

                        # Update laporan Excel otomatis
                        _refresh_report(sig_logger)

                        # Kirim ke Telegram
                        send_message(
                            s.telegram_token,
                            s.telegram_chat_id,
                            format_signal(sig, signal_id=signal_id),
                        )

                # Scan setup plan setiap loop (tidak hanya saat candle close)
                # agar notif keluar lebih awal sebelum harga sampai zona entry
                # Cooldown per setup key = 15 menit agar tidak spam
                if data_by_tf:
                    try:
                        import pytz as _pytz
                        _now = __import__("datetime").datetime.now(_pytz.utc)

                        for _sp_scalping, _sp_anchor in [(True, "M15"), (False, "H1")]:
                            if _sp_anchor not in data_by_tf:
                                continue

                            setups = scan_setup_plan(
                                data_by_tf        = data_by_tf,
                                symbol            = symbol,
                                enabled_tfs       = s.timeframes,
                                min_confirm_votes = s.min_confirm_votes,
                                atr_min_pct       = s.atr_min_pct,
                                sl_atr_mult       = s.scalping_sl_atr_mult if _sp_scalping else s.sl_atr_mult,
                                tp1_rr            = s.scalping_tp1_rr if _sp_scalping else s.tp1_rr,
                                tp2_rr            = s.scalping_tp2_rr if _sp_scalping else s.tp2_rr,
                                tp3_rr            = s.scalping_tp3_rr if _sp_scalping else s.tp3_rr,
                                max_sl_points     = s.scalping_max_sl_points if _sp_scalping else s.max_sl_points,
                                sl_pips           = s.sl_pips,
                                tp1_pips          = s.tp1_pips,
                                tp2_pips          = s.tp2_pips,
                                tp3_pips          = s.tp3_pips,
                                pip_size          = s.pip_size,
                                session_filter    = s.session_filter,
                            )
                            for sp in setups:
                                sp_key      = (symbol, sp.tf, sp.direction)
                                sp_last_dt  = _setup_plan_sent.get(sp_key)

                                # Skip jika live signal arah+TF sama sudah keluar di loop ini
                                if sp_key in _live_signals_this_loop:
                                    logger.debug(
                                        f"[SETUP SKIP] {sp.symbol} {sp.tf} {sp.direction} "
                                        f"— live signal sudah keluar loop ini"
                                    )
                                    continue

                                # Cooldown 15 menit per (symbol, tf, direction)
                                if sp_last_dt is not None:
                                    elapsed = (_now - sp_last_dt).total_seconds() / 60
                                    if elapsed < 15:
                                        continue

                                _setup_plan_sent[sp_key] = _now
                                logger.info(
                                    f"[SETUP PLAN] {sp.symbol} {sp.tf} {sp.direction} "
                                    f"({sp.trade_mode}) exec={sp.exec_tf} RR={sp.rr:.2f}"
                                )
                                sp_id = sig_logger.log_signal(sp)
                                sp_rec = sig_logger.get_by_id(sp_id)
                                if sp_rec:
                                    tracker.add_signal(sp_rec)
                                send_message(
                                    s.telegram_token,
                                    s.telegram_chat_id,
                                    format_signal(sp, signal_id=sp_id),
                                )
                                _refresh_report(sig_logger)
                    except Exception as e:
                        logger.debug(f"Setup plan scan error: {e}")

            time.sleep(s.poll_seconds)

    except KeyboardInterrupt:
        logger.info("Bot dihentikan oleh user.")
    except Exception:
        logger.exception("FATAL ERROR")
    finally:
        tracker.stop()
        shutdown()
        logger.info("MT5 disconnected.")


if __name__ == "__main__":
    main()


