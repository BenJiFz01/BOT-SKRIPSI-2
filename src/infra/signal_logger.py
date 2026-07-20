"""
signal_logger.py
================
Pencatatan histori sinyal trading ke CSV dan JSON.

Output:
    logs/signal_history.csv   -- bisa dibuka langsung di Excel
    logs/signal_history.json  -- untuk proses programatik / statistik

Cara pakai:
    sl = SignalLogger()
    signal_id = sl.log_signal(sig)          # catat sinyal baru
    sl.update_outcome(signal_id, "WIN_TP1") # update hasil setelah sinyal keluar
    stats = sl.get_stats()                  # hitung win rate
"""
from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from src.models.signal import Signal


LOG_DIR   = Path("logs")
CSV_PATH  = LOG_DIR / "signal_history.csv"
JSON_PATH = LOG_DIR / "signal_history.json"

OUTCOME = Literal["PENDING", "WIN_TP1", "WIN_TP2", "WIN_TP3", "LOSS", "CANCELLED"]

CSV_FIELDS = [
    "signal_id",
    "timestamp",
    "symbol",
    "timeframe",
    "direction",
    "candle_close",
    "entry",
    "sl",
    "tp1",
    "tp2",
    "tp3",
    "rr",
    "trigger_score",
    "confluence_score",
    "htf_bias",
    "trigger_notes",
    "confluence_notes",
    "pattern_names",
    "fib_detail",
    "snr_detail",
    "snd_detail",
    "divergence_detail",
    "session_name",
    "sl_method",
    "atr_value",
    "outcome",
    "outcome_price",
    "outcome_time",
    "notes",
]


@dataclass
class SignalRecord:
    signal_id:         str
    timestamp:         str
    symbol:            str
    timeframe:         str
    direction:         str
    candle_close:      str
    entry:             float
    sl:                float
    tp1:               float
    tp2:               float
    tp3:               float
    rr:                float
    trigger_score:     str        # contoh: "5/6"
    confluence_score:  str        # contoh: "4/5"
    htf_bias:          str
    trigger_notes:     str
    confluence_notes:  str
    pattern_names:     str
    fib_detail:        str
    snr_detail:        str
    snd_detail:        str
    divergence_detail: str
    session_name:      str
    sl_method:         str
    atr_value:         float
    outcome:           str   = "PENDING"
    outcome_price:     float = 0.0
    outcome_time:      str   = ""
    notes:             str   = ""


def _make_signal_id(symbol: str, tf: str, timestamp: str) -> str:
    """
    Buat ID unik untuk sinyal.
    Format: XAUUSD_H1_20260720_140000
    """
    clean = (
        timestamp
        .replace(":", "")
        .replace("-", "")
        .replace("T", "_")
        .replace(" ", "_")
    )[:15]
    return f"{symbol}_{tf}_{clean}"


