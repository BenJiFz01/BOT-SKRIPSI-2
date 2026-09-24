"""signal_logger.py — Pencatatan histori sinyal ke CSV dan JSON."""

import csv
import json
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from src.models.signal import Signal
from src.utils.time_utils import TZ_WIB, now_wib_str


LOG_DIR   = Path("logs")
CSV_PATH  = LOG_DIR / "signal_history.csv"
JSON_PATH = LOG_DIR / "signal_history.json"

CSV_FIELDS = [
    "signal_id", "timestamp", "symbol", "timeframe", "direction",
    "signal_mode", "trade_mode", "is_setup_plan", "exec_tf", "candle_close",
    "entry", "sl", "tp1", "tp2", "tp3", "rr", "rr_tp2_actual",
    "trigger_score", "confluence_score", "htf_bias",
"trigger_notes", "confluence_notes", "pattern_names",
    "fib_detail", "snr_detail", "snd_detail", "divergence_detail",
    "sweep_detail", "fvg_detail",
    "session_name", "sl_method", "atr_value",
    "outcome", "outcome_price", "outcome_time",
    "tp1_hit_time", "tp2_hit_time", "tp3_hit_time", "sl_hit_time",
    "duration_minutes", "notes",
]

# Field & keyword untuk component accuracy di get_stats()
_COMPONENT_FIELDS: dict[str, str] = {
    "EMA200":     "trigger_notes",
    "EMA50":      "trigger_notes",
    "RSI":        "trigger_notes",
    "MACD":       "trigger_notes",
    "PATTERN":    "pattern_names",
"DIVERGENCE": "divergence_detail",
    "FIBONACCI":  "fib_detail",
    "SNR":        "snr_detail",
    "SND":        "snd_detail",
    "SWEEP":      "sweep_detail",
    "FVG":        "fvg_detail",
}
_COMP_KEYWORDS: dict[str, str] = {
    "EMA200":     "EMA200+",
    "EMA50":      "EMA50+",
    "RSI":        "RSI+",
    "MACD":       "MACD+",
    "PATTERN":    "",
    "DIVERGENCE": "",
    "FIBONACCI":  "",
    "SNR":        "SNR_OK",
    "SND":        "",
    "SWEEP":      "SWEEP_OK",
    "FVG":        "FVG_OK",
}


@dataclass
class SignalRecord:
    signal_id:         str
    timestamp:         str
    symbol:            str
    timeframe:         str
    direction:         str
    signal_mode:       str
    trade_mode:        str
    is_setup_plan:     bool
    exec_tf:           str
    candle_close:      str
    entry:             float
    sl:                float
    tp1:               float
    tp2:               float
    tp3:               float
    rr:                float
    rr_tp2_actual:     float
    trigger_score:     str
    confluence_score:  str
    htf_bias:          str
    trigger_notes:     str
    confluence_notes:  str
    pattern_names:     str
    fib_detail:        str
    snr_detail:        str
    snd_detail:        str
    divergence_detail: str
    sweep_detail:      str
    fvg_detail:        str
    session_name:      str
    sl_method:         str
    atr_value:         float
    outcome:           str   = "PENDING"
    outcome_price:     float = 0.0
    outcome_time:      str   = ""
    tp1_hit_time:      str   = ""
    tp2_hit_time:      str   = ""
    tp3_hit_time:      str   = ""
    sl_hit_time:       str   = ""
    duration_minutes:  int   = 0
    notes:             str   = ""


def _make_signal_id(symbol: str, tf: str, timestamp: str) -> str:
    clean = (
        timestamp.replace(":", "").replace("-", "").replace("T", "_").replace(" ", "_")
    )[:15]
    return f"{symbol}_{tf}_{clean}"


