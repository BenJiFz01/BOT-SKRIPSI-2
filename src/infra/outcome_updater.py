"""
outcome_updater.py
==================
CLI interaktif untuk mencatat hasil sinyal (WIN/LOSS) setelah sinyal keluar.

Cara menjalankan (dari root project):
    python -m src.infra.outcome_updater
"""
from __future__ import annotations

import sys
from pathlib import Path

# Tambah root ke sys.path agar bisa dijalankan langsung
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.infra.signal_logger import SignalLogger


_logger = SignalLogger()

VALID_OUTCOMES = ["WIN_TP1", "WIN_TP2", "WIN_TP3", "LOSS", "CANCELLED"]


# ── Fungsi utama ──────────────────────────────────────────────────────

def show_pending() -> None:
    """Tampilkan semua sinyal yang masih PENDING."""
    pending = _logger.get_pending()
    if not pending:
        print("\nTidak ada sinyal PENDING.\n")
        return

    sep = "-" * 72
    print(f"\n{sep}")
    print(f"{'SINYAL PENDING':^72}")
    print(sep)
    print(f"{'ID':<35} {'Sym':<8} {'TF':<5} {'Dir':<5} {'Entry':>9} {'RR':>5}")
    print(sep)
    for r in pending:
        print(
            f"{r['signal_id']:<35} "
            f"{r['symbol']:<8} "
            f"{r['timeframe']:<5} "
            f"{r['direction']:<5} "
            f"{float(r.get('entry', 0)):>9.2f} "
            f"{float(r.get('rr', 0)):>5.2f}"
        )
    print(sep)
    print(f"Total: {len(pending)} sinyal pending\n")


def show_stats() -> None:
    """Tampilkan statistik win rate di terminal."""
    s = _logger.get_stats()
    sep  = "=" * 52
    sep2 = "-" * 52
    print(f"\n{sep}")
    print(f"{'STATISTIK BOT TRADING':^52}")
    print(sep)
    print(f"  Total sinyal     : {s['total_signals']}")
    print(f"  Pending          : {s['pending']}")
    print(f"  Sudah dievaluasi : {s['decided']}")
    print(sep2)
    print(f"  WIN TP1          : {s['win_tp1']}")
    print(f"  WIN TP2          : {s['win_tp2']}")
    print(f"  WIN TP3          : {s['win_tp3']}")
    print(f"  LOSS             : {s['losses']}")
    print(f"  BATAL            : {s['cancelled']}")
    print(sep2)
    print(f"  Win Rate         : {s['win_rate_pct']}%")
    print(f"  Avg RR           : {s['avg_rr']}")
    print(f"  Best RR          : {s['best_rr']}")

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

    print(f"{sep}\n")


def update(
    signal_id: str,
    outcome:   str,
    price:     float = 0.0,
    notes:     str   = "",
) -> None:
    """
    Perbarui hasil sinyal.

    Args:
        signal_id: ID sinyal (format: XAUUSD_H1_20260720_140000).
        outcome:   WIN_TP1 / WIN_TP2 / WIN_TP3 / LOSS / CANCELLED.
        price:     Harga saat outcome terjadi (opsional).
        notes:     Catatan tambahan (opsional).
    """
    outcome = outcome.upper().strip()
    if outcome not in VALID_OUTCOMES:
        print(f"Outcome tidak valid: '{outcome}'")
        print(f"Pilihan: {', '.join(VALID_OUTCOMES)}")
        return

    if _logger.update_outcome(signal_id, outcome, price=price, notes=notes):
        print(f"Updated: {signal_id} -> {outcome} @ {price}")
    else:
        print(f"Signal ID tidak ditemukan: {signal_id}")
        show_pending()


# ── CLI interaktif ────────────────────────────────────────────────────

def _cli() -> None:
    print("\n" + "=" * 40)
    print("  BOT TRADING -- OUTCOME UPDATER")
    print("=" * 40)

    while True:
        print("\nMenu:")
        print("  1. Lihat sinyal PENDING")
        print("  2. Update hasil sinyal")
        print("  3. Lihat statistik win rate")
        print("  4. Keluar")

        choice = input("\nPilih (1-4): ").strip()

        if choice == "1":
            show_pending()

        elif choice == "2":
            show_pending()
            sid = input("Signal ID: ").strip()
            if not sid:
                continue

            print(f"Outcome ({'/'.join(VALID_OUTCOMES)}): ", end="")
            outcome = input().strip().upper()

            price_str = input("Harga saat outcome (Enter = 0): ").strip()
            price = float(price_str) if price_str else 0.0

            notes = input("Catatan (opsional): ").strip()
            update(sid, outcome, price, notes)

        elif choice == "3":
            show_stats()

        elif choice == "4":
            print("Keluar.\n")
            break

        else:
            print("Pilihan tidak valid.")


if __name__ == "__main__":
    _cli()
