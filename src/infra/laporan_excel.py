"""
laporan_excel.py
===================
Generator laporan statistik trading dalam 1 file Excel (.xlsx) untuk skripsi.

Cara menjalankan (dari root project):
    python -m src.infra.laporan_excel

Output:
    logs/report/laporan_trading_YYYYMMDD_HHMMSS.xlsx

Sheet dalam file Excel:
    1. Ringkasan       -- statistik umum: win rate, avg RR, avg durasi, dll
    2. Semua Sinyal    -- histori lengkap semua sinyal + status TP1/TP2/TP3/SL
    3. Per Timeframe   -- win rate per TF (H1, H4, dll)
    4. Per Arah        -- win rate BUY vs SELL
    5. Trend vs Counter-- trend following vs counter trend
    6. Akurasi Komponen-- seberapa akurat tiap komponen analisis teknikal
    7. Equity Curve    -- kumulatif WIN (+1) dan LOSS (-1) per sinyal
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import openpyxl
from openpyxl.chart import BarChart, LineChart, PieChart, Reference
from openpyxl.styles import (
    Alignment, Border, Font, PatternFill, Side
)
from openpyxl.utils import get_column_letter

# Pastikan bisa dijalankan langsung
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.infra.signal_logger import SignalLogger

REPORT_DIR = Path("logs/report")
C_HEADER_BLUE   = "1F4E79"   # header kolom (putih tulisan)
C_HEADER_GOLD   = "C9A000"   # header sheet judul
C_WIN           = "E2EFDA"   # background baris WIN (hijau muda)
C_LOSS          = "FCE4D6"   # background baris LOSS (merah muda)
C_PENDING       = "FFF2CC"   # background baris PENDING (kuning muda)
C_COUNTER       = "DAE3F3"   # background baris counter trend (biru muda)
C_SUBHEADER     = "D6E4F0"   # sub-header tabel

def _to_wib(iso_str: str) -> str:
    """Konversi ISO timestamp UTC ke format WIB (UTC+7) untuk tampilan Excel."""
    if not iso_str:
        return ""
    try:
        from datetime import timezone, timedelta
        s = iso_str[:19]
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        wib = dt.astimezone(timezone(timedelta(hours=7)))
        return wib.strftime("%d/%m/%Y %H:%M WIB")
    except Exception:
        return iso_str[:19]


def generate_report(logger: SignalLogger | None = None, silent: bool = False) -> Path:
    """
    Generate / update laporan Excel ke logs/report/laporan_trading.xlsx.
    File selalu ditimpa (bukan dibuat baru) agar tidak menumpuk.

    Args:
        logger: Instance SignalLogger. Jika None, buat baru.
        silent: Jika True, tidak print output ke terminal (untuk auto-update dari main).

    Returns:
        Path ke file Excel.
    """
    if logger is None:
        logger = SignalLogger()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    # Nama file tetap — ditimpa setiap update, tidak dibuat file baru
    out_path = REPORT_DIR / "laporan_trading.xlsx"

    records = logger.get_all_records()
    stats   = logger.get_stats()

    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # hapus sheet default kosong

    _sheet_ringkasan(wb, stats, records)
    _sheet_semua_sinyal(wb, records)
    _sheet_per_tf(wb, stats)
    _sheet_per_arah(wb, stats)
    _sheet_trend_vs_counter(wb, stats)
    _sheet_akurasi_komponen(wb, stats)
    _sheet_equity_curve(wb, records)

    wb.save(out_path)

    if not silent:
        print(f"\n{'='*60}")
        print(f"  LAPORAN EXCEL BERHASIL DIBUAT")
        print(f"{'='*60}")
        print(f"  File : {out_path.resolve()}")
        print(f"  Sheet: 7 sheet (Ringkasan, Semua Sinyal, Per TF,")
        print(f"         Per Arah, Trend vs Counter, Akurasi Komponen,")
        print(f"         Equity Curve)")
        print(f"{'='*60}\n")

    return out_path

def _sheet_ringkasan(wb, stats: dict, records: list[dict]) -> None:
    """
    Sheet ringkasan dengan:
    - Layout 2 kolom (kiri: statistik, kanan: navigasi + grafik)
    - Rumus Excel untuk win rate (=B12/B11 dll) agar auto-update di Excel
    - Grafik Pie distribusi outcome
    - Grafik Bar win rate per TF
    - Navigasi hyperlink ke semua sheet
    """
    ws = wb.create_sheet("Ringkasan")

    # Lebar kolom
    ws.column_dimensions["A"].width = 2     # margin kiri
    ws.column_dimensions["B"].width = 28    # label
    ws.column_dimensions["C"].width = 16    # nilai
    ws.column_dimensions["D"].width = 2     # pemisah
    ws.column_dimensions["E"].width = 28    # navigasi label
    ws.column_dimensions["F"].width = 20    # navigasi link
    ws.row_dimensions[1].height = 36
    ws.row_dimensions[2].height = 20
    ws.row_dimensions[3].height = 18
    ws.merge_cells("A1:F1")
    _set(ws, 1, 1, "LAPORAN PERFORMA SISTEM DSS TRADING XAU/USD",
         bold=True, size=15, bg=C_HEADER_GOLD, fg="FFFFFF", align="center")

    ws.merge_cells("A2:F2")
    _set(ws, 2, 1,
         f"Dibuat: {datetime.now().strftime('%Y-%m-%d %H:%M:%S WIB')}  |  "
         f"Skripsi — M. Dzikri Zen | Informatika UNTIRTA",
         italic=True, align="center", bg="FFF8E7")

    ws.merge_cells("A3:F3")  # spacer
    r = 4

    def section_left(title: str) -> None:
        nonlocal r
        ws.merge_cells(f"B{r}:C{r}")
        _set(ws, r, 2, title, bold=True, size=11, bg=C_HEADER_BLUE, fg="FFFFFF")
        ws.row_dimensions[r].height = 18
        r += 1

    def data_row(label: str, value, formula: str | None = None,
                 pct: bool = False, bold_val: bool = True) -> int:
        """Tulis satu baris data. Return nomor baris yang diisi."""
        nonlocal r
        _set(ws, r, 2, label)
        cell = ws.cell(row=r, column=3)
        if formula:
            cell.value = formula
        else:
            cell.value = value
        cell.font      = Font(bold=bold_val, size=11)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        if pct and formula:
            cell.number_format = "0.0%"
        elif isinstance(value, float) and not pct:
            cell.number_format = "0.00"
        current_r = r
        r += 1
        return current_r

    def blank_left() -> None:
        nonlocal r
        r += 1
    section_left("A.  TOTAL SINYAL")
    r_total      = data_row("Total Sinyal Dihasilkan", stats["total_signals"])
    r_decided    = data_row("Sudah Dievaluasi",        stats["decided"])
    r_pending    = data_row("Masih Pending",            stats["pending"])
    r_cancelled  = data_row("Dibatalkan",               stats["cancelled"])
    blank_left()
    section_left("B.  DISTRIBUSI OUTCOME")
    r_wtp1 = data_row("WIN TP1",   stats["win_tp1"])
    r_wtp2 = data_row("WIN TP2",   stats["win_tp2"])
    r_wtp3 = data_row("WIN TP3",   stats["win_tp3"])
    # Total WIN pakai rumus SUM
    r_twin = data_row("Total WIN", stats["total_wins"],
                      formula=f"=SUM(C{r_wtp1}:C{r_wtp3})")
    r_loss = data_row("LOSS",      stats["losses"])
    blank_left()
    section_left("C.  PERFORMA")
    # Win Rate = Total WIN / Decided  (pakai rumus)
    r_wr = data_row(
        "Win Rate",
        stats["win_rate_pct"] / 100,
        formula=f"=IFERROR(C{r_twin}/C{r_decided},0)",
        pct=True,
    )
    ws.cell(row=r_wr, column=3).number_format = "0.0%"

    r_avgRR  = data_row("Average RR Realized", stats["avg_rr"])
    r_avgDur = data_row("Avg Durasi Sinyal (menit)", stats["avg_duration_m"])
    blank_left()
    by_mode = stats.get("by_mode", {})
    if by_mode:
        section_left("D.  TREND vs COUNTER TREND")
        for mode, d in by_mode.items():
            label = "Counter Trend" if mode == "counter_trend" else "Trend Following"
            dec   = d["win"] + d["loss"]
            wr    = round(d["win"] / dec * 100, 1) if dec > 0 else 0.0
            data_row(f"{label} — Total Sinyal", d["total"])
            data_row(f"{label} — WIN",          d["win"])
            data_row(f"{label} — LOSS",         d["loss"])
            r_mode_wr = data_row(
                f"{label} — Win Rate",
                wr / 100,
                pct=True,
            )
            ws.cell(row=r_mode_wr, column=3).number_format = "0.0%"
            ws.cell(row=r_mode_wr, column=3).value = wr / 100
        blank_left()

    # Warnai sel Win Rate berdasarkan nilai
    wr_cell = ws.cell(row=r_wr, column=3)
    wr_val  = stats["win_rate_pct"]
    wr_cell.fill = PatternFill("solid", fgColor=(C_WIN if wr_val >= 50 else C_LOSS))

    # Border blok kiri
    _auto_border(ws, 4, 2, r - 1, 3)
    nav_r = 4
    ws.merge_cells(f"E{nav_r}:F{nav_r}")
    _set(ws, nav_r, 5, "NAVIGASI CEPAT", bold=True, size=11,
         bg=C_HEADER_BLUE, fg="FFFFFF", align="center")
    nav_r += 1

    nav_items = [
        ("Semua Sinyal",      "Semua Sinyal",      "Histori semua sinyal + TP/SL hit"),
        ("Per Timeframe",     "Per Timeframe",     "Win rate H1, H4, dll"),
        ("Per Arah",          "Per Arah",          "BUY vs SELL"),
        ("Trend vs Counter",  "Trend vs Counter",  "Trend Following vs Counter Trend"),
        ("Akurasi Komponen",  "Akurasi Komponen",  "Akurasi tiap indikator"),
        ("Equity Curve",      "Equity Curve",      "Grafik kumulatif WIN/LOSS"),
    ]
    for sheet_name, display, desc in nav_items:
        # Hyperlink ke sheet tujuan
        link_cell = ws.cell(row=nav_r, column=5, value=f"▶  {display}")
        link_cell.hyperlink       = f"#{sheet_name}!A1"
        link_cell.font            = Font(color="1F4E79", bold=True,
                                         underline="single", size=11)
        link_cell.alignment       = Alignment(vertical="center")
        ws.cell(row=nav_r, column=6, value=desc).font = Font(italic=True, size=10)
        ws.row_dimensions[nav_r].height = 18
        nav_r += 1

    nav_r += 1
    ws.merge_cells(f"E{nav_r}:F{nav_r}")
    _set(ws, nav_r, 5, "KETERANGAN WARNA", bold=True, size=11,
         bg=C_HEADER_BLUE, fg="FFFFFF", align="center")
    nav_r += 1
    for label, color in [
        ("WIN (TP1 / TP2 / TP3)",   C_WIN),
        ("LOSS",                     C_LOSS),
        ("PENDING (belum resolve)",  C_PENDING),
        ("Counter Trend",            C_COUNTER),
    ]:
        _set(ws, nav_r, 5, f"  {label}", bg=color)
        ws.merge_cells(f"E{nav_r}:F{nav_r}")
        nav_r += 1

    _auto_border(ws, 4, 5, nav_r - 1, 6)
    # Data source: baris outcome di sheet ini (kolom B=label, C=nilai)
    # Siapkan data pie di area tersembunyi (kolom H:I)
    pie_labels = ["WIN TP1", "WIN TP2", "WIN TP3", "LOSS", "Pending"]
    pie_values = [
        stats["win_tp1"], stats["win_tp2"], stats["win_tp3"],
        stats["losses"], stats["pending"],
    ]
    pie_start = 4
    _set(ws, pie_start,     8, "Kategori", bold=True, bg=C_SUBHEADER)
    _set(ws, pie_start,     9, "Jumlah",   bold=True, bg=C_SUBHEADER)
    for i, (lbl, val) in enumerate(zip(pie_labels, pie_values)):
        _set(ws, pie_start + 1 + i, 8, lbl)
        ws.cell(row=pie_start + 1 + i, column=9, value=val)

    # Font kecil untuk area data tersembunyi
    for row_i in range(pie_start, pie_start + 6):
        for col_i in (8, 9):
            ws.cell(row=row_i, column=col_i).font = Font(size=9, color="AAAAAA")

    pie = PieChart()
    pie.title  = "Distribusi Outcome Sinyal"
    pie.style  = 10
    pie.width  = 14
    pie.height = 10

    pie_data   = Reference(ws, min_col=9, min_row=pie_start,
                              max_row=pie_start + 5)
    pie_labels_ref = Reference(ws, min_col=8, min_row=pie_start + 1,
                                   max_row=pie_start + 5)
    pie.add_data(pie_data, titles_from_data=True)
    pie.set_categories(pie_labels_ref)
    ws.add_chart(pie, "E14")
    by_tf    = stats.get("by_timeframe", {})
    bar_start = pie_start + 8
    _set(ws, bar_start, 8, "Timeframe", bold=True, bg=C_SUBHEADER)
    _set(ws, bar_start, 9, "Win Rate %", bold=True, bg=C_SUBHEADER)
    for i, (tf, d) in enumerate(sorted(by_tf.items())):
        dec = d["win"] + d["loss"]
        wr  = round(d["win"] / dec * 100, 1) if dec > 0 else 0.0
        ws.cell(row=bar_start + 1 + i, column=8, value=tf)
        ws.cell(row=bar_start + 1 + i, column=9, value=wr)
        for col_i in (8, 9):
            ws.cell(row=bar_start + 1 + i, column=col_i).font = Font(size=9, color="AAAAAA")

    n_tf = len(by_tf)
    if n_tf > 0:
        bar = BarChart()
        bar.type    = "col"
        bar.title   = "Win Rate per Timeframe (%)"
        bar.y_axis.title = "Win Rate (%)"
        bar.x_axis.title = "Timeframe"
        bar.style   = 10
        bar.width   = 14
        bar.height  = 10

        bar_data   = Reference(ws, min_col=9, min_row=bar_start,
                                   max_row=bar_start + n_tf)
        bar_labels = Reference(ws, min_col=8, min_row=bar_start + 1,
                                   max_row=bar_start + n_tf)
        bar.add_data(bar_data, titles_from_data=True)
        bar.set_categories(bar_labels)
        ws.add_chart(bar, "E28")

def _sheet_semua_sinyal(wb, records: list[dict]) -> None:
    ws = wb.create_sheet("Semua Sinyal")

    headers = [
        "No", "Signal ID", "Tanggal (WIB)", "Simbol", "TF", "Arah", "Mode",
        "Entry", "Stop Loss", "TP1", "TP2", "TP3", "RR",
        "Trigger", "Confluence", "HTF Bias",
        "Pattern", "Fibonacci", "SnR", "SnD", "Divergence", "Sesi",
        "Outcome",
        "TP1 Hit (WIB)", "TP2 Hit (WIB)", "TP3 Hit (WIB)", "SL Hit (WIB)",
        "Durasi (mnt)", "Harga Resolve", "Catatan",
    ]

    # Header row
    _write_header_row(ws, 1, headers, bg=C_HEADER_BLUE, fg="FFFFFF")

    # Lebar kolom
    col_widths = [
        4, 38, 20, 9, 5, 6, 14,
        10, 10, 10, 10, 10, 6,
        10, 10, 22,
        18, 20, 16, 20, 14, 10,
        10,
        20, 20, 20, 20,
        12, 14, 20,
    ]
    for i, w in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws.freeze_panes = "A2"

    sorted_recs = sorted(records, key=lambda x: x.get("timestamp", ""))

    for i, rec in enumerate(sorted_recs, 1):
        outcome = rec.get("outcome", "PENDING")

        # Pilih warna baris
        if outcome in ("WIN_TP1", "WIN_TP2", "WIN_TP3"):
            row_bg = C_WIN
        elif outcome == "LOSS":
            row_bg = C_LOSS
        elif outcome == "PENDING":
            row_bg = C_PENDING
        else:
            row_bg = None

        if rec.get("signal_mode") == "counter_trend" and row_bg is None:
            row_bg = C_COUNTER

        mode_label = "Counter" if rec.get("signal_mode") == "counter_trend" else "Trend"

        values = [
            i,
            rec.get("signal_id", ""),
            _to_wib(rec.get("timestamp", "")),
            rec.get("symbol", ""),
            rec.get("timeframe", ""),
            rec.get("direction", ""),
            mode_label,
            _f(rec.get("entry")),
            _f(rec.get("sl")),
            _f(rec.get("tp1")),
            _f(rec.get("tp2")),
            _f(rec.get("tp3")),
            _f(rec.get("rr")),
            rec.get("trigger_score", ""),
            rec.get("confluence_score", ""),
            rec.get("htf_bias", ""),
            rec.get("pattern_names", ""),
            rec.get("fib_detail", ""),
            rec.get("snr_detail", ""),
            rec.get("snd_detail", ""),
            rec.get("divergence_detail", ""),
            rec.get("session_name", ""),
            outcome,
            _to_wib(rec.get("tp1_hit_time", "")),
            _to_wib(rec.get("tp2_hit_time", "")),
            _to_wib(rec.get("tp3_hit_time", "")),
            _to_wib(rec.get("sl_hit_time",  "")),
            int(rec.get("duration_minutes", 0) or 0),
            _f(rec.get("outcome_price")),
            rec.get("notes", ""),
        ]

        row_num = i + 1
        for col, val in enumerate(values, 1):
            cell = ws.cell(row=row_num, column=col, value=val)
            if row_bg:
                cell.fill = PatternFill("solid", fgColor=row_bg)
            cell.alignment = Alignment(wrap_text=False, vertical="center")

        # Warnai kolom outcome lebih terang
        outcome_col = headers.index("Outcome") + 1
        _set(ws, row_num, outcome_col, outcome, bold=True,
             bg=C_WIN if "WIN" in outcome else (C_LOSS if outcome == "LOSS" else C_PENDING))

    _auto_border(ws, 1, 1, len(records) + 1, len(headers))

    # Keterangan warna di bawah tabel
    legend_row = len(records) + 3
    ws.merge_cells(f"A{legend_row}:D{legend_row}")
    _set(ws, legend_row, 1, "Keterangan Warna:", bold=True)
    legend_row += 1
    for label, color in [
        ("WIN (TP1/TP2/TP3)", C_WIN),
        ("LOSS", C_LOSS),
        ("PENDING (belum resolve)", C_PENDING),
    ]:
        _set(ws, legend_row, 1, f"  {label}", bg=color)
        legend_row += 1

def _sheet_per_tf(wb, stats: dict) -> None:
    ws  = wb.create_sheet("Per Timeframe")
    by_tf = stats.get("by_timeframe", {})

    _set(ws, 1, 1, "PERFORMA PER TIMEFRAME", bold=True, size=12, bg=C_HEADER_GOLD, fg="FFFFFF")
    ws.merge_cells("A1:G1")

    headers = ["Timeframe", "Total", "WIN", "LOSS", "Pending", "Win Rate (%)", "Keterangan"]
    _write_header_row(ws, 2, headers, bg=C_HEADER_BLUE, fg="FFFFFF")

    for col, w in zip(range(1, 8), [12, 8, 8, 8, 8, 14, 20]):
        ws.column_dimensions[get_column_letter(col)].width = w

    r = 3
    for tf, d in sorted(by_tf.items()):
        dec = d["win"] + d["loss"]
        wr  = round(d["win"] / dec * 100, 1) if dec > 0 else 0.0
        note = "Data cukup" if dec >= 10 else ("Data terbatas" if dec > 0 else "Belum ada data")
        bg   = C_WIN if wr >= 60 else (C_LOSS if (dec > 0 and wr < 40) else None)

        vals = [tf, d["total"], d["win"], d["loss"], d["pending"], wr, note]
        for col, val in enumerate(vals, 1):
            _set(ws, r, col, val, bg=bg)
        r += 1

    _auto_border(ws, 1, 1, r - 1, 7)

    # Catatan
    r += 1
    _set(ws, r, 1, "* Hijau = Win Rate >= 60% | Merah = Win Rate < 40%", italic=True)

def _sheet_per_arah(wb, stats: dict) -> None:
    ws    = wb.create_sheet("Per Arah")
    by_dir = stats.get("by_direction", {})

    _set(ws, 1, 1, "PERFORMA PER ARAH (BUY vs SELL)", bold=True, size=12, bg=C_HEADER_GOLD, fg="FFFFFF")
    ws.merge_cells("A1:F1")

    headers = ["Arah", "Total", "WIN", "LOSS", "Pending", "Win Rate (%)"]
    _write_header_row(ws, 2, headers, bg=C_HEADER_BLUE, fg="FFFFFF")

    for col, w in zip(range(1, 7), [10, 8, 8, 8, 8, 14]):
        ws.column_dimensions[get_column_letter(col)].width = w

    r = 3
    for direc, d in by_dir.items():
        dec = d["win"] + d["loss"]
        wr  = round(d["win"] / dec * 100, 1) if dec > 0 else 0.0
        bg  = C_WIN if wr >= 60 else (C_LOSS if (dec > 0 and wr < 40) else None)

        vals = [direc, d["total"], d["win"], d["loss"], d["pending"], wr]
        for col, val in enumerate(vals, 1):
            _set(ws, r, col, val, bg=bg)
        r += 1

    _auto_border(ws, 1, 1, r - 1, 6)

def _sheet_trend_vs_counter(wb, stats: dict) -> None:
    ws      = wb.create_sheet("Trend vs Counter")
    by_mode = stats.get("by_mode", {})

    _set(ws, 1, 1, "TREND FOLLOWING vs COUNTER TREND", bold=True, size=12, bg=C_HEADER_GOLD, fg="FFFFFF")
    ws.merge_cells("A1:G1")

    headers = ["Mode", "Total", "WIN", "LOSS", "Pending", "Win Rate (%)", "Keterangan"]
    _write_header_row(ws, 2, headers, bg=C_HEADER_BLUE, fg="FFFFFF")

    for col, w in zip(range(1, 8), [18, 8, 8, 8, 8, 14, 40]):
        ws.column_dimensions[get_column_letter(col)].width = w

    r = 3
    labels = {"trend": "Trend Following", "counter_trend": "Counter Trend"}
    notes  = {
        "trend":         "Mengikuti arah HTF bias",
        "counter_trend": "Melawan HTF bias — butuh divergence + konfluensi ketat",
    }
    colors = {"trend": None, "counter_trend": C_COUNTER}

    for mode, d in by_mode.items():
        dec   = d["win"] + d["loss"]
        wr    = round(d["win"] / dec * 100, 1) if dec > 0 else 0.0
        label = labels.get(mode, mode)
        note  = notes.get(mode, "")
        bg    = colors.get(mode)

        vals = [label, d["total"], d["win"], d["loss"], d["pending"], wr, note]
        for col, val in enumerate(vals, 1):
            _set(ws, r, col, val, bg=bg)
        r += 1

    _auto_border(ws, 1, 1, r - 1, 7)

    # Penjelasan
    r += 1
    _set(ws, r, 1, "Penjelasan:", bold=True)
    r += 1
    for line in [
        "Trend Following : sinyal searah bias HTF (H4/D1). Min RR 1.5, Min Confluence 2.",
        "Counter Trend   : sinyal melawan bias HTF. Min RR 2.0, Min Confluence 3.",
        "                  Wajib ada Divergence RSI/MACD. Hanya diizinkan di TF H1 dan H4.",
    ]:
        ws.merge_cells(f"A{r}:G{r}")
        _set(ws, r, 1, line, italic=True)
        r += 1

def _sheet_akurasi_komponen(wb, stats: dict) -> None:
    ws   = wb.create_sheet("Akurasi Komponen")
    comp = stats.get("component_accuracy", {})

    _set(ws, 1, 1, "AKURASI PER KOMPONEN ANALISIS TEKNIKAL", bold=True, size=12, bg=C_HEADER_GOLD, fg="FFFFFF")
    ws.merge_cells("A1:F1")

    _set(ws, 2, 1,
         "Akurasi = % sinyal WIN dari semua sinyal yang menggunakan komponen ini",
         italic=True)
    ws.merge_cells("A2:F2")

    headers = ["Komponen", "Layer", "Total Pakai", "WIN", "LOSS", "Akurasi (%)"]
    _write_header_row(ws, 3, headers, bg=C_HEADER_BLUE, fg="FFFFFF")

    for col, w in zip(range(1, 7), [18, 12, 12, 8, 8, 14]):
        ws.column_dimensions[get_column_letter(col)].width = w

    # Layer mapping
    layer_map = {
        "EMA200":        "Trigger",
        "EMA50":         "Trigger",
        "EMA_ALIGN":     "Trigger",
        "RSI":           "Trigger",
        "MACD":          "Trigger",
        "CANDLE":        "Trigger",
        "PATTERN":       "Confluence",
        "DIVERGENCE":    "Confluence",
        "FIBONACCI":     "Confluence",
        "SNR":           "Confluence",
        "SND":           "Confluence",
        "COUNTER_TREND": "Mode",
    }

    r = 4
    if comp:
        for name, v in sorted(comp.items(), key=lambda x: -x[1]["accuracy"]):
            layer = layer_map.get(name, "-")
            wr    = v["accuracy"]
            bg    = C_WIN if wr >= 60 else (C_LOSS if (v["total"] > 0 and wr < 40) else None)

            vals = [name, layer, v["total"], v["win"], v["loss"], wr]
            for col, val in enumerate(vals, 1):
                _set(ws, r, col, val, bg=bg)
            r += 1
    else:
        ws.merge_cells(f"A{r}:F{r}")
        _set(ws, r, 1, "Belum ada data (butuh minimal 1 sinyal WIN/LOSS)", italic=True)
        r += 1

    _auto_border(ws, 1, 1, r - 1, 6)

    r += 1
    _set(ws, r, 1, "* Hijau = Akurasi >= 60% | Merah = Akurasi < 40%", italic=True)
    r += 1
    _set(ws, r, 1,
         "* Komponen dengan akurasi tinggi = indikator yang paling andal di sistem ini",
         italic=True)

def _sheet_equity_curve(wb, records: list[dict]) -> None:
    ws = wb.create_sheet("Equity Curve")

    _set(ws, 1, 1, "EQUITY CURVE — KUMULATIF WIN/LOSS", bold=True, size=12,
         bg=C_HEADER_GOLD, fg="FFFFFF")
    ws.merge_cells("A1:F1")
    _set(ws, 2, 1,
         "WIN = +1 | LOSS = -1 | Equity = akumulasi hasil sejak sinyal pertama",
         italic=True)
    ws.merge_cells("A2:F2")

    headers = ["No", "Tanggal Resolve (WIB)", "Signal ID", "Arah", "Outcome", "Equity"]
    _write_header_row(ws, 3, headers, bg=C_HEADER_BLUE, fg="FFFFFF")

    for col, w in zip(range(1, 7), [5, 22, 38, 6, 12, 10]):
        ws.column_dimensions[get_column_letter(col)].width = w

    decided = [
        r for r in records
        if r.get("outcome") not in ("PENDING", "CANCELLED", "")
        and r.get("outcome_time")
    ]
    decided.sort(key=lambda x: x.get("outcome_time", ""))

    equity   = 0
    data_row = 4
    for i, rec in enumerate(decided, 1):
        outcome = rec.get("outcome", "")
        if outcome in ("WIN_TP1", "WIN_TP2", "WIN_TP3"):
            equity += 1
            bg = C_WIN
        elif outcome == "LOSS":
            equity -= 1
            bg = C_LOSS
        else:
            continue

        vals = [
            i,
            _to_wib(rec.get("outcome_time", "")),
            rec.get("signal_id", ""),
            rec.get("direction", ""),
            outcome,
            equity,
        ]
        for col, val in enumerate(vals, 1):
            _set(ws, data_row, col, val, bg=bg)

        eq_cell = ws.cell(row=data_row, column=6)
        eq_cell.font = Font(bold=True)
        data_row += 1

    if data_row == 4:
        ws.merge_cells("A4:F4")
        _set(ws, 4, 1, "Belum ada sinyal yang resolve (WIN/LOSS)", italic=True)
        data_row = 5

    _auto_border(ws, 1, 1, data_row - 1, 6)

    # Summary
    data_row += 1
    _set(ws, data_row,     1, f"Equity Akhir  : {equity:+d}", bold=True)
    _set(ws, data_row + 1, 1, f"Total Resolve : {len(decided)} sinyal", bold=True)
    n_rows = data_row - 4 - 2   # jumlah baris data (tidak termasuk summary)
    if n_rows > 0:
        chart = LineChart()
        chart.title         = "Equity Curve — Kumulatif Hasil Trading"
        chart.y_axis.title  = "Equity (unit sinyal)"
        chart.x_axis.title  = "Urutan Sinyal"
        chart.style         = 10
        chart.width         = 22
        chart.height        = 14
        chart.y_axis.crossAx = 500
        chart.x_axis.crossAx = 100

        # Data equity (kolom F, mulai baris 4)
        data_ref = Reference(ws, min_col=6, min_row=3,
                             max_row=3 + n_rows)
        chart.add_data(data_ref, titles_from_data=True)

        # Style garis: tebal, warna biru
        series = chart.series[0]
        series.graphicalProperties.line.solidFill = "1F4E79"
        series.graphicalProperties.line.width     = 25000  # 2.5pt

        ws.add_chart(chart, "H3")

def _set(
    ws, row: int, col: int, value=None,
    bold=False, italic=False, size=11,
    bg: str | None = None, fg: str = "000000",
    align: str = "left",
) -> None:
    cell = ws.cell(row=row, column=col, value=value)
    cell.font      = Font(bold=bold, italic=italic, size=size, color=fg)
    cell.alignment = Alignment(
        horizontal  = align,
        vertical    = "center",
        wrap_text   = False,
    )
    if bg:
        cell.fill = PatternFill("solid", fgColor=bg)

def _write_header_row(
    ws, row: int, headers: list[str],
    bg: str = C_HEADER_BLUE, fg: str = "FFFFFF",
) -> None:
    for col, h in enumerate(headers, 1):
        _set(ws, row, col, h, bold=True, bg=bg, fg=fg, align="center")
    ws.row_dimensions[row].height = 18

def _auto_border(ws, r1: int, c1: int, r2: int, c2: int) -> None:
    thin = Side(style="thin")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    for row in ws.iter_rows(min_row=r1, max_row=r2, min_col=c1, max_col=c2):
        for cell in row:
            cell.border = border

def _f(val) -> float:
    """Parse float dengan aman, return 0.0 jika kosong/None."""
    try:
        v = float(val or 0)
        return v if v != 0.0 else 0.0
    except Exception:
        return 0.0

def _cli() -> None:
    print("\n" + "=" * 60)
    print("  REPORT GENERATOR — BOT TRADING DSS XAU/USD")
    print("=" * 60)

    log     = SignalLogger()
    records = log.get_all_records()

    if not records:
        print("\n  Tidak ada data sinyal.")
        print("  Jalankan bot dulu dan tunggu sinyal keluar.\n")
        return

    stats = log.get_stats()
    print(f"\n  Total sinyal : {stats['total_signals']}")
    print(f"  Sudah eval   : {stats['decided']}")
    print(f"  Win rate     : {stats['win_rate_pct']}%")
    print(f"\n  Membuat laporan Excel ...")

    out = generate_report(log)

    print(f"  Buka file ini di Excel:")
    print(f"  {out.resolve()}\n")

if __name__ == "__main__":
    _cli()


