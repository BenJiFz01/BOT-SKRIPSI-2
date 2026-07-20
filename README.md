# Bot Trading DSS Forex — XAU/USD

**Sistem Pendukung Keputusan (DSS) Sinyal Trading Forex**
Berbasis Multi Analisis Teknikal dengan Integrasi MetaTrader 5 dan Telegram.

> Skripsi — M. Dzikri Zen (3337220001)
> Program Studi Informatika, Universitas Sultan Ageng Tirtayasa

---

## Deskripsi

Bot ini adalah Decision Support System (DSS) berbasis **rule-based intelligent system** yang menganalisis pasar XAU/USD secara otomatis menggunakan kombinasi analisis teknikal multi-timeframe, lalu mengirimkan rekomendasi sinyal BUY/SELL ke Telegram.

**Sistem TIDAK melakukan auto-trading.** Keputusan eksekusi sepenuhnya di tangan trader.

---

## Fitur Utama

- **Multi-Timeframe Analysis (MTA)** — analisis bias dari M5 sampai D1
- **Trigger Score (Layer 1)** — 6 komponen: EMA200, EMA50 pullback, EMA alignment, RSI, MACD, Candle
- **Confluence Score (Layer 2)** — 5 komponen: Candlestick Pattern, RSI/MACD Divergence, Fibonacci, SnR, SnD
- **Dynamic ATR SL/TP** — SL/TP adaptif terhadap volatilitas pasar
- **Session Filter** — sinyal hanya aktif di London + NY session (jam terbaik XAU/USD)
- **Signal Logger** — histori sinyal tersimpan ke CSV & JSON untuk evaluasi
- **Outcome Tracker** — catat WIN/LOSS untuk menghitung win rate

---

## Prasyarat