class SignalLogger:
    """Pencatat histori sinyal ke CSV dan JSON; thread-safe via _lock untuk
    mencegah race condition (rawan JSON corrupt antara main loop dan tracker).
    """

    def __init__(
        self,
        csv_path:  Path | str = CSV_PATH,
        json_path: Path | str = JSON_PATH,
    ) -> None:
        self.csv_path  = Path(csv_path)
        self.json_path = Path(json_path)
        self._lock     = threading.Lock()   # satu lock untuk JSON + CSV
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.csv_path.exists():
            with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=CSV_FIELDS).writeheader()

    def _load(self) -> dict[str, dict]:
        """Load JSON — harus dipanggil di dalam _lock."""
        if not self.json_path.exists():
            return {}
        try:
            with open(self.json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save(self, data: dict[str, dict]) -> None:
        """Tulis JSON atomic (harus dipanggil di dalam _lock): tulis ke .tmp lalu
        rename, mencegah file terpotong setengah jika crash saat nulis.
        """
        tmp = self.json_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp.replace(self.json_path)   # atomic pada Windows NTFS

    def _rewrite_csv(self, data: dict[str, dict]) -> None:
        """Tulis ulang CSV — harus dipanggil di dalam _lock."""
        tmp = self.csv_path.with_suffix(".tmp")
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            w.writeheader()
            for rec in data.values():
                w.writerow({k: rec.get(k, "") for k in CSV_FIELDS})
        tmp.replace(self.csv_path)

    def log_signal(self, sig: Signal) -> str:
        """Catat sinyal baru ke CSV dan JSON. Return signal_id."""
        now = now_wib_str()
        sid = _make_signal_id(sig.symbol, sig.tf, now)

        is_setup = getattr(sig, "is_setup_plan", False)
        rec = SignalRecord(
            signal_id         = sid,
            timestamp         = now,
            symbol            = sig.symbol,
            timeframe         = sig.tf,
            direction         = sig.direction,
            signal_mode       = getattr(sig, "signal_mode",   "CONTINUATION"),
            trade_mode        = getattr(sig, "trade_mode",    "intraday"),
            is_setup_plan     = is_setup,
            exec_tf           = getattr(sig, "exec_tf",       ""),
            candle_close      = sig.close_time,
            entry             = round(sig.entry, 5),
            sl                = round(sig.sl,  5) if sig.sl  is not None else 0.0,
            tp1               = round(sig.tp,  5) if sig.tp  is not None else 0.0,
            tp2               = round(sig.tp2, 5) if sig.tp2 is not None else 0.0,
            tp3               = round(sig.tp3, 5) if sig.tp3 is not None else 0.0,
            rr                = round(sig.rr,  2) if sig.rr  is not None else 0.0,
            rr_tp2_actual     = round(sig.rr_tp2_actual, 2),
            trigger_score     = f"{sig.trigger_score}/{sig.trigger_max}",
            confluence_score  = f"{sig.confluence_score}",
            htf_bias          = sig.htf_bias,
            trigger_notes     = sig.trigger_notes,
            confluence_notes  = sig.confluence_notes,
            pattern_names     = sig.pattern_names,
            fib_detail        = sig.fib_detail,
            snr_detail        = sig.snr_detail,
            snd_detail        = sig.snd_detail,
            divergence_detail = sig.divergence_detail,
            sweep_detail      = sig.sweep_detail,
            fvg_detail        = sig.fvg_detail,
            session_name      = sig.session_name,
            sl_method         = sig.sl_method,
            atr_value         = round(sig.atr_value, 4),
            outcome           = "SETUP" if is_setup else "PENDING",
        )

        with self._lock:
            with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=CSV_FIELDS).writerow(
                    {k: getattr(rec, k, "") for k in CSV_FIELDS}
                )
            data = self._load()
            data[sid] = asdict(rec)
            self._save(data)
        return sid

    def update_hit_time(self, signal_id: str, level: str, hit_time: str) -> bool:
        """Catat waktu TP/SL tersentuh. level = 'tp1'|'tp2'|'tp3'|'sl'."""
        field = {"tp1": "tp1_hit_time", "tp2": "tp2_hit_time",
                 "tp3": "tp3_hit_time", "sl": "sl_hit_time"}.get(level.lower())
        if not field:
            return False
        with self._lock:
            data = self._load()
            if signal_id not in data:
                return False
            data[signal_id][field] = hit_time
            self._save(data)
            self._rewrite_csv(data)
        return True

    def update_outcome(
        self,
        signal_id:  str,
        outcome:    str,
        price:      float = 0.0,
        notes:      str   = "",
        duration_m: int   = 0,
    ) -> bool:
        """Update hasil akhir sinyal."""
        with self._lock:
            data = self._load()
            if signal_id not in data:
                return False
            rec = data[signal_id]
            rec["outcome"]       = outcome
            rec["outcome_price"] = price
            rec["outcome_time"]  = now_wib_str()
            rec["notes"]         = notes
            if duration_m > 0:
                rec["duration_minutes"] = duration_m
            elif rec.get("timestamp") and not rec.get("duration_minutes"):
                try:
                    ts = rec["timestamp"]
                    dt_sig = datetime.fromisoformat(ts)
                    if dt_sig.tzinfo is None:
                        dt_sig = dt_sig.replace(tzinfo=TZ_WIB)
                    dur = int((datetime.now(tz=TZ_WIB) - dt_sig).total_seconds() / 60)
                    rec["duration_minutes"] = dur
                except Exception:
                    pass
            if outcome == "LOSS" and not rec.get("sl_hit_time"):
                rec["sl_hit_time"] = rec["outcome_time"]
            self._save(data)
            self._rewrite_csv(data)
        return True

    def get_all_records(self) -> list[dict]:
        with self._lock:
            return list(self._load().values())

    def get_trackable(self) -> list[dict]:
        """Semua sinyal yang perlu dimonitor: PENDING (live) + SETUP (setup plan)."""
        with self._lock:
            return [r for r in self._load().values() if r.get("outcome") in ("PENDING", "SETUP")]

    def get_by_id(self, signal_id: str) -> dict | None:
        with self._lock:
            return self._load().get(signal_id)

    def get_stats(self) -> dict:
        """Statistik hanya dari sinyal terkonfirmasi (bukan setup plan)."""
        wins = {"WIN_TP1": 0, "WIN_TP2": 0, "WIN_TP3": 0}
        losses = pending = cancelled = 0
        rr_list: list[float] = []
        rr_tp2_list: list[float] = []
        dur_list: list[int]  = []
        by_tf: dict = {}
        by_dir: dict = {}
        by_mode: dict = {}

        for rec in self.get_all_records():
            # Skip sinyal yang masih SETUP (belum ada outcome)
            if rec.get("outcome") == "SETUP":
                continue

            outcome = rec.get("outcome", "PENDING")
            tf      = rec.get("timeframe", "?")
            direc   = rec.get("direction", "?")
            mode    = rec.get("signal_mode", "CONTINUATION")
            rr      = float(rec.get("rr", 0) or 0)
            dur     = int(rec.get("duration_minutes", 0) or 0)

            for bmap, key in [(by_tf, tf), (by_dir, direc), (by_mode, mode)]:
                bmap.setdefault(key, {"total": 0, "win": 0, "loss": 0, "pending": 0})
                bmap[key]["total"] += 1

            if outcome == "PENDING":
                pending += 1
                for bmap, key in [(by_tf, tf), (by_dir, direc), (by_mode, mode)]:
                    bmap[key]["pending"] += 1
            elif outcome in wins:
                wins[outcome] += 1
                if rr  > 0: rr_list.append(rr)
                rr_tp2 = float(rec.get("rr_tp2_actual", 0) or 0)
                if rr_tp2 > 0: rr_tp2_list.append(rr_tp2)
                if dur > 0: dur_list.append(dur)
                for bmap, key in [(by_tf, tf), (by_dir, direc), (by_mode, mode)]:
                    bmap[key]["win"] += 1
            elif outcome == "LOSS":
                losses += 1
                for bmap, key in [(by_tf, tf), (by_dir, direc), (by_mode, mode)]:
                    bmap[key]["loss"] += 1
            elif outcome == "CANCELLED":
                cancelled += 1

        total_wins = sum(wins.values())
        decided    = total_wins + losses

        component_accuracy: dict[str, dict] = {}

        for rec in self.get_all_records():
            if rec.get("outcome") in ("SETUP", "PENDING", "CANCELLED"):
                continue
            outcome = rec.get("outcome", "")
            is_win  = outcome in ("WIN_TP1", "WIN_TP2", "WIN_TP3")
            is_loss = outcome == "LOSS"
            if not (is_win or is_loss):
                continue

            for comp, field in _COMPONENT_FIELDS.items():
                field_val = str(rec.get(field, "") or "")
                kw        = _COMP_KEYWORDS[comp]
                used      = (kw and kw in field_val) or (not kw and bool(field_val.strip()))
                if not used:
                    continue
                if comp not in component_accuracy:
                    component_accuracy[comp] = {"total": 0, "win": 0, "loss": 0, "accuracy": 0.0}
                b = component_accuracy[comp]
                b["total"] += 1
                if is_win:
                    b["win"] += 1
                elif is_loss:
                    b["loss"] += 1

        for b in component_accuracy.values():
            dec = b["win"] + b["loss"]
            b["accuracy"] = round(b["win"] / dec * 100, 1) if dec > 0 else 0.0

        return {
            "total_signals":  decided + pending + cancelled,
            "pending":        pending,
            "decided":        decided,
            "win_tp1":        wins["WIN_TP1"],
            "win_tp2":        wins["WIN_TP2"],
            "win_tp3":        wins["WIN_TP3"],
            "total_wins":     total_wins,
            "losses":         losses,
            "cancelled":      cancelled,
            "win_rate_pct":   round(total_wins / decided * 100, 1) if decided else 0.0,
            "avg_rr":         round(sum(rr_list)  / len(rr_list),  2) if rr_list  else 0.0,
            "avg_structural_rr": round(sum(rr_tp2_list) / len(rr_tp2_list), 2) if rr_tp2_list else 0.0,
            "avg_duration_m": int(sum(dur_list) / len(dur_list))       if dur_list else 0,
            "by_timeframe":   by_tf,
            "by_direction":   by_dir,
            "by_mode":        by_mode,
            "component_accuracy": component_accuracy,
        }
