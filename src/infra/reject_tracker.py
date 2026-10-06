"""reject_tracker.py — Tracking & summary rejection sinyal untuk monitoring.

Cara pakai: RejectTracker().record(symbol, tf, reason, df) lalu
maybe_print_summary() tiap loop — auto print summary 30 menit ke terminal.
"""

import re
from collections import defaultdict
from datetime import datetime, timedelta

import pandas as pd
from loguru import logger


def _atr_proxy(df: pd.DataFrame, n: int = 14) -> float:
    if "atr_14" in df.columns:
        v = df["atr_14"].iloc[-2]
        if pd.notna(v) and float(v) > 0:
            return float(v)
    if len(df) < 3:
        return 0.0
    w = df.iloc[-n:] if len(df) > n else df
    v = (w["high"].astype(float) - w["low"].astype(float)).mean()
    return float(v) if pd.notna(v) and v > 0 else 0.0


def _safe(row: pd.Series, col: str) -> float | None:
    v = row.get(col)
    return None if (v is None or pd.isna(v)) else float(v)

_SUMMARY_INTERVAL_MIN = 30

# Kategori reject untuk grouping (raw reason prefix → nama pendek)
_CATEGORY: dict[str, str] = {
    "EMA200_WAJIB":       "EMA200_WAJIB",
    "TRIGGER_FAIL":       "TRIGGER_FAIL",
    "RSI_EXTREME":        "RSI_EXTREME",
    "CT_EMA200_FAIL":     "CT_GAGAL",
    "CT_NO_CHOCH":        "CT_GAGAL",
    "CT_NO_DIV":          "CT_GAGAL",
    "CT_NO_FIB":          "CT_GAGAL",
    "BIAS_FAIL":          "BIAS_FAIL",
    "BRIDGE_FAIL":        "BIAS_FAIL",
    "CONFLUENCE_FAIL":    "CONFLUENCE_FAIL",
    "INTRADAY_NO_ANCHOR": "CONFLUENCE_FAIL",
    "PULLBACK_NO_FIB":    "CONFLUENCE_FAIL",
    "REVERSAL_NO_ZONE":   "CONFLUENCE_FAIL",
    "CANDLE_CONFIRM_FAIL":"CANDLE_FAIL",
    "RR_FAIL":            "RR_FAIL",
    "SL_TOO_WIDE":        "RR_FAIL",
    "ATR_TOO_LOW":        "ATR_RENDAH",
    "ATR_INVALID":        "ATR_RENDAH",
    "ATR_SPIKE":          "ATR_SPIKE",
    "ATR_DATA_INSUFFICIENT": "DATA_KURANG",
    "TP_ORDER_INVALID":   "SLTP_ERROR",
    "NEWS_SPIKE_SKIP":    "NEWS_SPIKE",
    "NOT_ENOUGH_BARS":    "DATA_KURANG",
    "COOLDOWN":           "COOLDOWN",
    "SLTP_NONE":          "SLTP_ERROR",
    "OUT_OF_SESSION":     "OUT_OF_SESSION",
    "LATE_ENTRY":         "LATE_ENTRY",
    "ASIAN_NO_KEY_LEVEL": "ASIAN_GATE",
    "SNR_BLOCKED":        "SNR_BLOCKED",
    "SNR_WEAK":           "SNR_BLOCKED",
    "DAILY_LIMIT":        "DAILY_LIMIT",
    "DAILY_LIMIT_SCALPING":  "DAILY_LIMIT",
    "DAILY_LIMIT_INTRADAY":  "DAILY_LIMIT",
    "MARKET_TRANSITION":  "MARKET_TRANSITION",
    "RANGE_QUALITY_NO_KEY_LEVEL": "RANGE_QUALITY",
    "MOM_RECOVERY_NO_LEVEL": "MOM_RECOVERY_NO_LEVEL",
    "RANGE_NO_REJECTION":    "RANGE_NO_REJECTION",
    "SL_OUT_OF_BOUNDS":      "SL_OUT_OF_BOUNDS",
    "SL_TOO_TIGHT":          "SL_TOO_TIGHT",
}