- Python 3.10+
- MetaTrader 5 terinstal di Windows (bot berjalan di Windows karena MT5 API hanya untuk Windows)
- Akun MT5 (demo atau real) di broker yang mendukung XAU/USD
- Bot Telegram (buat via [@BotFather](https://t.me/BotFather))

---

## Instalasi

### 1. Clone / Download project

```bash
cd "BOT SKRIPSI 2"
```

### 2. Buat virtual environment

```bash
python -m venv venv
venv\Scripts\activate        # Windows
```

### 3. Install dependencies

```bash
pip install MetaTrader5 pandas numpy ta-lib python-dotenv loguru pydantic requests pytz
```

> **Catatan TA-Lib:** Jika instalasi gagal, download wheel dari
> https://github.com/cgohlke/talib-build/releases
> lalu: `pip install TA_Lib-*.whl`

### 4. Konfigurasi environment

```bash
copy .env.example .env      # Windows
# atau
cp .env.example .env        # Linux/Mac
```

Edit file `.env` dan isi:
- `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER` — kredensial MT5 Anda
- `TELEGRAM_BOT_TOKEN` — token dari @BotFather
- `TELEGRAM_CHAT_ID` — ID chat tujuan sinyal

### 5. Sesuaikan path MT5 di connector.py

Buka `src/mt5/connector.py` dan sesuaikan:
```python
TERMINAL_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"
```

---

## Menjalankan Bot

```bash
# Dari folder root project
python -m src.main
```

Bot akan:
1. Connect ke MT5
2. Kirim notifikasi "BOT ONLINE" ke Telegram
3. Monitor candle close setiap 5 detik (sesuai POLL_SECONDS)
4. Analisis multi-timeframe setiap candle close
5. Kirim sinyal ke Telegram jika semua filter lulus
6. Simpan setiap sinyal ke `logs/signal_history.csv`

---

## Update Hasil Sinyal (WIN/LOSS)

Setelah sinyal keluar, trader perlu mencatat hasilnya secara manual:

```bash
python -m src.infra.outcome_updater
```

Menu interaktif akan muncul:
1. Lihat sinyal PENDING
2. Update hasil (WIN_TP1 / WIN_TP2 / WIN_TP3 / LOSS / CANCELLED)
3. Lihat statistik win rate

---

## Struktur Alur Keputusan

```
Candle Close
    │
    ├─ GATE 1: Validasi (bars, ATR, cooldown, session)
    ├─ GATE 2: HTF Bias (vote dari TF lebih tinggi)
    ├─ GATE 3: Trigger Score ≥ 4/6
    ├─ GATE 4: Confluence Score ≥ 2 (Pattern+Fib+SnR+SnD+Divergence)
    └─ GATE 5: SL/TP ATR-based + RR ≥ 1.5
                    │
            ┌───────┴────────┐
            ▼                ▼
     Log ke CSV       Kirim Telegram
```

---

## Komponen Analisis Teknikal

| Komponen | Peran | Layer |
|---|---|---|
| EMA 200 | Filter trend utama (wajib lulus) | Trigger |
| EMA 50 | Filter pullback ke MA | Trigger |
| EMA 20/50/200 alignment | Konfirmasi kekuatan trend | Trigger |
| RSI (14) | Momentum + filter zona ekstrem | Trigger |
| MACD Histogram | Konfirmasi momentum | Trigger |
| Candle close | Konfirmasi arah candle | Trigger |
| Candlestick Patterns (27) | Price action confirmation | Confluence |
| RSI/MACD Divergence | Sinyal reversal premium | Confluence |
| Fibonacci Retracement | Entry di area value | Confluence |
| Support & Resistance | Level historis pasar | Confluence |
| Supply & Demand Zone | Area akumulasi/distribusi | Confluence |

---

## Parameter Konfigurasi

Lihat `.env.example` untuk daftar lengkap parameter dan penjelasannya.

Parameter kunci:

| Parameter | Default | Keterangan |
|---|---|---|
| `MIN_TRIGGER_SCORE` | 4 | Min skor Layer-1 (dari 6) |
| `MIN_CONFLUENCE_SCORE` | 2 | Min skor Layer-2 (Pattern+Fib+SnR+SnD+Div) |
| `MIN_RR` | 1.5 | Min Risk-Reward Ratio |
| `SL_ATR_MULT` | 1.5 | SL = 1.5× ATR |
| `SESSION_FILTER` | true | Aktifkan session filter |

---

## Output Sinyal Telegram

Contoh format sinyal yang dikirim:

```
🟢 SINYAL BUY ↑ XAUUSD
TF: H1  |  2026-07-20T14:00:00
ID: XAUUSD_H1_20260720_140000

📌 Entry Zone : 3310.00 – 3313.00
🛑 Stop Loss  : 3296.50  (ATR-based)
🎯 TP1        : 3329.00
🎯 TP2        : 3341.00
🎯 TP3        : 3357.00
📊 RR         : 1.85R

── Analisis Teknikal ──────────────
📈 HTF Bias   : M15:BULL H4:BULL D1:BULL
🧩 Trigger    : 5/6 [EMA200✓ EMA50✓ ALIGN✓ RSI✓(42) MACD✓ CDL✓]
💎 Confluence : 5 [Pattern++ Div✓ Fib✓ SnR✓ SnD✓]
🕯 Pattern    : ENGULFING, MORNINGSTAR
📐 Fibonacci  : FIB_STRONG(fib_0.618=3311.50)
🔲 SnR        : S~3305.20 R~3340.00
📦 Zone       : SND_DEMAND(3308.50-3313.00)
🔀 Divergence : RSI_DIV
🕐 Sesi       : London
📉 ATR        : 12.5000

⚠️ Rekomendasi manual — bukan auto-trade.
```

---

## Struktur File

```
src/
├── config/         settings.py, timeframes.py
├── mt5/            connector.py, market_data.py
├── features/       indicators.py, patterns.py, fibonacci.py,
│                   zones_snr.py, zones_snd.py, session.py
├── engine/         signal_engine.py, anytf_mta_engine.py
├── models/         signal.py
├── risk/           sl_tp.py, rr.py
├── notify/         telegram.py, templates.py
├── strategy/       timeframe_hierarchy.py
├── infra/          logger.py, scheduler.py,
│                   signal_logger.py, outcome_updater.py
└── main.py
logs/
├── app.log
├── signal_history.csv
└── signal_history.json
```

---

## Lisensi

Proyek ini dibuat untuk keperluan penelitian skripsi. Tidak untuk digunakan sebagai
dasar keputusan investasi tanpa analisis mandiri lebih lanjut.
