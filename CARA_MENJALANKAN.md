# Cara Menjalankan Bot Trading DSS Forex

**Panduan lengkap untuk running bot di Windows + MetaTrader 5**

---

## Prasyarat yang Harus Sudah Ada

✅ Windows 10/11
✅ Python 3.10+ terinstal
✅ MetaTrader 5 terinstal di `C:\Program Files\MetaTrader 5\terminal64.exe`
✅ Akun MT5 (demo/real) yang sudah login di MetaTrader 5
✅ Bot Telegram sudah dibuat via [@BotFather](https://t.me/BotFather)
✅ Sudah tahu Chat ID Telegram Anda (via [@userinfobot](https://t.me/userinfobot))

---

## Langkah 1 — Buka Folder Project di Terminal

**Option A — Command Prompt (CMD):**

```cmd
cd "C:\Users\YourName\...\BOT SKRIPSI 2"
```

**Option B — PowerShell:**

```powershell
cd "C:\Users\YourName\...\BOT SKRIPSI 2"
```

**Option C — Terminal VSCode:**

- Buka folder `BOT SKRIPSI 2` di VSCode
- Tekan ``Ctrl + ` `` untuk buka terminal

---

## Langkah 2 — Aktifkan Virtual Environment

Bot sudah punya folder `venv` dengan dependencies lengkap.

**Di Command Prompt:**

```cmd
venv\Scripts\activate
```

**Di PowerShell:**

```powershell
venv\Scripts\Activate.ps1
```

**Jika error "Execution Policy"** di PowerShell, jalankan dulu:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**Tanda berhasil:** Prompt berubah jadi `(venv) C:\...\BOT SKRIPSI 2>`

---

## Langkah 3 — Cek File `.env` Sudah Benar

File `.env` sudah ada dan sudah diisi dengan kredensial Anda:

```env
MT5_LOGIN=10011808810
MT5_PASSWORD="I@7gIaGt"
MT5_SERVER="MetaQuotes-Demo"

TELEGRAM_BOT_TOKEN="7273461631:AAEnEeu8WwiXcaF3PKJHYDDE93vI3OcusLI"
TELEGRAM_CHAT_ID="-1003525075700"

SYMBOLS=XAUUSD
TIMEFRAMES=M5,M15,H1,H4,D1
MIN_TRIGGER_SCORE=4
MIN_CONFLUENCE_SCORE=2
MIN_RR=1.5
SESSION_FILTER=true
```

**✅ Kredensial sudah benar** — jangan ubah apapun kecuali Anda mau ganti broker/bot.

**⚠️ Jika ingin ubah threshold:**

- `MIN_TRIGGER_SCORE=4` — turunkan ke 3 kalau mau lebih banyak sinyal (tapi kualitas turun)
- `MIN_CONFLUENCE_SCORE=2` — turunkan ke 1 kalau mau lebih sering sinyal
- `MIN_RR=1.5` — ini sudah oke, jangan turunkan di bawah 1.2
- `SESSION_FILTER=true` — set `false` jika mau sinyal 24 jam (tidak disarankan)

---

## Langkah 4 — Pastikan MetaTrader 5 Sudah Login

**Buka MetaTrader 5:**

- Pastikan akun `10011808810` di server `MetaQuotes-Demo` sudah login (lihat di kiri atas MT5)
- Pastikan chart XAUUSD ada dan data streaming (candle bergerak)

**Jika MT5 belum login:**

1. File → Login to Trade Account
2. Masukkan login `10011808810`, password `I@7gIaGt`, server `MetaQuotes-Demo`

**⚠️ MT5 harus tetap buka** selama bot berjalan — bot mengambil data dari MT5 yang sedang running.

---

## Langkah 5 — Jalankan Bot

**Di terminal (dengan venv sudah aktif):**

```cmd
python -m src.main
```

**Output yang normal:**

```
2026-07-20 13:55:00.123 | INFO  | LOGGER OK
2026-07-20 13:55:00.456 | INFO  | BOT START | symbols=['XAUUSD'] TFs=['M5', 'M15', 'H1', 'H4', 'D1']
2026-07-20 13:55:00.789 | INFO  | PARAMS | RR>=1.5 trigger>=4/6 conf>=2 cooldown=3bar session_filter=True
2026-07-20 13:55:01.234 | INFO  | SignalLogger aktif → logs/signal_history.csv
2026-07-20 13:55:02.567 | INFO  | MT5 | login=10011808810 server=MetaQuotes-Demo
```

**Anda juga akan terima notifikasi di Telegram:**

```
🚀 BOT TRADING ONLINE

Account : 10011808810
Server  : MetaQuotes-Demo
Symbols : XAUUSD
TFs     : M5, M15, H1, H4, D1

RR≥1.5 | Trigger≥4/6 | Conf≥2 | Cooldown=3bar | Session=ON
```

**✅ Kalau sudah sampai sini, bot sudah berjalan!**

---

## Langkah 6 — Bot Sedang Berjalan — Apa yang Terjadi?

### Setiap 5 detik:

- Bot cek apakah ada candle yang baru saja close di M5/M15/H1/H4/D1
- Kalau ada candle close → ambil data OHLC dari MT5 → jalankan analisis 5 gate

### Log yang muncul:

```
13:55:05 | INFO  | [CLOSE] XAUUSD M5 | 2026-07-20 13:50:00
13:55:06 | WARNING | [NO SIGNAL] XAUUSD M5 | OUT_OF_SESSION(Asian)
```

```
14:00:05 | INFO  | [CLOSE] XAUUSD H1 | 2026-07-20 14:00:00
14:00:08 | SUCCESS | [SIGNAL] XAUUSD H1 BUY RR=1.85 T=5/6 C=5 ID=XAUUSD_H1_20260720_140000
```

### Kalau sinyal keluar:

- Log di terminal tampil `[SIGNAL] ...`
- **Pesan masuk ke Telegram Anda** dengan format lengkap
- Sinyal tersimpan ke `logs/signal_history.csv`

---

## Langkah 7 — Cara Menghentikan Bot

**Tekan `Ctrl + C` di terminal.**

Output:

```
2026-07-20 14:30:15 | INFO  | Bot dihentikan.
2026-07-20 14:30:15 | INFO  | MT5 shutdown.
```

**MT5 tetap berjalan** — hanya bot Python yang berhenti.

---

## Langkah 8 — Update Hasil Sinyal (WIN/LOSS)

Setelah sinyal keluar dan Anda trading, catat hasilnya:

```cmd
python -m src.infra.outcome_updater
```

**Menu interaktif muncul:**

```
════════════════════════════════════
  BOT TRADING — OUTCOME UPDATER
════════════════════════════════════

Menu:
  1. Lihat sinyal PENDING
  2. Update hasil sinyal (WIN/LOSS)
  3. Lihat statistik win rate
  4. Keluar

Pilih (1-4):
```

**Contoh workflow:**

1. Pilih `1` → lihat sinyal pending
2. Copy ID sinyal (misal `XAUUSD_H1_20260720_140000`)
3. Pilih `2` → paste ID → pilih outcome (`WIN_TP1` / `WIN_TP2` / `LOSS` / dll)
4. Pilih `3` → lihat win rate update

---

## Langkah 9 — Monitoring & Log

### File log yang penting:

| File                         | Isi                                           | Kegunaan                            |
| ---------------------------- | --------------------------------------------- | ----------------------------------- |
| `logs/app.log`             | Log runtime bot (candle close, sinyal, error) | Debugging kalau ada masalah         |
| `logs/signal_history.csv`  | Semua sinyal dalam format tabel               | Bisa dibuka di Excel untuk analisis |
| `logs/signal_history.json` | Semua sinyal dalam format JSON                | Untuk processing programatik        |

### Cara buka CSV di Excel:

1. Buka Excel
2. File → Open → pilih `logs\signal_history.csv`
3. Kolom: `signal_id`, `timestamp`, `symbol`, `direction`, `entry`, `sl`, `tp1`, `tp2`, `tp3`, `rr`, `confluence_score`, `outcome`, dll

---

## Troubleshooting

### ❌ Error: "MT5 initialize failed"

**Penyebab:** Path MT5 salah atau MT5 tidak terinstal.

**Solusi:**

1. Cek MT5 terinstal di `C:\Program Files\MetaTrader 5\terminal64.exe`
2. Kalau path berbeda, edit `src/mt5/connector.py` baris 4:
   ```python
   TERMINAL_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"
   ```

---

### ❌ Error: "MT5 login failed"

**Penyebab:** Login/password/server salah, atau akun expired.

**Solusi:**

1. Buka MT5 manual → coba login dengan kredensial yang sama
2. Kalau berhasil login manual, coba jalankan bot lagi
3. Kalau MT5 minta ganti password, update `.env` dengan password baru

---

### ❌ Error: "No module named 'MetaTrader5'"

**Penyebab:** Virtual environment tidak aktif atau dependencies tidak terinstal.

**Solusi:**

```cmd
venv\Scripts\activate
pip install MetaTrader5 pandas numpy ta-lib python-dotenv loguru pydantic requests pytz
```

---

### ❌ Error: "No module named 'talib'"

**Penyebab:** TA-Lib gagal install via pip (butuh compiler).

**Solusi:**

1. Download wheel dari: https://github.com/cgohlke/talib-build/releases
2. Pilih file sesuai Python version Anda (misal `TA_Lib‑0.4.28‑cp310‑cp310‑win_amd64.whl` untuk Python 3.10 64-bit)
3. Install:
   ```cmd
   pip install TA_Lib-0.4.28-cp310-cp310-win_amd64.whl
   ```

---

### ❌ Bot tidak kirim sinyal sama sekali

**Penyebab:** Threshold terlalu ketat, atau sedang di luar jam session aktif.

**Cek di `logs/app.log` alasan reject:**

```
[NO SIGNAL] XAUUSD M5 | TRIGGER_FAIL score=3/4
[NO SIGNAL] XAUUSD H1 | CONFLUENCE_FAIL conf=1/2
[NO SIGNAL] XAUUSD M15 | OUT_OF_SESSION(Asian)
```

**Solusi sementara untuk testing:**
Edit `.env`:

```env
MIN_TRIGGER_SCORE=3        # turunkan dari 4
MIN_CONFLUENCE_SCORE=1     # turunkan dari 2
SESSION_FILTER=false       # nonaktifkan filter jam
```

⚠️ **Hati-hati:** Ini akan membuat sinyal lebih banyak tapi kualitas turun. Untuk skripsi testing boleh, untuk trading sungguhan kembalikan ke default.

---

### ❌ Telegram tidak terima pesan

**Penyebab:** Token atau Chat ID salah.

**Test manual:**

```cmd
python -c "from src.notify.telegram import send_message; send_message('7273461631:AAEnEeu8WwiXcaF3PKJHYDDE93vI3OcusLI', '-1003525075700', 'Test dari bot')"
```

Kalau pesan masuk → berarti kredensial benar, masalah di tempat lain.
Kalau error → cek token/chat ID di `.env`.

---

## Tips Running untuk Skripsi

### Untuk pengumpulan data evaluasi (BAB IV):

1. Jalankan bot **minimal 2 minggu** (10 hari trading)
2. **Jangan ubah parameter** di tengah-tengah testing
3. **Update outcome** setiap hari via `outcome_updater.py`
4. **Screenshot** setiap sinyal yang masuk Telegram
5. **Export** `signal_history.csv` ke Excel untuk tabel di lampiran skripsi

### Untuk demo sidang:

1. Buka terminal + MT5 side-by-side di layar
2. Jalankan bot
3. Tunjukkan log real-time saat candle close
4. Tunjukkan Telegram saat sinyal masuk
5. Tunjukkan `outcome_updater.py` untuk update hasil

---

## Perintah Cepat (Cheat Sheet)

```cmd
# Aktifkan venv
venv\Scripts\activate

# Jalankan bot
python -m src.main

# Stop bot
Ctrl + C

# Update outcome sinyal
python -m src.infra.outcome_updater

# Lihat log
type logs\app.log

# Buka CSV di Excel
start logs\signal_history.csv
```

---

Selamat mencoba! Kalau ada error, cek di `logs/app.log` atau tanya saya.