# Hint tuning per kategori dominan
_HINT: dict[str, str] = {
    "EMA200_WAJIB": (
        "Harga sedang di sisi salah EMA200 LTF — kemungkinan koreksi dalam trend HTF. "
        "Ini normal. Tunggu harga kembali di atas/bawah EMA200, atau cek apakah HTF bias masih valid."
    ),
    "BIAS_FAIL": (
        "HTF belum punya bias jelas atau TF konfirmasi tidak selaras. "
        "Pasar mungkin sedang transisi/konsolidasi. "
        "Tuning: kurangi MIN_CONFIRM_VOTES=1, atau cek apakah TF range sudah cukup panjang."
    ),
    "CONFLUENCE_FAIL": (
        "Zona entry tidak cukup terkonfirmasi (Fibonacci, S/R, Pattern, Divergence). "
        "Tuning: kurangi MIN_CONFLUENCE_SCORE — tapi pastikan Fib masih ada untuk intraday. "
        "Atau cek apakah harga sedang jauh dari level kunci."
    ),
    "TRIGGER_FAIL": (
        "Momentum entry belum cukup kuat (EMA, RSI, MACD, Candle). "
        "Tuning: kurangi MIN_TRIGGER_SCORE=3 untuk intraday atau SCALPING_MIN_TRIGGER_SCORE=2. "
        "Tapi pastikan EMA200 dan RSI masih masuk akal."
    ),
    "RSI_EXTREME": (
        "RSI overbought/oversold saat entry — harga sudah terlalu jauh bergerak. "
        "Ini filter yang benar. Tunggu RSI kembali ke area normal sebelum entry."
    ),
    "CT_GAGAL": (
        "Counter trend tidak memenuhi syarat (CHoCH/Divergence/Fibonacci). "
        "Counter trend memang jarang valid — ini expected."
    ),
    "RR_FAIL": (
        "Risk/Reward terlalu kecil atau SL terlalu lebar. "
        "Cek apakah swing point yang dipakai sebagai SL terlalu jauh. "
        "Atau turunkan TP RR minimum di .env."
    ),
    "ATR_RENDAH": (
        "Volatilitas pasar terlalu rendah untuk entry. "
        "Normal di sesi sepi (Asia malam). Tidak perlu tuning — tunggu pasar aktif."
    ),
    "CANDLE_FAIL": (
        "Candle konfirmasi tidak mendukung arah sinyal. "
        "Tuning: ini biasanya false negative kecil — bisa turunkan min_body dari 0.3x ke 0.2x ATR di evaluator.py."
    ),
    "COOLDOWN":    "Cooldown normal antar sinyal. Tidak perlu tuning.",
    "NEWS_SPIKE":  "Spike news — sistem sengaja skip. Benar.",
    "DATA_KURANG": "Data bar belum cukup — tunggu lebih banyak candle terkumpul.",
    "SLTP_ERROR":  "SL/TP gagal dihitung — kemungkinan data price bermasalah. Cek koneksi MT5.",
    "OUT_OF_SESSION": (
        "Di luar jam sesi aktif (02:00-06:00 WIB). Normal di akhir malam/dini hari. "
        "Tidak perlu tuning — bot akan aktif kembali saat sesi buka."
    ),
    "LATE_ENTRY": (
        "Harga sudah terlalu jauh dari candle trigger (>1.5×ATR). "
        "Entry yang 'chasing' rawan kena SL dari retracement wajar. "
        "Ini filter yang benar — tidak perlu dilemahkan."
    ),
    "ASIAN_GATE": (
        "Scalping di sesi Asian tanpa konfirmasi level SNR/SND kunci. "
        "Sesuai desain — Asian lebih choppy, wajib ada level struktural. "
        "Jika terlalu sering, pertimbangkan naikkan near_factor SNR/SND."
    ),
    "SNR_BLOCKED": (
        "Jalur ke TP terblokir level SNR, atau level SNR terlalu lemah (2-touch). "
        "Ini filter kualitas yang benar — level 2-touch akurasi historis hanya 31.6%. "
        "Tidak perlu dilemahkan."
    ),
    "DAILY_LIMIT": (
        "Circuit breaker aktif — terlalu banyak loss beruntun untuk symbol ini. "
        "Bot pause generate sinyal baru sampai ada WIN atau reset hari baru. "
        "Ini proteksi modal yang benar."
    ),
    "MARKET_TRANSITION": (
        "ADX di TF penentu bias (H1/H4) di bawah ambang block "
        "(MARKET_TRANSITION_ADX_BLOCK, default 15). "
        "Sistem menunda Continuation signal sesuai PRD 'Range/Transition → NO SIGNAL'. "
        "Jika terlalu sering, turunkan ambang block atau cek apakah D1 sudah beri bias."
    ),
    "RANGE_QUALITY": (
        "Pasar RANGE/sideways tanpa key level berkualitas (SnR 3-touch / FIB_GOLDEN) pada "
        "jalur continuation — level 2-touch (SnR_WEAK) tak dihitung karena rawan stop-hunt. "
        "Kasus 30/09 12:00 LOSS dengan SnR_WEAK; semua WIN hari itu punya level 3-touch. "
        "Tuning: RANGE_QUALITY_KEY_LEVEL=false untuk melonggari."
    ),
    "MOM_RECOVERY_NO_LEVEL": (
        "Sinyal lewat jalur MOM_RECOVERY (H1 netral + impulse lokal) tapi TIDAK punya "
        "level dekat entry (SnR/SnD/FIB_GOLDEN) — entry melayang tanpa pijakan. "
        "Kasus 30/09 16:00 M15 LOSS: SNR_FAR 25pt. "
        "Ini filter yang benar — MOM_RECOVERY butuh level sebagai anchor."
    ),
    "RANGE_NO_REJECTION": (
        "RANGE lane: skor rejection kurang (butuh 3/3: candle rejection + RSI + MACD). "
        "Kasus 30/09 17:50 M5 LOSS: skor 2/3. WIN 12:50 skor 3/3. "
        "Ini filter yang benar — RANGE hanya valid jika ketiga indikator setuju."
    ),
    "SL_OUT_OF_BOUNDS": (
        "SL hasil perhitungan ATR melampaui batas maksimum (scalping 2×ATR, intraday 2.5×ATR). "
        "Pasar terlalu volatile atau swing point terlalu jauh — risiko per trade tidak layak. "
        "Tuning: naikkan SCALPING_MAX_ATR_MULT/INTRADAY_MAX_ATR_MULT jika sering terjadi."
    ),
    "SL_TOO_TIGHT": (
        "SL hasil perhitungan kurang dari minimum (scalping 3×spread, intraday 5×spread). "
        "Entry terlalu dekat swing point atau ATR sangat rendah — rawan stop-hunt. "
        "Ini proteksi yang benar — jangan dilemahkan kecuali spread broker terlalu lebar."
    ),
    "ATR_SPIKE": (
        "ATR melonjak lebih dari 2× median 100 periode — kemungkinan spike news atau volatilitas abnormal. "
        "Clamp maksimum SL ikut membesar dengan ATR, sehingga reject ini mencegah SL terlalu lebar. "
        "Filter ini melindungi modal saat pasar tidak stabil. Jika terlalu sering, cek apakah ada news rutin atau "
        "turunkan threshold dari 2.0× ke 1.8×."
    ),
    "ATR_DATA_INSUFFICIENT": (
        "Data ATR tidak cukup untuk menjalankan spike filter: kurang dari 102 bar atau lebih dari 50% NaN "
        "dalam 100 periode terakhir. Sinyal ditolak karena filter keamanan tidak bisa divalidasi. "
        "Pastikan BARS >= 200 di .env dan kolom atr_14 terisi penuh sejak warmup."
    ),
    "TP_ORDER_INVALID": (
        "Urutan TP tidak valid setelah obstacle adjustment: tp1 < tp2 < tp3 tidak terpenuhi, "
        "atau jarak antar TP kurang dari 0.3R (30% sl_dist). "
        "Biasanya terjadi saat OBSTACLE_MIN_RR_FRAC terlalu rendah atau obstacle sangat berdekatan. "
        "Sinyal ditolak agar backtest tidak mencatat TP yang hampir identik sebagai target berbeda."
    ),
}