class SignalLogger:
    """Pencatat histori sinyal ke CSV dan JSON."""

    def __init__(
        self,
        csv_path:  Path | str = CSV_PATH,
        json_path: Path | str = JSON_PATH,
    ) -> None:
        self.csv_path  = Path(csv_path)
        self.json_path = Path(json_path)
        self._ensure_dirs()
        self._ensure_csv_header()

    # ── Setup ─────────────────────────────────────────────────────────

    def _ensure_dirs(self) -> None:
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)

    def _ensure_csv_header(self) -> None:
        if not self.csv_path.exists():
            with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
                writer.writeheader()

    # ── JSON helpers ──────────────────────────────────────────────────

    def _load_json(self) -> dict[str, dict]:
        if not self.json_path.exists():
            return {}
        try:
            with open(self.json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_json(self, data: dict[str, dict]) -> None:
        with open(self.json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    # ── Catat sinyal baru ─────────────────────────────────────────────

    def log_signal(self, sig: Signal) -> str:
        """
        Catat sinyal ke CSV dan JSON.

        Args:
            sig: Objek Signal dari engine.

        Returns:
            signal_id: ID unik sinyal yang baru dicatat.
        """
        now = datetime.now().isoformat(timespec="seconds")
        sid = _make_signal_id(sig.symbol, sig.tf, now)

        record = SignalRecord(
            signal_id        = sid,
            timestamp        = now,
            symbol           = sig.symbol,
            timeframe        = sig.tf,
            direction        = sig.direction,
            candle_close     = sig.close_time,
            entry            = round(sig.entry, 5),
            sl               = round(sig.sl,    5) if sig.sl  is not None else 0.0,
            tp1              = round(sig.tp,     5) if sig.tp  is not None else 0.0,
            tp2              = round(sig.tp2,    5) if sig.tp2 is not None else 0.0,
            tp3              = round(sig.tp3,    5) if sig.tp3 is not None else 0.0,
            rr               = round(sig.rr,     2) if sig.rr  is not None else 0.0,
            trigger_score    = f"{sig.trigger_score}/{sig.trigger_max}",
            confluence_score = f"{sig.confluence_score}/{sig.confluence_max}",
            htf_bias         = sig.htf_bias,
            trigger_notes    = sig.trigger_notes,
            confluence_notes = sig.confluence_notes,
            pattern_names    = sig.pattern_names,
            fib_detail       = sig.fib_detail,
            snr_detail       = sig.snr_detail,
            snd_detail       = sig.snd_detail,
            divergence_detail = sig.divergence_detail,
            session_name     = sig.session_name,
            sl_method        = sig.sl_method,
            atr_value        = round(sig.atr_value, 4),
        )

        with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            writer.writerow({k: getattr(record, k, "") for k in CSV_FIELDS})

        data = self._load_json()
        data[sid] = asdict(record)
        self._save_json(data)

        return sid

    # ── Update hasil sinyal ───────────────────────────────────────────

    def update_outcome(
        self,
        signal_id:    str,
        outcome:      str,
        price:        float = 0.0,
        notes:        str   = "",
    ) -> bool:
        """
        Perbarui hasil (outcome) sinyal yang sudah ada.

        Args:
            signal_id: ID sinyal yang akan diupdate.
            outcome:   Salah satu dari PENDING/WIN_TP1/WIN_TP2/WIN_TP3/LOSS/CANCELLED.
            price:     Harga saat outcome terjadi.
            notes:     Catatan tambahan (opsional).

        Returns:
            True jika berhasil, False jika signal_id tidak ditemukan.
        """
        data = self._load_json()
        if signal_id not in data:
            return False

        data[signal_id]["outcome"]       = outcome
        data[signal_id]["outcome_price"] = price
        data[signal_id]["outcome_time"]  = datetime.now().isoformat(timespec="seconds")
        data[signal_id]["notes"]         = notes
        self._save_json(data)
        self._rewrite_csv(data)
        return True

    def _rewrite_csv(self, data: dict[str, dict]) -> None:
        with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for rec in data.values():
                writer.writerow({k: rec.get(k, "") for k in CSV_FIELDS})

    # ── Statistik ─────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Hitung statistik win rate dari semua sinyal yang sudah dievaluasi."""
        data = self._load_json()

        wins      = {"WIN_TP1": 0, "WIN_TP2": 0, "WIN_TP3": 0}
        losses    = 0
        pending   = 0
        cancelled = 0
        rr_list:  list[float] = []

        by_tf:        dict[str, dict] = {}
        by_direction: dict[str, dict] = {}
        by_symbol:    dict[str, dict] = {}

        def _bucket() -> dict:
            return {"total": 0, "win": 0, "loss": 0, "pending": 0}

        for rec in data.values():
            outcome = rec.get("outcome", "PENDING")
            tf      = rec.get("timeframe", "?")
            direc   = rec.get("direction", "?")
            sym     = rec.get("symbol", "?")
            rr      = float(rec.get("rr", 0) or 0)

            for bucket, key in [(by_tf, tf), (by_direction, direc), (by_symbol, sym)]:
                if key not in bucket:
                    bucket[key] = _bucket()
                bucket[key]["total"] += 1

            if outcome == "PENDING":
                pending += 1
                by_tf[tf]["pending"]        += 1
                by_direction[direc]["pending"] += 1
                by_symbol[sym]["pending"]    += 1
                continue

            if outcome in wins:
                wins[outcome] += 1
                if rr > 0:
                    rr_list.append(rr)
                by_tf[tf]["win"]           += 1
                by_direction[direc]["win"] += 1
                by_symbol[sym]["win"]      += 1
            elif outcome == "LOSS":
                losses += 1
                by_tf[tf]["loss"]           += 1
                by_direction[direc]["loss"] += 1
                by_symbol[sym]["loss"]      += 1
            elif outcome == "CANCELLED":
                cancelled += 1

        total_wins = sum(wins.values())
        decided    = total_wins + losses
        win_rate   = round(total_wins / decided * 100, 1) if decided > 0 else 0.0

        return {
            "total_signals": len(data),
            "pending":       pending,
            "decided":       decided,
            "win_tp1":       wins["WIN_TP1"],
            "win_tp2":       wins["WIN_TP2"],
            "win_tp3":       wins["WIN_TP3"],
            "total_wins":    total_wins,
            "losses":        losses,
            "cancelled":     cancelled,
            "win_rate_pct":  win_rate,
            "avg_rr":        round(sum(rr_list) / len(rr_list), 2) if rr_list else 0.0,
            "best_rr":       round(max(rr_list), 2) if rr_list else 0.0,
            "worst_rr":      round(min(rr_list), 2) if rr_list else 0.0,
            "by_timeframe":  by_tf,
            "by_direction":  by_direction,
            "by_symbol":     by_symbol,
        }

    def format_stats_telegram(self) -> str:
        """Format statistik untuk dikirim ke Telegram (HTML)."""
        s = self.get_stats()

        lines = [
            "<b>STATISTIK BOT TRADING</b>",
            "",
            f"Total sinyal     : <code>{s['total_signals']}</code>",
            f"Pending          : <code>{s['pending']}</code>",
            f"Sudah dievaluasi : <code>{s['decided']}</code>",
            "",
            f"WIN TP1  : <code>{s['win_tp1']}</code>",
            f"WIN TP2  : <code>{s['win_tp2']}</code>",
            f"WIN TP3  : <code>{s['win_tp3']}</code>",
            f"LOSS     : <code>{s['losses']}</code>",
            f"BATAL    : <code>{s['cancelled']}</code>",
            "",
            f"<b>Win Rate : {s['win_rate_pct']}%</b>",
            f"Avg RR   : <code>{s['avg_rr']}</code>",
            f"Best RR  : <code>{s['best_rr']}</code>",
        ]

        if s["by_timeframe"]:
            lines.append("")
            lines.append("<b>Per Timeframe:</b>")
            for tf, d in sorted(s["by_timeframe"].items()):
                dec = d["win"] + d["loss"]
                wr  = round(d["win"] / dec * 100, 1) if dec > 0 else 0
                lines.append(
                    f"  {tf}: {d['win']}W {d['loss']}L ({wr}%) | pending={d['pending']}"
                )

        if s["by_direction"]:
            lines.append("")
            lines.append("<b>Per Arah:</b>")
            for direc, d in s["by_direction"].items():
                dec = d["win"] + d["loss"]
                wr  = round(d["win"] / dec * 100, 1) if dec > 0 else 0
                lines.append(f"  {direc}: {d['win']}W {d['loss']}L ({wr}%)")

        return "\n".join(lines)

    def get_all_records(self) -> list[dict]:
        """Kembalikan semua record sebagai list dict."""
        return list(self._load_json().values())

    def get_pending(self) -> list[dict]:
        """Kembalikan semua sinyal yang masih PENDING."""
        return [r for r in self.get_all_records() if r.get("outcome") == "PENDING"]
