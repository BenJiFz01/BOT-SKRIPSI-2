"""update_hasil.py — CLI interaktif untuk update hasil sinyal (WIN/LOSS).

Jalankan: python -m src.infra.update_hasil
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.infra.signal_logger import SignalLogger


_logger = SignalLogger()

VALID_OUTCOMES = ["WIN_TP1", "WIN_TP2", "WIN_TP3", "LOSS", "CANCELLED"]
_SEP  = "=" * 72
_SEP2 = "-" * 72


def show_pending() -> None:
    pending = [r for r in _logger.get_trackable()
               if r.get("outcome") in ("PENDING", "SETUP")]
    if not pending:
        print("\n  Tidak ada sinyal PENDING / SETUP.\n")
        return
    print(f"\n{_SEP}")
    print(f"{'SINYAL PENDING & SETUP':^72}")
    print(_SEP)
    print(f"  {'No':<4} {'ID Sinyal':<38} {'TF':<5} {'Dir':<5} {'Entry':>9} {'RR':>5} {'Status':<10}")
    print(_SEP2)
    for i, r in enumerate(pending, 1):
        status = r.get("outcome", "PENDING")
        print(f"  {i:<4} {r['signal_id']:<38} {r['timeframe']:<5} "
              f"{r['direction']:<5} {float(r.get('entry',0)):>9.2f} "
              f"{float(r.get('rr',0)):>5.2f} {status:<10}")
    print(_SEP2)
    print(f"  Total: {len(pending)} sinyal\n")


def update(signal_id: str, outcome: str, price: float = 0.0, notes: str = "") -> None:
    outcome = outcome.upper().strip()
    if outcome not in VALID_OUTCOMES:
        print(f"\n  Outcome tidak valid. Pilihan: {', '.join(VALID_OUTCOMES)}\n")
        return
    if _logger.update_outcome(signal_id, outcome, price=price, notes=notes):
        print(f"\n  ✅ Updated: {signal_id} -> {outcome} @ {price}\n")
    else:
        print(f"\n  ❌ Signal ID tidak ditemukan: {signal_id}\n")
        show_pending()


def show_detail(signal_id: str) -> None:
    rec = _logger.get_by_id(signal_id)
    if not rec:
        print(f"\n  Signal ID tidak ditemukan: {signal_id}\n")
        return

    outcome = rec.get("outcome", "PENDING")
    icon    = {"WIN_TP1":"✅","WIN_TP2":"✅✅","WIN_TP3":"✅✅✅","LOSS":"❌","PENDING":"⏳","CANCELLED":"⚠️"}.get(outcome, "?")
    mode    = "Counter Trend" if rec.get("signal_mode") == "counter_trend" else "Trend Following"

    print(f"\n{_SEP}\n  DETAIL SINYAL: {signal_id}\n{_SEP}")
    print(f"  Waktu    : {rec.get('timestamp','')}  |  Candle: {rec.get('candle_close','')}")
    print(f"  Simbol   : {rec.get('symbol','')} {rec.get('timeframe','')} {rec.get('direction','')}  |  Mode: {mode}")
    print(f"\n  HARGA\n{_SEP2}")
    print(f"  Entry    : {float(rec.get('entry',0)):.2f}  |  SL: {float(rec.get('sl',0)):.2f}  ({rec.get('sl_method','')})")
    print(f"  TP1/2/3  : {float(rec.get('tp1',0)):.2f} / {float(rec.get('tp2',0)):.2f} / {float(rec.get('tp3',0)):.2f}")
    print(f"  RR       : {float(rec.get('rr',0)):.2f}  |  ATR: {float(rec.get('atr_value',0)):.4f}")
    print(f"\n  ANALISIS\n{_SEP2}")
    print(f"  Trigger  : {rec.get('trigger_score','')}  [{rec.get('trigger_notes','')}]")
    print(f"  Conf     : {rec.get('confluence_score','')}  [{rec.get('confluence_notes','')}]")
    print(f"  HTF Bias : {rec.get('htf_bias','')}")
    print(f"  Pattern  : {rec.get('pattern_names','') or '-'}  |  Fib: {rec.get('fib_detail','') or '-'}")
    print(f"  SnR      : {rec.get('snr_detail','') or '-'}  |  SnD: {rec.get('snd_detail','') or '-'}")
    print(f"  Div      : {rec.get('divergence_detail','') or '-'}  |  Sesi: {rec.get('session_name','')}")
    print(f"\n  HASIL\n{_SEP2}")
    print(f"  Outcome  : {icon} {outcome}  @  {float(rec.get('outcome_price',0)):.2f}  ({rec.get('outcome_time','')})")
    print(f"  TP Hit   : TP1={rec.get('tp1_hit_time','-') or '-'}  TP2={rec.get('tp2_hit_time','-') or '-'}  TP3={rec.get('tp3_hit_time','-') or '-'}")
    print(f"  SL Hit   : {rec.get('sl_hit_time','-') or '-'}")
    print(f"  Durasi   : {int(rec.get('duration_minutes',0) or 0)} menit  |  Catatan: {rec.get('notes','') or '-'}")
    print(f"{_SEP}\n")


def show_stats() -> None:
    s = _logger.get_stats()
    print(f"\n{_SEP}\n{'STATISTIK BOT TRADING':^72}\n{_SEP}")
    print(f"  Total: {s['total_signals']}  |  Pending: {s['pending']}  |  Decided: {s['decided']}")
    print(f"{_SEP2}")
    print(f"  WIN TP1: {s['win_tp1']}  WIN TP2: {s['win_tp2']}  WIN TP3: {s['win_tp3']}  LOSS: {s['losses']}  BATAL: {s['cancelled']}")
    print(f"{_SEP2}")
    print(f"  Win Rate: {s['win_rate_pct']}%  |  Avg RR: {s['avg_rr']}  |  Avg Durasi: {s['avg_duration_m']} menit")

    if s["by_timeframe"]:
        print(f"\n  Per Timeframe:")
        for tf, d in sorted(s["by_timeframe"].items()):
            dec = d["win"] + d["loss"]
            wr  = round(d["win"] / dec * 100, 1) if dec > 0 else 0
            print(f"    {tf:<5}: {d['win']}W {d['loss']}L ({wr}%) | pending={d['pending']}")

    if s["by_direction"]:
        print(f"\n  Per Arah:")
        for direc, d in s["by_direction"].items():
            dec = d["win"] + d["loss"]
            wr  = round(d["win"] / dec * 100, 1) if dec > 0 else 0
            print(f"    {direc:<5}: {d['win']}W {d['loss']}L ({wr}%)")

    if s.get("by_mode"):
        print(f"\n  Trend vs Counter:")
        for mode, d in s["by_mode"].items():
            dec   = d["win"] + d["loss"]
            wr    = round(d["win"] / dec * 100, 1) if dec > 0 else 0
            label = "Counter Trend" if mode == "counter_trend" else "Trend"
            print(f"    {label:<14}: {d['win']}W {d['loss']}L ({wr}%)")
    print(f"{_SEP}\n")


def show_tracker_status() -> None:
    pending = _logger.get_pending()
    if not pending:
        print("\n  Tidak ada sinyal yang sedang dimonitor.\n")
        return
    print(f"\n{_SEP}\n{'STATUS TRACKER':^72}\n{_SEP}")
    print(f"  {'No':<4} {'ID Sinyal':<38} {'Entry':>9} {'SL':>9} {'TP1':>9} {'Mode':<14}")
    print(_SEP2)
    for i, r in enumerate(pending, 1):
        mode = "Counter" if r.get("signal_mode") == "counter_trend" else "Trend"
        print(f"  {i:<4} {r.get('signal_id','?'):<38} {float(r.get('entry',0)):>9.2f} "
              f"{float(r.get('sl',0)):>9.2f} {float(r.get('tp1',0)):>9.2f} {mode:<14}")
    print(_SEP2)
    print(f"  {len(pending)} sinyal aktif. SignalTracker berjalan otomatis saat bot aktif.\n")


def make_report() -> None:
    try:
        from src.infra.laporan_excel import generate_report
        generate_report(_logger)
    except Exception as e:
        print(f"\n  Gagal membuat laporan: {e}\n")


def _cli() -> None:
    print(f"\n{_SEP}\n  {'BOT TRADING DSS — OUTCOME UPDATER':^68}\n{_SEP}")
    while True:
        print("\n  Menu:")
        print("    1. Lihat sinyal PENDING")
        print("    2. Update hasil sinyal (WIN/LOSS)")
        print("    3. Lihat detail satu sinyal")
        print("    4. Statistik win rate")
        print("    5. Status tracker")
        print("    6. Buat laporan Excel")
        print("    7. Keluar")

        choice = input("\n  Pilih (1-7): ").strip()

        if choice == "1":
            show_pending()
        elif choice == "2":
            show_pending()
            sid = input("  Signal ID: ").strip()
            if not sid:
                continue
            outcome = input(f"  Outcome ({'/'.join(VALID_OUTCOMES)}): ").strip().upper()
            price_s = input("  Harga (Enter=0): ").strip()
            price   = float(price_s) if price_s else 0.0
            dur_s   = input("  Durasi menit (Enter=hitung otomatis): ").strip()
            dur_m   = int(dur_s) if dur_s.isdigit() else 0
            notes   = input("  Catatan (opsional): ").strip()
            if _logger.update_outcome(sid, outcome, price=price, notes=notes, duration_m=dur_m):
                print(f"\n  ✅ Updated: {sid} -> {outcome} @ {price}"
                      f"{f' | durasi={dur_m} menit' if dur_m else ''}\n")
            else:
                print(f"\n  ❌ Signal ID tidak ditemukan: {sid}\n")
        elif choice == "3":
            sid = input("  Signal ID (Enter=pilih dari list): ").strip()
            if not sid:
                show_pending()
                sid = input("  Signal ID: ").strip()
            if sid:
                show_detail(sid)
        elif choice == "4":
            show_stats()
        elif choice == "5":
            show_tracker_status()
        elif choice == "6":
            make_report()
        elif choice == "7":
            print("\n  Keluar.\n")
            break
        else:
            print("  Pilihan tidak valid.")


if __name__ == "__main__":
    _cli()