def _categorize(raw: str) -> str:
    """Petakan raw reject reason ke kategori pendek."""
    raw_up = raw.upper().split(":")[0].split("(")[0].strip()
    for prefix, cat in _CATEGORY.items():
        if raw_up.startswith(prefix.upper()):
            return cat
    return raw_up[:20]  # fallback: 20 karakter pertama


def _extract_context(raw: str, df: pd.DataFrame | None) -> str:
    """Ekstrak konteks dari raw reason + df untuk baris log per-TF.
    Contoh: "close=4395.2 EMA200=4412.8 gap=17.6pts (1.1×ATR)" / "skor=1/2".
    """
    raw_up = raw.upper()

    if raw_up.startswith("EMA200_WAJIB") or raw_up.startswith("CT_EMA200"):
        if df is not None:
            try:
                last   = df.iloc[-2]
                close  = float(last.get("close", 0))
                ema200 = _safe(last, "ema_200")
                atr    = _atr_proxy(df)
                if ema200 and atr > 0:
                    gap      = abs(close - ema200)
                    atr_mul  = gap / atr
                    side     = "bawah" if close < ema200 else "atas"
                    return (
                        f"close={close:.1f}  EMA200={ema200:.1f}  "
                        f"gap={gap:.1f}pts ({atr_mul:.1f}x ATR)  [{side} EMA200]"
                    )
            except Exception:
                pass
        # Fallback: ambil dari raw string
        dir_ = re.search(r"dir=(\w+)", raw)
        bias = re.search(r"bias=(\w+)", raw)
        parts = []
        if dir_:  parts.append(f"arah={dir_.group(1)}")
        if bias:  parts.append(f"HTF={bias.group(1)}")
        return "  ".join(parts) if parts else ""

    if raw_up.startswith("CONFLUENCE_FAIL") or raw_up.startswith("INTRADAY_NO") or \
       raw_up.startswith("PULLBACK_NO") or raw_up.startswith("REVERSAL_NO"):
        parts = []
        m_sc = re.search(r"score=(\d+/\d+)", raw)
        if m_sc:
            parts.append(f"skor={m_sc.group(1)}")
        # Ambil komponen dari dalam [...] — strip semua kurung dan isinya agar ringkas
        m_comp = re.search(r"\[([^\]]+)\]", raw)
        if m_comp:
            tokens = []
            for t in m_comp.group(1).split():
                # Ambil bagian sebelum '(' pertama — buang semua kurung nested
                clean = re.sub(r'\([^)]*\)', '', t)  # strip (...)
                clean = clean.rstrip("()")            # bersihkan sisa
                if clean:
                    tokens.append(clean)
            parts.append(" ".join(tokens))
        if not parts:
            parts.append(raw[raw.find(":")+1:][:60] if ":" in raw else raw[:60])
        return "  ".join(parts)

    if raw_up.startswith("TRIGGER_FAIL"):
        m = re.search(r"score=(\d+/\d+)", raw)
        dir_ = re.search(r"dir=(\w+)", raw)
        parts = []
        if dir_:  parts.append(f"arah={dir_.group(1)}")
        if m:     parts.append(f"skor={m.group(1)}")
        return "  ".join(parts)

    if raw_up.startswith("RSI_EXTREME"):
        m = re.search(r"\((\d+\.?\d*)\)", raw)
        if m:
            val = m.group(1)
            kind = "OB" if "OVERBOUGHT" in raw_up else "OS"
            return f"RSI={val} ({kind})"

    if raw_up.startswith("BIAS_FAIL") or raw_up.startswith("BRIDGE_FAIL"):
        idx = raw.find("(")
        if idx != -1:
            # Cari posisi ')' terakhir yang menutup kurung pembuka pertama (handle nested)
            depth = 0
            end_idx = -1
            for i in range(idx, len(raw)):
                if raw[i] == "(":   depth += 1
                elif raw[i] == ")": depth -= 1
                if depth == 0:
                    end_idx = i
                    break
            if end_idx == -1:
                detail = raw[idx + 1:]
            else:
                detail = raw[idx + 1 : end_idx]
            
            if not detail.strip():
                return "tidak ada TF konfirmasi — TF ini adalah yang tertinggi (self-confirm)"
            # Potong rapi di 90 karakter tanpa memotong di tengah kata
            if len(detail) > 90:
                detail = detail[:90].rsplit(" ", 1)[0] + "…"
            return detail
        return ""

    if raw_up.startswith("RR_FAIL"):
        m_rr  = re.search(r"rr=([0-9.]+)", raw)
        m_min = re.search(r"min=([0-9.]+)", raw)
        parts = []
        if m_rr:  parts.append(f"RR={m_rr.group(1)}")
        if m_min: parts.append(f"min={m_min.group(1)}")
        return "  ".join(parts)

    if raw_up.startswith("ATR_TOO_LOW"):
        m = re.search(r"\(([^)]+)\)", raw)
        if m:
            return m.group(1)

    if raw_up.startswith("CT_NO_CHOCH"):
        m = re.search(r"\(([^)]+)\)", raw)
        if m:
            return m.group(1)[:60]

    if raw_up.startswith("COOLDOWN"):
        m = re.search(r"\(([^)]+)\)", raw)
        if m:
            return f"tunggu {m.group(1)}"

    if raw_up.startswith("LATE_ENTRY"):
        dist = re.search(r"dist=([0-9.]+)", raw)
        mx   = re.search(r"max=([0-9.]+)", raw)
        if dist and mx:
            return f"jarak={dist.group(1)} max={mx.group(1)}"

    if raw_up.startswith("OUT_OF_SESSION"):
        m = re.search(r"\(([^)]+)\)", raw)
        if m:
            return f"sesi={m.group(1)}"

    if raw_up.startswith("ASIAN_NO_KEY_LEVEL"):
        m = re.search(r"\[([^\]]+)\]", raw)
        if m:
            return m.group(1)[:60]

    if raw_up.startswith("SNR_BLOCKED") or raw_up.startswith("SNR_WEAK"):
        m = re.search(r"\(([^)]+)\)", raw)
        if m:
            return m.group(1)[:60]

    if raw_up.startswith("DAILY_LIMIT"):
        mode = "scalping" if "SCALPING" in raw_up else "intraday"
        m = re.search(r"\(([^)]+)\)", raw)
        detail = m.group(1) if m else ""
        return f"{mode}: {detail}"

    if raw_up.startswith("MARKET_TRANSITION"):
        adx = re.search(r"adx_(\w+)=([0-9.]+)", raw)
        if adx:
            return f"ADX {adx.group(1)}={adx.group(2)} di bawah ambang block (bawaan 15)"

    return ""


