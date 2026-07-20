# PRD & ROADMAP — Bot Trading DSS Forex (Skripsi)

**Judul Skripsi:** Perancangan dan Implementasi Sistem Pendukung Keputusan Sinyal Trading Forex Berbasis Multi Analisis dengan Integrasi MetaTrader 5 dan Telegram
**Mahasiswa:** M. Dzikri Zen — NIM 3337220001
**Program Studi:** Informatika, Universitas Sultan Ageng Tirtayasa
**Terakhir diperbarui:** 2026-07-20
**Versi:** 2.0 (revisi perspektif trader profesional)

---

## Daftar Isi

1. [Overview Sistem](#1-overview-sistem)
2. [Prinsip Dasar Trading yang Jadi Landasan](#2-prinsip-dasar-trading-yang-jadi-landasan)
3. [Status Kode Saat Ini](#3-status-kode-saat-ini)
4. [Gap Analysis](#4-gap-analysis)
5. [Spesifikasi Fitur](#5-spesifikasi-fitur)
6. [Arsitektur Sistem](#6-arsitektur-sistem)
7. [Spesifikasi Logika Rule-Based Engine](#7-spesifikasi-logika-rule-based-engine)
8. [Parameter Konfigurasi](#8-parameter-konfigurasi)
9. [Roadmap &amp; Prioritas Pengerjaan](#9-roadmap--prioritas-pengerjaan)
10. [Rencana Evaluasi &amp; Pengujian](#10-rencana-evaluasi--pengujian)
11. [Checklist Kelengkapan Skripsi](#11-checklist-kelengkapan-skripsi)
12. [Struktur File Project](#12-struktur-file-project)

---

## 1. Overview Sistem

### Tujuan

Membangun **Decision Support System (DSS)** berbasis rule-based yang menganalisis pasar forex XAU/USD secara otomatis dan mengirimkan **rekomendasi sinyal trading** (BUY/SELL) kepada trader melalui Telegram. Sistem **tidak** melakukan eksekusi order otomatis — keputusan akhir tetap di tangan trader.

### Filosofi Sistem

> "Sinyal sedikit tapi berkualitas lebih baik dari sinyal banyak tapi noise."

Sistem dirancang **selektif**. Tidak setiap candle close menghasilkan sinyal. Sinyal hanya keluar jika **semua lapisan filter terpenuhi**, termasuk konfluensi multi-analisis teknikal. Ini sesuai cara kerja trader profesional yang hanya masuk market pada setup terbaik.

### Komponen Utama

```
MetaTrader 5 API  →  Python DSS Engine  →  Telegram Bot API
     (data)              (analisis)            (output sinyal)
                              ↓
                       Signal Logger
                     (CSV + JSON history)
```

### Stack Teknologi

| Komponen           | Teknologi                          |
| ------------------ | ---------------------------------- |
| Bahasa             | Python 3.10                        |
| Data pasar         | MetaTrader 5 API (`MetaTrader5`) |
| Indikator teknikal | TA-Lib                             |
| Pengolahan data    | pandas, NumPy                      |
| Notifikasi         | Telegram Bot API (`requests`)    |
| Logging            | loguru                             |
| Konfigurasi        | python-dotenv                      |
| Validasi model     | pydantic                           |

### Instrumen & Timeframe

- **Instrumen:** XAU/USD (emas vs USD)
- **Timeframes aktif:** M5, M15, H1, H4, D1
- **Trigger TF:** Setiap TF bisa jadi trigger (yang mendeteksi entry)
- **Konfirmasi TF:** Semua TF lebih tinggi dari trigger (yang menentukan bias)

---

## 2. Prinsip Dasar Trading yang Jadi Landasan

Bagian ini menjelaskan **mengapa** setiap aturan di sistem ini ada, dari kacamata trader profesional. Ini penting sebagai justifikasi akademik di BAB II/III skripsi.

### 2.1 — Top-Down Analysis (HTF → LTF)

Trader profesional selalu membaca pasar dari timeframe besar ke kecil:

- **D1/H4** → tentukan bias utama (trend dominan)
- **H1/M15** → tentukan area entry yang tepat
- **M5** → timing eksekusi

**Implementasi di sistem:** `higher_timeframes()` + `_vote_bias()` — timeframe lebih tinggi memberi "suara" bias. Sinyal dari trigger TF yang berlawanan dengan HTF otomatis ditolak (Rule R-03, R-04).

### 2.2 — Konfluensi (Confluence)

Setup trading terbaik adalah setup di mana **banyak analisis berbeda menunjuk ke arah yang sama**. Satu indikator saja bisa memberikan false signal. Tapi jika EMA, Fibonacci, SnR, SnD, dan candlestick pattern semua setuju → probabilitas jauh lebih tinggi.

**Implementasi di sistem:** Confluence Score (F-01) — setiap analisis berkontribusi skor, sinyal hanya keluar jika total skor minimum terpenuhi.

### 2.3 — Entry di Area Nilai (Value Area)

Jangan entry sembarangan. Entry terbaik adalah di area di mana harga "wajar" untuk diambil:

- Dekat level Fibonacci 38.2%, 50%, 61.8% (koreksi dari swing)
- Di zona Demand/Supply (area akumulasi institusional)
- Di level Support/Resistance historis

**Implementasi di sistem:** Fib, SnR, SnD confluence score sebagai komponen wajib dalam keputusan.

### 2.4 — Manajemen Risiko Adaptif

SL/TP harus menyesuaikan volatilitas pasar saat ini, bukan nilai tetap. XAU/USD bisa bergerak 50 pip dalam 5 menit saat news, atau hanya 20 pip sepanjang hari Asian session. Fixed pip SL tidak representatif.

**Implementasi di sistem:** ATR-based SL/TP (F-02) — SL = 1.5× ATR, TP1/2/3 = RR 1.5/2.5/4.0.

### 2.5 — Sesi Trading Berpengaruh pada Kualitas Sinyal

XAU/USD punya karakter berbeda per sesi:

| Sesi         | Waktu WIB    | Karakter                                     | Kualitas Sinyal |
| ------------ | ------------ | -------------------------------------------- | --------------- |
| Asian        | 02:00–08:00 | Range sempit, fake breakout tinggi           | ⚠️ Rendah     |
| London Open  | 14:00–17:00 | Volatilitas mulai tinggi, trend sering mulai | ✅ Tinggi       |
| New York     | 19:00–23:00 | Paling volatile, pergerakan besar            | ✅ Tinggi       |
| Overlap L+NY | 19:00–22:00 | Volume maksimal                              | ✅✅ Tertinggi  |

**Implementasi di sistem:** Session filter (F-05) — sinyal hanya dikirim di jam London + NY session, kecuali TF besar (H4, D1) yang tidak sensitif sesi.

### 2.6 — Divergence sebagai Setup Reversal Premium

RSI divergence (harga buat lower low tapi RSI buat higher low) adalah salah satu setup reversal paling reliable di XAU/USD. Sudah dihitung di kode tapi belum digunakan — ini harus jadi bagian dari confluence score.

### 2.7 — Selektivitas > Kuantitas

`min_trigger_score = 3/6` (50%) terlalu longgar. Trader profesional hanya masuk di setup 80%+. Untuk sistem ini, score minimum yang masuk akal adalah **4/6** untuk trigger, dengan tambahan confluence score dari Fib/SnR/SnD/Pattern.

---

## 3. Status Kode Saat Ini

### ✅ Sudah Berjalan dengan Baik

| Modul                 | File                               | Keterangan                                          |
| --------------------- | ---------------------------------- | --------------------------------------------------- |
| Koneksi MT5           | `src/mt5/connector.py`           | Login & account info                                |
| Pengambilan data OHLC | `src/mt5/market_data.py`         | `fetch_ohlc()` per TF                             |
| Indikator teknikal    | `src/features/indicators.py`     | RSI, EMA 20/50/200, MACD, ATR,**divergence**  |
| Candlestick patterns  | `src/features/patterns.py`       | 27 pattern via TA-Lib                               |
| Fibonacci             | `src/features/fibonacci.py`      | Levels +`fib_confluence_score()`                  |
| Zona SnR              | `src/features/zones_snr.py`      | Swing points +`snr_confluence_score()`            |
| Zona SnD              | `src/features/zones_snd.py`      | Base zone +`snd_confluence_score()`               |
| HTF bias voting       | `src/engine/anytf_mta_engine.py` | EMA50/200 per TF                                    |
| Trigger scoring       | `src/engine/anytf_mta_engine.py` | 6 komponen                                          |
| SL/TP fixed pip       | `src/risk/sl_tp.py`              | `fixed_zone_sltp()` — *dipakai*                |
| SL/TP dynamic ATR     | `src/risk/sl_tp.py`              | `dynamic_atr_sltp()` — *dibuat, belum dipakai* |
| Risk-Reward filter    | `src/risk/rr.py`                 | Filter`min_rr` aktif                              |
| Candle close watcher  | `src/infra/scheduler.py`         | Deteksi bar baru                                    |
| Pengiriman Telegram   | `src/notify/telegram.py`         | `send_message()` HTML                             |
| Format pesan          | `src/notify/templates.py`        | `format_signal()`                                 |
| Signal logger         | `src/infra/signal_logger.py`     | CSV + JSON —*dibuat, belum aktif*                |
| Outcome updater CLI   | `src/infra/outcome_updater.py`   | Update WIN/LOSS —*dibuat, belum aktif*           |
| Main loop             | `src/main.py`                    | Poll + trigger per candle close                     |

### ⚠️ Masalah Kritis yang Ditemukan

**1. Pattern, Fibonacci, SnR, SnD tidak mempengaruhi keputusan apapun**
Semua ini sudah dihitung tapi hasilnya hanya ditampilkan sebagai teks di reason string. Tidak ada satupun yang menjadi kondisi `IF` dalam logika pengambilan keputusan. Artinya **sistem saat ini bukan "multi-analisis"** — hanya EMA + MACD + RSI biasa.

**2. min_trigger_score default = 3 terlalu longgar**
Setup dengan hanya 50% kriteria terpenuhi menghasilkan terlalu banyak false signal, terutama di market choppy.

**3. ATR SL/TP tidak dipakai**
Fixed pip SL/TP berbahaya untuk XAU/USD yang volatilitasnya sangat dinamis.

**4. Divergence dihitung tapi dibuang**
`rsi_bull_div` dan `macd_bull_div` ada di DataFrame tapi tidak masuk engine sama sekali.

**5. Tidak ada session filter**
Sinyal bisa keluar jam 03:00 pagi (Asian session) di mana kualitas setup XAU/USD sangat rendah.

**6. Signal Logger tidak aktif**
Tidak ada histori sinyal → tidak ada data untuk evaluasi skripsi BAB IV.

---

## 4. Gap Analysis

| #  | Kebutuhan Proposal + Trading                     | Status                             | Prioritas |
| -- | ------------------------------------------------ | ---------------------------------- | --------- |
| 1  | Multi-Timeframe Analysis (MTA)                   | ✅ Berjalan                        | —        |
| 2  | RSI sebagai filter + oversold/overbought zone    | ⚠️ Partial                       | KRITIKAL  |
| 3  | EMA 20/50/200 + trend alignment                  | ✅ Berjalan                        | —        |
| 4  | MACD konfirmasi                                  | ✅ Berjalan                        | —        |
| 5  | RSI/MACD Divergence sebagai konfirmasi reversal  | ❌ Dihitung, tidak dipakai         | KRITIKAL  |
| 6  | Fibonacci Retracement sebagai filter zona entry  | ⚠️ Partial — hanya teks         | KRITIKAL  |
| 7  | Support & Resistance sebagai filter              | ⚠️ Partial — hanya teks         | KRITIKAL  |
| 8  | Supply & Demand Zone sebagai filter              | ⚠️ Partial — hanya teks         | KRITIKAL  |
| 9  | Candlestick patterns (price action)              | ⚠️ Partial — tidak masuk engine | KRITIKAL  |
| 10 | Confluence Score (semua analisis terintegrasi)   | ❌ Belum ada                       | KRITIKAL  |
| 11 | Risk-Reward Ratio minimum                        | ✅ Berjalan                        | —        |
| 12 | Dynamic ATR SL/TP (adaptif volatilitas)          | ⚠️ Dibuat, tidak dipakai         | TINGGI    |
| 13 | Session filter (London + NY only)                | ❌ Belum ada                       | TINGGI    |
| 14 | min_trigger_score lebih selektif (≥4/6)         | ⚠️ Default terlalu rendah        | TINGGI    |
| 15 | Pengiriman sinyal via Telegram                   | ✅ Berjalan                        | —        |
| 16 | Format sinyal informatif (semua analisis tampil) | ⚠️ Partial                       | SEDANG    |
| 17 | Pencatatan histori sinyal (Signal Logger aktif)  | ⚠️ Dibuat, tidak aktif           | KRITIKAL  |
| 18 | Evaluasi akurasi / win rate untuk skripsi        | ❌ Belum ada data                  | KRITIKAL  |
| 19 | File`.env.example` & README setup              | ❌ Belum ada                       | SEDANG    |

---

## 5. Spesifikasi Fitur

### F-01 — Confluence Score Engine (KRITIKAL)

**Masalah:** Fibonacci, SnR, SnD, Pattern sudah dihitung tapi tidak mempengaruhi keputusan apapun. Ini bertentangan langsung dengan judul skripsi "multi analisis" dan konsep konfluensi trading.

**Solusi:** Tambahkan lapisan **Confluence Score** setelah trigger_score lulus. Setiap analisis berkontribusi skor. Sinyal final hanya keluar jika `confluence_score >= min_confluence_score`.

**Skema skor (total maks 11 poin):**

| Layer                         | Komponen            | Skor      | Kondisi                                       |
| ----------------------------- | ------------------- | --------- | --------------------------------------------- |
| **Layer 1: Trigger**    | EMA200 trend        | 1 (wajib) | close di sisi benar dari EMA200               |
|                               | EMA50 pullback      | 1         | \|close - EMA50\| ≤ 2×ATR                   |
|                               | EMA alignment       | 1         | EMA20 > 50 > 200 (BUY) / sebaliknya           |
|                               | RSI arah            | 1         | RSI naik (BUY) / turun (SELL), tidak ekstrem  |
|                               | MACD histogram      | 1         | Hist naik (BUY) / turun (SELL)                |
|                               | Candle konfirmasi   | 1         | Candle bullish (BUY) / bearish (SELL)         |
| **Layer 2: Confluence** | Candlestick Pattern | 0–2      | ≥1 pattern = +1, ≥2 pattern = +2            |
|                               | RSI/MACD Divergence | 0–1      | Divergence terdeteksi = +1                    |
|                               | Fibonacci           | 0–2      | Near fib = +1, strong fib (38.2/50/61.8) = +2 |
|                               | SnR                 | 0–1      | Entry dekat Support/Resistance = +1           |
|                               | SnD Zone            | 0–1      | Entry di dalam Supply/Demand zone = +1        |

**Default threshold:**

- `min_trigger_score = 4` (naik dari 3, lebih selektif)
- `min_confluence_score = 2` (minimal 2 poin dari Layer 2)

**Justifikasi akademik:** Sesuai prinsip konfluensi dalam analisis teknikal — sinyal yang dikonfirmasi oleh multiple metode memiliki probabilitas lebih tinggi (Singh, 2025; Ghanem et al., 2024).

**File:** `src/engine/anytf_mta_engine.py`, `src/models/signal.py`

---

### F-02 — Dynamic ATR SL/TP sebagai Primary (KRITIKAL)

**Masalah:** Fixed pip SL/TP tidak adaptif terhadap volatilitas XAU/USD. Di hari news (FOMC, NFP), volatilitas bisa 3× lipat normal — fixed SL 50 pip bisa terlalu ketat atau terlalu lebar.

**Solusi:** Aktifkan `dynamic_atr_sltp()` yang sudah ada sebagai metode utama, dengan `fixed_zone_sltp()` sebagai fallback.

**Logika SL/TP:**

```
ATR valid (> 0) → dynamic_atr_sltp(sl_atr_mult=1.5, tp1_rr=1.5, tp2_rr=2.5, tp3_rr=4.0)
ATR tidak valid  → fixed_zone_sltp() sebagai fallback
```

**Contoh nyata XAU/USD:**

- ATR M15 = 150 pip → SL = 225 pip, TP1 = 337 pip (RR 1.5)
- ATR M15 = 40 pip → SL = 60 pip, TP1 = 90 pip (RR 1.5)

**Justifikasi akademik:** SL/TP berbasis ATR terbukti lebih adaptif dan memberikan performa lebih baik dibanding fixed pip pada instrumen dengan volatilitas dinamis (Kute et al., 2023).

**File:** `src/engine/anytf_mta_engine.py`

---

### F-03 — Session Filter (TINGGI)

**Masalah:** Sistem saat ini mengirim sinyal 24 jam non-stop. Di Asian session (02:00–08:00 WIB), XAU/USD sering choppy dan banyak fake breakout — kualitas sinyal sangat rendah.

**Solusi:** Filter sesi trading — sinyal hanya dikirim pada jam London dan New York session. Timeframe besar (H4, D1) dikecualikan dari filter karena mereka tidak sensitif sesi.

**Aturan session filter:**

| TF      | Session Filter                                    | Alasan                                   |
| ------- | ------------------------------------------------- | ---------------------------------------- |
| M5, M15 | London (14:00–23:00 WIB) + NY (19:00–02:00 WIB) | Sangat sensitif sesi                     |
| H1      | London + NY + sedikit overlap                     | Agak sensitif sesi                       |
| H4, D1  | Tidak difilter                                    | Mewakili trend makro, tidak sensitif jam |

**Jam trading aktif (WIB / UTC+7):**

- London session: 14:00 – 23:00 WIB
- New York session: 19:00 – 02:00 WIB
- Overlap terbaik: 19:00 – 22:00 WIB

**File baru:** `src/features/session.py`
**File dimodifikasi:** `src/engine/anytf_mta_engine.py`, `src/config/settings.py`

---

### F-04 — Aktifkan RSI/MACD Divergence di Engine (TINGGI)

**Masalah:** `rsi_bull_div` dan `macd_bull_div` sudah dihitung di `indicators.py` tapi tidak digunakan di engine sama sekali. Divergence adalah salah satu setup reversal paling reliable di XAU/USD.

**Solusi:** Tambahkan divergence sebagai komponen confluence score.

**Aturan:**

- BUY: `rsi_bull_div == True` OR `macd_bull_div == True` → +1 confluence
- SELL: `rsi_bear_div == True` OR `macd_bear_div == True` → +1 confluence

**Justifikasi akademik:** Divergence RSI/MACD merupakan indikator pembalikan tren yang diakui secara luas dan terbukti meningkatkan akurasi sinyal entry (Singh, 2025).

**File:** `src/engine/anytf_mta_engine.py`

---

### F-05 — Aktifkan Signal Logger di Main (KRITIKAL)

**Masalah:** `SignalLogger` sudah lengkap di `signal_logger.py` tapi tidak pernah dipanggil dari `main.py`. Tidak ada histori sinyal → tidak ada data untuk evaluasi di skripsi BAB IV.

**Solusi:** Inisialisasi `SignalLogger` di `main.py` dan panggil `log_signal(sig)` setiap kali sinyal berhasil digenerate. Kirim juga `signal_id` ke Telegram agar trader bisa update outcome.

**File:** `src/main.py`

---

### F-06 — Perbarui Format Pesan Telegram (SEDANG)

**Masalah:** Pesan Telegram saat ini tidak menampilkan confluence score, pattern terdeteksi, dan zone secara eksplisit. Untuk skripsi, bukti bahwa semua analisis teknikal ditampilkan sangat penting.

**Solusi:** Perbarui `format_signal()` agar semua komponen analisis tampil secara terstruktur.

**Format target:**

```
🟢 SINYAL BUY — XAUUSD
TF: H1  |  2026-07-20 14:00 WIB
ID: XAUUSD_H1_20260720_140000

📌 Entry Zone : 3310.00 – 3313.00
🛑 Stop Loss  : 3296.50  (ATR-based)
🎯 TP1        : 3329.00  (RR 1.5)
🎯 TP2        : 3341.00  (RR 2.5)
🎯 TP3        : 3357.00  (RR 4.0)
📊 RR         : 1.85R

── Analisis Teknikal ──────────────
📈 HTF Bias   : M15:BULL H4:BULL D1:BULL
🧩 Trigger    : 5/6 [EMA200✓ EMA50✓ ALIGN✓ RSI✓(42) MACD✓ CDL✓]
💎 Confluence : 6/5 [Pattern✓ Fib✓(0.618) SnR✓ SnD✓ Div✓]
🕯 Pattern    : Engulfing, Morning Star
📐 Fibonacci  : 61.8% = 3311.50 (STRONG)
🔲 SnR        : Support~3305.20 | Resistance~3340.00
📦 Zone       : Demand 3308.50 – 3313.00
🕐 Sesi       : London Open

⚠️ Rekomendasi manual — bukan auto-trade.
```

**File:** `src/notify/templates.py`, `src/models/signal.py`

---

### F-07 — Naikkan Default min_trigger_score ke 4 (TINGGI)

**Masalah:** Default 3/6 (50%) terlalu longgar. Menghasilkan terlalu banyak false signal terutama di kondisi ranging market.

**Solusi:** Ubah default `MIN_TRIGGER_SCORE` menjadi **4** di `.env.example` dan dokumentasi. Nilai ini bisa dikonfigurasi ulang via `.env` sesuai preferensi trader.

**Dampak:** Jumlah sinyal berkurang, tapi kualitas (win rate) meningkat.

**File:** `.env.example`, `src/config/settings.py`

---

### F-08 — File `.env.example` & README (SEDANG)

**Masalah:** Tidak ada template konfigurasi dan dokumentasi setup. Penting untuk reproducibility penelitian dan penilaian skripsi.

**File dibuat:** `.env.example`, `README.md`

---

### F-09 — Command `/stats` via Telegram (OPSIONAL)

Kirim laporan win rate langsung ke Telegram dengan command `/stats`. `SignalLogger.format_stats_telegram()` sudah siap, tinggal disambungkan ke webhook atau polling command.

---

## 6. Arsitektur Sistem

```
┌────────────────────────────────────────────────────────────────────┐
│                         MAIN LOOP                                  │
│  Poll setiap N detik → deteksi candle close → trigger per TF       │
└───────────────────────────┬────────────────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────────────────┐
│                    DATA LAYER (MT5)                                │
│  fetch_ohlc(symbol, tf, bars)  →  DataFrame OHLC per TF           │
└───────────────────────────┬────────────────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────────────────┐
│              PREPROCESSING & FEATURE EXTRACTION                    │
│                                                                    │
│  add_indicators() → RSI, EMA 20/50/200, MACD, ATR, Divergence     │
│  add_patterns()   → 27 candlestick pattern (TA-Lib)               │
└───────────────────────────┬────────────────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────────────────┐
│              RULE-BASED DECISION ENGINE                            │
│                                                                    │
│  GATE 1 — Validasi Awal                                           │
│    • bars cukup (≥220)?                                            │
│    • ATR valid & tidak terlalu kecil?                              │
│    • Cooldown sudah habis?                                         │
│    • [NEWs] Dalam session aktif? (F-03)                            │
│                                                                    │
│  GATE 2 — HTF Bias                                                 │
│    • Vote dari semua TF lebih tinggi (EMA50 vs EMA200)             │
│    • Majority = BULL / BEAR / None                                 │
│                                                                    │
│  GATE 3 — Trigger Score (Layer 1, max 6)          default ≥4      │
│    • [WAJIB] EMA200 side                                           │
│    • EMA50 pullback                                                │
│    • EMA alignment (20>50>200)                                     │
│    • RSI arah & zone                                               │
│    • MACD histogram arah                                           │
│    • Candle konfirmasi                                             │
│                                                                    │
│  GATE 4 — Confluence Score (Layer 2, max 5)       default ≥2      │
│    • Candlestick Pattern (0–2)         ← F-01                      │
│    • RSI/MACD Divergence (0–1)         ← F-04                      │
│    • Fibonacci confluence (0–2)        ← F-01                      │
│    • SnR confluence (0–1)              ← F-01                      │
│    • SnD Zone confluence (0–1)         ← F-01                      │
│                                                                    │
│  GATE 5 — SL/TP & RR Filter                                        │
│    • ATR-based SL/TP (primary)         ← F-02                      │
│    • Fixed pip SL/TP (fallback)                                    │
│    • RR ≥ min_rr                                                   │
└────────┬──────────────────────────────────────┬────────────────────┘
         │ SIGNAL                                │ NO SIGNAL
         ▼                                       ▼
┌─────────────────────┐                   log reject_reason
│   OUTPUT LAYER      │
│                     │
│  Signal Logger      │  → logs/signal_history.csv
│  (F-05)             │  → logs/signal_history.json
│                     │
│  Telegram Notifier  │  → Pesan sinyal lengkap (F-06)
│  (format_signal)    │     dengan confluence detail
└─────────────────────┘
         │
         ▼ (manual, oleh trader)
┌─────────────────────┐
│  Outcome Updater    │  → update WIN_TP1 / LOSS / dll
│  (CLI interaktif)   │  → statistik win rate
└─────────────────────┘
```

---

## 7. Spesifikasi Logika Rule-Based Engine

### 7.1 — Alur Keputusan Lengkap (Pseudocode)

```
FUNCTION evaluate_signal(symbol, trigger_tf, data_by_tf):

  df = data_by_tf[trigger_tf]

  # ── GATE 1: Validasi Awal ────────────────────────────────────
  IF len(df) < 220:
      REJECT "NOT_ENOUGH_BARS"

  IF ATR <= 0 OR ATR < price * atr_min_pct:
      REJECT "ATR_INVALID / ATR_TOO_LOW"

  IF time_since_last_signal < cooldown_bars:
      REJECT "COOLDOWN"

  IF session_filter_enabled AND trigger_tf IN [M5, M15, H1]:
      IF current_hour NOT IN london_ny_hours:
          REJECT "OUT_OF_SESSION"

  # ── GATE 2: HTF Bias ─────────────────────────────────────────
  FOR each tf IN higher_timeframes(trigger_tf):
      IF close > EMA200 AND EMA50 > EMA200: vote BULL
      IF close < EMA200 AND EMA50 < EMA200: vote BEAR
      ELSE: vote NEUTRAL

  bias = majority(BULL votes, BEAR votes)
  IF confirm_votes < min_confirm_votes: bias = None

  direction = "BUY" if bias == BULL else "SELL" if bias == BEAR else try_both

  # ── GATE 3: Trigger Score (Layer 1) ──────────────────────────
  score = 0

  # [WAJIB] EMA200
  IF direction == BUY AND close > EMA200:  score += 1
  ELIF direction == SELL AND close < EMA200: score += 1
  ELSE: REJECT "EMA200_FAIL (wajib)"

  # EMA50 pullback
  IF |close - EMA50| <= 2 * ATR: score += 1

  # EMA alignment
  IF BUY  AND EMA20 > EMA50 > EMA200: score += 1
  IF SELL AND EMA20 < EMA50 < EMA200: score += 1

  # RSI
  IF BUY  AND RSI < 75 AND RSI > RSI_prev: score += 1
  IF SELL AND RSI > 25 AND RSI < RSI_prev: score += 1

  # MACD histogram
  IF BUY  AND macd_hist > macd_hist_prev: score += 1
  IF SELL AND macd_hist < macd_hist_prev: score += 1

  # Candle konfirmasi
  IF BUY  AND close > open: score += 1
  IF SELL AND close < open: score += 1

  IF score < min_trigger_score:   # default 4
      REJECT "TRIGGER_FAIL score={score}/{min_trigger_score}"

  # ── GATE 4: Confluence Score (Layer 2) ───────────────────────
  conf_score = 0
  conf_notes = []

  # Candlestick Pattern
  IF BUY  AND pattern_bull_count >= 2: conf_score += 2; note "Pattern++"
  ELIF BUY AND pattern_bull_count >= 1: conf_score += 1; note "Pattern+"
  IF SELL AND pattern_bear_count >= 2: conf_score += 2; note "Pattern++"
  ELIF SELL AND pattern_bear_count >= 1: conf_score += 1; note "Pattern+"

  # Divergence
  IF BUY  AND (rsi_bull_div OR macd_bull_div): conf_score += 1; note "Div✓"
  IF SELL AND (rsi_bear_div OR macd_bear_div): conf_score += 1; note "Div✓"

  # Fibonacci
  fib_score, fib_note = fib_confluence_score(direction, entry, df, ATR)
  conf_score += fib_score; note fib_note

  # SnR
  snr_score = snr_confluence_score(direction, entry, df, ATR)
  conf_score += snr_score

  # SnD
  snd_score, snd_note = snd_confluence_score(direction, entry, df, ATR)
  conf_score += snd_score

  IF conf_score < min_confluence_score:   # default 2
      REJECT "CONFLUENCE_FAIL conf={conf_score}/{min_confluence_score}"

  # ── GATE 5: SL/TP & RR ───────────────────────────────────────
  IF ATR valid:
      plan = dynamic_atr_sltp(direction, price, ATR)
  ELSE:
      plan = fixed_zone_sltp(direction, price)   # fallback

  IF plan is None: REJECT "SLTP_NONE"

  rr = calc_rr(direction, entry, plan.sl, plan.tp1)
  IF rr < min_rr: REJECT "RR_FAIL rr={rr}"

  # ── OUTPUT ───────────────────────────────────────────────────
  RETURN Signal(
      symbol, tf, direction,
      entry, sl, tp1, tp2, tp3, rr,
      trigger_score = score,
      confluence_score = conf_score,
      reason = full_analysis_string
  )
```

### 7.2 — Tabel Aturan IF-THEN (Sesuai Proposal + Perspektif Trader)

| #    | Kondisi (IF)                                        | Aksi (THEN)                               | Referensi             |
| ---- | --------------------------------------------------- | ----------------------------------------- | --------------------- |
| R-01 | close > EMA200 AND EMA50 > EMA200 AND HTF bias BULL | Arah = BUY                                | Prinsip 2.1           |
| R-02 | close < EMA200 AND EMA50 < EMA200 AND HTF bias BEAR | Arah = SELL                               | Prinsip 2.1           |
| R-03 | HTF bias berlawanan dengan arah trigger             | REJECT — sinyal dibatalkan               | Prinsip 2.1           |
| R-04 | trigger_score < 4 (min_trigger_score)               | REJECT — tidak cukup konfirmasi          | Prinsip 2.7           |
| R-05 | conf_score < 2 (min_confluence_score)               | REJECT — tidak ada konfluensi            | Prinsip 2.2           |
| R-06 | Session M5/M15/H1 di luar London+NY                 | REJECT — kualitas sinyal rendah          | Prinsip 2.5           |
| R-07 | Bars < 220                                          | REJECT — data tidak cukup                | —                    |
| R-08 | ATR terlalu kecil atau nol                          | REJECT — market flat/tidak valid         | Prinsip 2.4           |
| R-09 | RSI < 30 AND di zona Demand (SnD)                   | Divergence oversold, +1 confluence BUY    | R-05, Proposal        |
| R-10 | RSI > 70 AND di zona Supply (SnD)                   | Divergence overbought, +1 confluence SELL | R-05, Proposal        |
| R-11 | Pattern bullish (engulfing/pin bar/dll) terdeteksi  | +skor confluence BUY                      | Prinsip 2.3, Proposal |
| R-12 | Pattern bearish terdeteksi                          | +skor confluence SELL                     | Prinsip 2.3, Proposal |
| R-13 | Entry dekat level Fib 38.2/50/61.8                  | +2 conf (strong fib)                      | Prinsip 2.3, Proposal |
| R-14 | Entry dekat Support (BUY) / Resistance (SELL)       | +1 conf                                   | Prinsip 2.3, Proposal |
| R-15 | Entry di dalam Demand (BUY) / Supply (SELL) zone    | +1 conf                                   | Prinsip 2.3, Proposal |
| R-16 | RSI/MACD divergence terdeteksi                      | +1 conf                                   | Prinsip 2.6           |
| R-17 | RR < min_rr                                         | REJECT — manajemen risiko tidak layak    | Prinsip 2.4, Proposal |
| R-18 | Cooldown belum habis                                | REJECT — cegah sinyal spam               | Prinsip 2.7           |
| R-19 | Semua gate lulus                                    | GENERATE Signal → Log → Kirim Telegram  | —                    |

---

## 8. Parameter Konfigurasi

Semua parameter dikonfigurasi via file `.env`.

| Parameter                | Default Lama        | Default Baru        | Alasan Perubahan                          |
| ------------------------ | ------------------- | ------------------- | ----------------------------------------- |
| `SYMBOLS`              | `XAUUSD`          | `XAUUSD`          | —                                        |
| `TIMEFRAMES`           | `M5,M15,H1,H4,D1` | `M5,M15,H1,H4,D1` | —                                        |
| `BARS`                 | `800`             | `800`             | —                                        |
| `POLL_SECONDS`         | `5`               | `5`               | —                                        |
| `MIN_RR`               | `1.0`             | `1.5`             | RR 1.0 terlalu rendah untuk trading nyata |
| `MIN_TRIGGER_SCORE`    | `3`               | `4`               | Lebih selektif, kurangi false signal      |
| `MIN_CONFIRM_VOTES`    | `1`               | `1`               | —                                        |
| `MIN_CONFLUENCE_SCORE` | *(belum ada)*     | `2`               | Filter confluence baru                    |
| `COOLDOWN_BARS`        | `2`               | `3`               | Cegah sinyal terlalu berdekatan           |
| `ATR_MIN_PCT`          | `0.0006`          | `0.0006`          | —                                        |
| `SL_ATR_MULT`          | *(belum aktif)*   | `1.5`             | 1.5× ATR untuk SL                        |
| `TP1_RR`               | *(belum aktif)*   | `1.5`             | TP1 = RR 1.5                              |
| `TP2_RR`               | *(belum aktif)*   | `2.5`             | TP2 = RR 2.5                              |
| `TP3_RR`               | *(belum aktif)*   | `4.0`             | TP3 = RR 4.0                              |
| `SESSION_FILTER`       | *(belum ada)*     | `true`            | Aktifkan session filter                   |
| `SESSION_TZ`           | *(belum ada)*     | `Asia/Jakarta`    | Timezone referensi                        |
| `SESSION_LTF_HOURS`    | *(belum ada)*     | `14-02`           | Jam aktif untuk M5/M15/H1 (WIB)           |
| `MT5_LOGIN`            | —                  | —                  | —                                        |
| `MT5_PASSWORD`         | —                  | —                  | —                                        |
| `MT5_SERVER`           | —                  | —                  | —                                        |
| `TELEGRAM_BOT_TOKEN`   | —                  | —                  | —                                        |
| `TELEGRAM_CHAT_ID`     | —                  | —                  | —                                        |

---

## 9. Roadmap & Prioritas Pengerjaan

### Phase 1 — Core Engine Fix (KRITIKAL, kerjakan duluan)

> Tanpa ini sistem belum bisa disebut "multi-analisis" sesuai proposal.

| ID   | Fitur                                                         | File Utama              | Estimasi |
| ---- | ------------------------------------------------------------- | ----------------------- | -------- |
| F-01 | Confluence Score: sambungkan Pattern, Fib, SnR, SnD ke engine | `anytf_mta_engine.py` | 3–4 jam |
| F-04 | Aktifkan Divergence di confluence score                       | `anytf_mta_engine.py` | 30 menit |
| F-02 | Aktifkan Dynamic ATR SL/TP sebagai primary                    | `anytf_mta_engine.py` | 1 jam    |
| F-07 | Naikkan default min_trigger_score → 4, min_rr → 1.5         | `settings.py`         | 15 menit |
| F-05 | Aktifkan SignalLogger di main.py                              | `main.py`             | 30 menit |

**Deliverable Phase 1:**

- Semua 10+ komponen analisis teknikal mempengaruhi keputusan
- Setiap sinyal punya `trigger_score` dan `confluence_score`
- Setiap sinyal tersimpan ke `logs/signal_history.csv`
- SL/TP adaptif terhadap volatilitas pasar

---

### Phase 2 — Quality of Life (PENTING)

> Meningkatkan kualitas sinyal dan kelengkapan output.

| ID   | Fitur                                                   | File Utama                                     | Estimasi |
| ---- | ------------------------------------------------------- | ---------------------------------------------- | -------- |
| F-03 | Session filter (London + NY)                            | `session.py` (baru), `anytf_mta_engine.py` | 2 jam    |
| F-06 | Update format pesan Telegram (tampilkan semua analisis) | `templates.py`, `signal.py`                | 2 jam    |
| F-08 | Buat`.env.example` dan `README.md`                  | baru                                           | 1 jam    |

**Deliverable Phase 2:**

- Sinyal tidak keluar di jam Asian session (kualitas rendah)
- Screenshot Telegram bisa langsung masuk laporan skripsi
- Orang lain bisa setup bot hanya dengan ikuti README

---

### Phase 3 — Data Collection & Evaluasi (untuk BAB IV Skripsi)

> Kumpulkan data empiris untuk evaluasi akademik.

| Aktivitas                                      | Durasi           | Tools                  |
| ---------------------------------------------- | ---------------- | ---------------------- |
| Jalankan bot live (forward testing)            | Minimal 2 minggu | `main.py`            |
| Update outcome sinyal (WIN/LOSS) secara manual | Setiap hari      | `outcome_updater.py` |
| Generate laporan statistik                     | Di akhir periode | `signal_logger.py`   |
| Analisis per TF, per arah, per session         | —               | Excel / Python         |
| Tangkap screenshot sinyal Telegram             | Setiap sinyal    | —                     |

**Deliverable Phase 3:**

- Tabel data sinyal ≥30 sinyal untuk lampiran skripsi
- Statistik win rate, avg RR, breakdown per TF
- Analisis perbandingan performa antar timeframe

---

### Phase 4 — Fitur Tambahan (OPSIONAL, jika ada waktu)

| ID   | Fitur                               | Keterangan                                          |
| ---- | ----------------------------------- | --------------------------------------------------- |
| F-09 | Command`/stats` di Telegram       | `SignalLogger.format_stats_telegram()` sudah siap |
| —   | Export CSV ke Excel otomatis        | Untuk lampiran skripsi                              |
| —   | Notifikasi di saat sesi London buka | Reminder trader                                     |
| —   | Backtesting mode                    | Simulasi pada data historis                         |

---

### Urutan Pengerjaan

```
[SEKARANG]
    │
    ▼
Phase 1 (1–2 hari):
F-01 (Confluence) → F-04 (Divergence) → F-02 (ATR SL/TP) → F-07 (parameter) → F-05 (Logger)
    │
    ▼
Phase 2 (1 hari):
F-03 (Session Filter) → F-06 (Format Telegram) → F-08 (README + .env.example)
    │
    ▼
[Live Testing 2–3 Minggu]
    │
    ▼
Phase 3:
Kumpulkan data → Update outcome harian → Analisis → Tulis BAB IV
    │
    ▼
[Selesai Skripsi]
```

---

## 10. Rencana Evaluasi & Pengujian

### 10.1 — Pengujian Fungsional (Black-Box per Aturan)

| Test Case | Kondisi Input                                   | Expected Output                      |
| --------- | ----------------------------------------------- | ------------------------------------ |
| TC-01     | close > EMA200, HTF BULL, score ≥ 4, conf ≥ 2 | Sinyal BUY terkirim                  |
| TC-02     | close < EMA200, HTF BEAR, score ≥ 4, conf ≥ 2 | Sinyal SELL terkirim                 |
| TC-03     | HTF bias BEAR, trigger arah BUY                 | REJECT: TRIGGER_FAIL (EMA200 wajib)  |
| TC-04     | trigger_score = 3 (< min 4)                     | REJECT: TRIGGER_FAIL                 |
| TC-05     | conf_score = 1 (< min 2)                        | REJECT: CONFLUENCE_FAIL              |
| TC-06     | RR = 1.2 (< min 1.5)                            | REJECT: RR_FAIL                      |
| TC-07     | Cooldown belum habis                            | REJECT: COOLDOWN                     |
| TC-08     | Jam 04:00 WIB, TF M15, session filter ON        | REJECT: OUT_OF_SESSION               |
| TC-09     | Jam 04:00 WIB, TF H4, session filter ON         | Tidak difilter (H4 bebas sesi)       |
| TC-10     | Bars < 220                                      | REJECT: NOT_ENOUGH_BARS              |
| TC-11     | Pattern engulfing terdeteksi                    | conf_score += 1                      |
| TC-12     | Entry di Fib 61.8% (strong)                     | conf_score += 2                      |
| TC-13     | RSI bull divergence terdeteksi                  | conf_score += 1                      |
| TC-14     | ATR valid → SL/TP dihitung                     | Method = "DynamicATR" di log         |
| TC-15     | ATR = 0 → fallback                             | Method = "FixedZone" di log          |
| TC-16     | Sinyal valid → log tersimpan                   | Baris baru di signal_history.csv     |
| TC-17     | Sinyal valid → Telegram terkirim               | Pesan diterima dengan format lengkap |

### 10.2 — Pengujian Performa Sinyal (Live Forward Testing)

**Protokol:**

- Periode: minimal 2 minggu (10 hari trading)
- Instrumen: XAU/USD
- Jam: London + NY session (session filter aktif)
- Outcome dicatat manual via `outcome_updater.py` setiap hari

**Cara menentukan outcome:**

- `WIN_TP1` — harga menyentuh TP1 sebelum SL
- `WIN_TP2` — harga menyentuh TP2 sebelum SL
- `WIN_TP3` — harga menyentuh TP3 sebelum SL
- `LOSS` — harga menyentuh SL sebelum TP manapun
- `CANCELLED` — sinyal dibatalkan manual (misal: keluar sebelum TP/SL karena news)

**Metrik evaluasi:**

| Metrik            | Rumus                                           | Target Referensi        |
| ----------------- | ----------------------------------------------- | ----------------------- |
| Win Rate (TP1)    | (WIN_TP1 + WIN_TP2 + WIN_TP3) / decided × 100% | ≥ 50%                  |
| Win Rate (TP2+)   | (WIN_TP2 + WIN_TP3) / decided × 100%           | ≥ 30%                  |
| Avg RR realized   | Rata-rata RR sinyal yang WIN                    | ≥ 1.5                  |
| Total sinyal      | Jumlah selama periode                           | Dokumentasikan semua    |
| Win rate per TF   | Breakdown per M5/M15/H1/H4/D1                   | Analisis komparatif     |
| Win rate per arah | BUY vs SELL                                     | Analisis komparatif     |
| Win rate per sesi | London vs NY vs Overlap                         | Validasi session filter |

**Catatan akademik:** Target win rate bukan syarat kelulusan. Yang dinilai adalah **konsistensi, transparansi, dan objektivitas** sistem dalam menghasilkan sinyal berbasis aturan yang terukur dan dapat dijelaskan.

### 10.3 — Pengujian Konsistensi

- Input data sama → output sinyal harus identik (sistem deterministic)
- Tidak ada sinyal duplikat sebelum cooldown habis
- Semua reject harus punya `reject_reason` yang tercatat di log

---

## 11. Checklist Kelengkapan Skripsi

### BAB I — Pendahuluan ✅

- [X] Latar belakang (XAU/USD, gap sinyal, DSS)
- [X] Rumusan masalah (3 poin)
- [X] Batasan masalah
- [X] Tujuan penelitian
- [X] Manfaat penelitian (akademis, praktis, teknologi)

### BAB II — Tinjauan Pustaka ✅

- [X] Pasar Forex & XAU/USD
- [X] Candlestick / Price Action
- [X] RSI
- [X] EMA / MA
- [X] MACD
- [X] Risk-Reward Ratio
- [X] Fibonacci Retracement
- [X] Support-Resistance & Supply-Demand
- [X] Multi-Timeframe Analysis
- [X] DSS & Rule-Based Intelligent System
- [X] Python, TA-Lib, MT5 API, Telegram API
- [X] Penelitian terdahulu (5 paper)

### BAB III — Metodologi ✅

- [X] Model Waterfall
- [X] Objek penelitian
- [X] Analisis kebutuhan fungsional & non-fungsional
- [X] Flowchart perancangan sistem
- [X] Tabel aturan IF-THEN
- [ ] Diagram arsitektur sistem (perlu gambar/diagram)
- [ ] Penjelasan setiap modul sistem

### BAB IV — Implementasi & Evaluasi ⏳

- [ ] Screenshot kode tiap modul utama
- [ ] Screenshot output Telegram (minimal 3 sinyal BUY & SELL)
- [ ] Tabel data sinyal hasil pengujian (dari `signal_history.csv`)
- [ ] Statistik win rate & RR hasil pengujian
- [ ] Analisis per TF dan per arah
- [ ] Pembahasan kesesuaian sistem dengan aturan yang dirancang
- [ ] Pembahasan keterbatasan sistem

### Lampiran

- [ ] File `.env.example`
- [ ] Tabel data sinyal lengkap (export dari CSV)
- [ ] Kode sumber (atau repository link)

---

## 12. Struktur File Project

```
BOT SKRIPSI 2/
├── src/
│   ├── config/
│   │   ├── settings.py          ✅ Load env vars  [perlu update: parameter baru]
│   │   └── timeframes.py        ✅ MT5 TF mapping
│   ├── mt5/
│   │   ├── connector.py         ✅ MT5 login
│   │   └── market_data.py       ✅ fetch OHLC
│   ├── features/
│   │   ├── indicators.py        ✅ RSI, EMA, MACD, ATR, Divergence
│   │   ├── patterns.py          ✅ 27 candlestick patterns
│   │   ├── fibonacci.py         ✅ Levels + fib_confluence_score()
│   │   ├── zones_snr.py         ✅ Swing points + snr_confluence_score()
│   │   ├── zones_snd.py         ✅ Base zone + snd_confluence_score()
│   │   └── session.py           ❌ BARU [F-03] — session filter
│   ├── engine/
│   │   ├── signal_engine.py     ✅ Entry point evaluasi
│   │   └── anytf_mta_engine.py  ⚠️ UTAMA — perlu F-01, F-02, F-03, F-04, F-07
│   ├── models/
│   │   └── signal.py            ⚠️ perlu tambah field: trigger_score, confluence_score
│   ├── risk/
│   │   ├── sl_tp.py             ✅ Fixed & Dynamic ATR SL/TP (keduanya sudah ada)
│   │   └── rr.py                ✅ Hitung RR
│   ├── notify/
│   │   ├── telegram.py          ✅ send_message()
│   │   └── templates.py         ⚠️ perlu F-06 (format lebih lengkap)
│   ├── strategy/
│   │   └── timeframe_hierarchy.py  ✅ higher_timeframes()
│   ├── infra/
│   │   ├── logger.py            ✅ Setup loguru
│   │   ├── scheduler.py         ✅ CandleCloseWatcher
│   │   ├── signal_logger.py     ✅ SignalLogger CSV+JSON  [belum dipanggil]
│   │   └── outcome_updater.py   ✅ CLI update WIN/LOSS    [siap pakai]
│   └── main.py                  ⚠️ perlu F-05 (aktifkan SignalLogger)
├── logs/
│   ├── app.log                  ✅ Log aplikasi
│   ├── signal_history.csv       ⏳ Terisi setelah F-05 aktif
│   └── signal_history.json      ⏳ Terisi setelah F-05 aktif
├── .env                         ✅ (tidak di-commit, berisi credentials)
├── .env.example                 ❌ BARU [F-08]
├── README.md                    ❌ BARU [F-08]
└── ROADMAP_PRD.md               ✅ Dokumen ini (versi 2.0)
```

---

## Legenda

| Simbol | Arti                                  |
| ------ | ------------------------------------- |
| ✅     | Sudah berjalan, tidak perlu diubah    |
| ⚠️   | Ada tapi perlu modifikasi             |
| ❌     | Belum ada, perlu dibuat               |
| ⏳     | Akan aktif setelah fitur lain selesai |

---

*Dokumen ini adalah living document — diperbarui setiap ada perubahan signifikan pada sistem.*
*Versi 2.0 — Revisi berdasarkan perspektif trader profesional + alignment penuh dengan proposal skripsi.*
