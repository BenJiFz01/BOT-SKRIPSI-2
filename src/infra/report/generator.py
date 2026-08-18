"""generator.py — Entry point pembuatan laporan Excel."""

import sys
from pathlib import Path

import openpyxl

_ROOT = Path(__file__).resolve().parents[4]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.infra.report.sheets import (
    sheet_akurasi_komponen, sheet_equity_curve, sheet_per_arah,
    sheet_per_tf, sheet_ringkasan, sheet_semua_sinyal, sheet_trend_vs_counter,
)
from src.infra.signal_logger import SignalLogger

REPORT_DIR = Path("logs/report")


def generate_report(logger: SignalLogger | None = None, silent: bool = False) -> Path:
    """
    Generate / update laporan Excel ke logs/report/laporan_trading.xlsx.
    File selalu ditimpa agar tidak menumpuk.

    Args:
        logger: SignalLogger instance. Jika None, dibuat baru.
        silent: Jika True, tidak print ke terminal (untuk auto-update dari main).

    Returns:
        Path ke file Excel.
    """
    if logger is None:
        logger = SignalLogger()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORT_DIR / "laporan_trading.xlsx"

    records = logger.get_all_records()
    stats   = logger.get_stats()

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    sheet_ringkasan(wb, stats, records)
    sheet_semua_sinyal(wb, records)
    sheet_per_tf(wb, stats)
    sheet_per_arah(wb, stats)
    sheet_trend_vs_counter(wb, stats)
    sheet_akurasi_komponen(wb, stats)
    sheet_equity_curve(wb, records)

    wb.save(out_path)

    if not silent:
        print(f"\n{'='*55}")
        print(f"  LAPORAN EXCEL: {out_path.resolve()}")
        print(f"{'='*55}\n")

    return out_path


def _cli() -> None:
    log     = SignalLogger()
    records = log.get_all_records()
    if not records:
        print("\n  Tidak ada data sinyal. Jalankan bot dulu.\n")
        return
    s = log.get_stats()
    print(f"\n  Total: {s['total_signals']} | Decided: {s['decided']} | Win rate: {s['win_rate_pct']}%")
    print("  Membuat laporan ...")
    out = generate_report(log)
    print(f"  Selesai: {out.resolve()}\n")


if __name__ == "__main__":
    _cli()