class RejectTracker:
    """Melacak rejection sinyal dan mencetak summary periodik (30 menit):
    total candle/signal per sesi, breakdown reject per kategori + per TF.
    """

    def __init__(self, interval_minutes: int = _SUMMARY_INTERVAL_MIN) -> None:
        self._interval    = timedelta(minutes=interval_minutes)
        self._window_start = datetime.utcnow()
        self._reset_window()

    def _reset_window(self) -> None:
        self._candle_count:  int = 0
        self._signal_count:  int = 0
        self._reject_count:  int = 0
        self._cat_tf: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._cat_total: dict[str, int] = defaultdict(int)

    def record_candle(self) -> None:
        """Panggil setiap kali ada candle close (terlepas sinyal atau tidak)."""
        self._candle_count += 1

    def record_signal(self) -> None:
        """Panggil setiap kali sinyal berhasil di-generate."""
        self._signal_count += 1

    def record_reject(
        self,
        symbol:    str,
        tf:        str,
        raw:       str,
        df:        pd.DataFrame | None = None,
    ) -> str:
        """Catat rejection, kembalikan baris log ringkas untuk dicetak caller.
        Format: "XAUUSD M5 ✗ EMA200_WAJIB | close=4395.2 EMA200=4412.8 gap=17.6pts".
        """
        cat     = _categorize(raw)
        ctx     = _extract_context(raw, df)
        tf_pad  = tf.ljust(3)
        cat_pad = cat.ljust(16)

        line = f"{symbol} {tf_pad} ✗  {cat_pad}"
        if ctx:
            if len(ctx) > 100:
                ctx = ctx[:100].rsplit(" ", 1)[0] + "…"
            line += f" | {ctx}"

        # Update counter window
        self._reject_count += 1
        self._cat_total[cat]   += 1
        self._cat_tf[cat][tf]  += 1

        return line

    def maybe_print_summary(self, symbol: str = "XAUUSD") -> None:
        """Cetak summary jika sudah lewat interval (default 30 mnt); panggil tiap loop."""
        now = datetime.utcnow()
        if now - self._window_start < self._interval:
            return

        elapsed = int((now - self._window_start).total_seconds() / 60)
        self._print_summary(symbol, elapsed)
        self._window_start = now
        self._reset_window()

    def _print_summary(self, symbol: str, elapsed_min: int) -> None:
        """Format dan cetak summary ke terminal + file log."""
        W = 58  # lebar summary box
        border = "═" * W
        divider = "─" * W

        total_reject = self._reject_count
        total_candle = self._candle_count
        total_signal = self._signal_count

        lines: list[str] = []
        lines.append(border)
        lines.append(
            f" REJECT SUMMARY  {symbol}  |  {elapsed_min} menit terakhir"
        )
        lines.append(border)
        lines.append(
            f" Candle close : {total_candle:<4}  "
            f"Signal : {total_signal:<4}  "
            f"Reject : {total_reject}"
        )

        if total_reject == 0:
            lines.append(divider)
            lines.append(" Tidak ada rejection — semua candle menghasilkan sinyal atau tidak close")
            lines.append(border)
            for l in lines:
                logger.info(l)
            return

        lines.append(divider)

        sorted_cats = sorted(
            self._cat_total.items(), key=lambda x: x[1], reverse=True
        )

        for rank, (cat, count) in enumerate(sorted_cats, 1):
            pct      = count / total_reject * 100
            tf_breakdown = self._cat_tf.get(cat, {})
            tf_str   = "  ".join(
                f"{tf}={n}"
                for tf, n in sorted(tf_breakdown.items(), key=lambda x: x[1], reverse=True)
            )
            prefix = f" #{rank}" if rank <= 5 else "   "
            lines.append(
                f"{prefix}  {cat:<18} {count:>3}x ({pct:4.0f}%)  {tf_str}"
            )

        # Tuning hint dari kategori paling dominan
        top_cat = sorted_cats[0][0] if sorted_cats else ""
        hint    = _HINT.get(top_cat, "")
        if hint:
            lines.append(divider)
            words  = hint.split()
            cur    = " Hint: "
            hint_lines: list[str] = []
            for w in words:
                if len(cur) + len(w) + 1 > W - 2:
                    hint_lines.append(cur)
                    cur = "        " + w + " "
                else:
                    cur += w + " "
            if cur.strip():
                hint_lines.append(cur)
            lines.extend(hint_lines)

        lines.append(border)

        for l in lines:
            logger.info(l)

