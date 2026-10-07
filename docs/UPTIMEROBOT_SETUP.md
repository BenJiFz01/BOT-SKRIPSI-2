# Panduan Setup Monitoring UptimeRobot — Alert VPS Crash / Bot OfHline

> Berpasangan dengan komponen yang sudah diimplementasikan:
> - `src/infra/health_server.py` — endpoint `/health` di dalam bot.
> - `main.py` — alert `🔴 BOT OFFLINE` (manual stop / crash) + health aktif.
> - `start_bot.bat` — auto-restart saat crash.
>
> Konsep inti: **monitor berada di luar VPS**, sehingga tetap hidup meski VPS mati.

## Skema Kerja

```
Bot (di VPS)  --/health-->  UptimeRobot (di cloud, di luar VPS)
      │                            │
      │  selama bot on             │  tiap 5 menit ping
      ▼                            ▼
  respon OK                    "UP" (tanpa notif)
      │                            │
      │  VPS crash / bot off       │  /health tidak merespons
      ▼                            ▼
  (mati)                        "DOWN" → kirim notif otomatis ke Telegram
```
Dengan interval *down re-notify 5 menit*, notifikasi `OFFLINE` dikirim **berulang
tiap 5 menit selama sistem mati**, dan **1x notifikasi** `UP` saat sistem pulih.

## Langkah Setup (Sekali saja)

### 1. Pastikan endpoint /health aktif
Jalankan bot. Endpoint aktif secara otomatis di port **8100**:
```
http://<IP-VPS>:8100/health   →  200 OK
```
Uji manual di VPS:
```
curl http://localhost:8100/health
```
harus mengembalikan `OK`.

> Jika VPS memakai firewall (Windows Defender Firewall / cloud security group),
> **buka port TCP 8100** untuk akses dari IP UptimeRobot.

### 2. Daftar monitor baru di UptimeRobot
1. Login ke app.uptimerobot.com → **+ New monitor**.
2. **Monitor Type**: `HTTP(s)`.
3. **Friendly Name**: `Bot Trading XAUUSD`.
4. **URL (or IP)**: `http://<IP-VPS>:8100/health`.
5. **Monitoring Interval**: `5 minutes` (minimum gratis).
6. **Contact Alert**: pilih kontak Telegram (tambahkan bot token via kontak).
7. Simpan.

### 3. Atur agar "off → spam tiap 5 menit, on → 1x"
Setelah monitor dibuat, buka tab **Settings** monitor:
- Pada *Alert Contacts* → set **"Notify every [5] min"** pada kontak saat status `DOWN`
  (ini menghasilkan notifikasi berulang tiap 5 menit selama offline).
- Notifikasi saat status pulih (`UP`) bersifat **satu kali**, otomatis.
- (Opsional) **Recovery / UP message**: biarkan default 1x.

Hasil akhir sesuai permintaan:
| Status | Notifikasi |
|---|---|
| Sistem off / VPS crash | **Berulang tiap 5 menit** (`🔴 DOWN`) |
| Sistem on / pulih | **Satu kali** (`🟢 UP`) |

## Catatan Skripsi (Bab IV / Bab V)

1. **Batasan teknis:** Bot yang mati tidak dapat mengirim pesan sendiri. Maka alert
   untuk insiden *crash/VPS down* dikirim oleh **monitor eksternal (UptimeRobot)**,
   bukan oleh bot.
2. **Alert manual-stop:** bot tetap mengirim `🔴 BOT OFFLINE (manual)` dari dalam
   saat user menghentikannya secara normal (Ctrl+C / flag STOP), karena proses
   masih hidup ketika itu.
3. **Kombinasi lengkap:**
   - Bot crash tapi VPS hidup → restart otomatis oleh `start_bot.bat`; jika mati
     menetap, UptimeRobot segera mengirim `DOWN`.
   - VPS mati total → UptimeRobot mengirim `DOWN` (repeat 5 mnt).
   - Recovery → bot kirim `BOT TRADING ONLINE`, UptimeRobot kirim `UP` sekali.
