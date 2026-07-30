# 🤖 Facebook Marketplace Alert Bot

Bot Python yang berjalan 24/7 di VPS untuk memonitor Facebook Marketplace dan mengirim notifikasi ke Telegram ketika ada listing baru yang sesuai kriteria pencarian Anda.

## ✨ Fitur

- 🔍 **Multi-keyword monitoring** — Monitor banyak kata kunci sekaligus
- 💰 **Filter harga** — Set rentang harga min-max untuk setiap keyword
- 🏷️ **Filter kondisi** — Filter barang baru/bekas
- 📍 **Filter lokasi** — Pencarian berdasarkan kota tertentu
- 📱 **Notifikasi Telegram** — Terima alert lengkap dengan foto, harga, link
- 🎮 **Kontrol via Telegram** — Start/stop/status langsung dari chat Telegram
- 🗄️ **Anti-duplikat** — Database SQLite memastikan tidak ada notifikasi ganda
- 📝 **Logging** — Log ke file dengan rotating handler
- 🔄 **Auto-recovery** — Restart otomatis jika terjadi error

## 📋 Prasyarat

### VPS
- **OS**: Ubuntu 20.04+ (atau Linux lain)
- **RAM**: Minimal 1GB (direkomendasikan 2GB)
- **Python**: 3.9+

### Software
- Google Chrome atau Chromium
- ChromeDriver (otomatis diinstall oleh `webdriver-manager`)

## 🚀 Instalasi

### 1. Install Google Chrome (di VPS Ubuntu)

```bash
# Download dan install Chrome
wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | sudo apt-key add -
echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" | sudo tee /etc/apt/sources.list.d/google-chrome.list
sudo apt update
sudo apt install -y google-chrome-stable

# Verifikasi instalasi
google-chrome --version
```

### 2. Install Dependencies Python

```bash
# Clone atau copy project ke VPS
cd fb-marketplace-alert

# Buat virtual environment (opsional tapi direkomendasikan)
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Buat Telegram Bot

1. Buka Telegram, cari **@BotFather**
2. Kirim `/newbot`
3. Ikuti instruksi, beri nama dan username bot
4. Salin **Bot Token** yang diberikan

### 4. Dapatkan Chat ID

1. Buka Telegram, cari **@userinfobot**
2. Kirim `/start`
3. Bot akan membalas dengan **Chat ID** Anda

### 5. Konfigurasi

```bash
# Copy template environment
cp .env.example .env

# Edit .env dengan kredensial Anda
nano .env
```

Isi file `.env`:
```
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ
TELEGRAM_CHAT_ID=123456789
FACEBOOK_EMAIL=email_fb_anda@gmail.com
FACEBOOK_PASSWORD=password_fb_anda
```

> ⚠️ **PENTING**: Gunakan akun Facebook **secondary/khusus**, JANGAN akun utama! Ada risiko akun dibatasi oleh Facebook.

### 6. Konfigurasi Kriteria Pencarian

Edit `config.json`:

```json
{
  "check_interval_minutes": 5,
  "facebook_cookies_file": "cookies.json",
  "max_listings_per_search": 30,
  "auto_cleanup_days": 30,
  "location": {
    "city": "Jakarta",
    "radius_km": 40
  },
  "searches": [
    {
      "keyword": "iPhone 13",
      "min_price": 3000000,
      "max_price": 7000000,
      "condition": "used",
      "enabled": true
    },
    {
      "keyword": "PS5",
      "min_price": 4000000,
      "max_price": 8000000,
      "condition": "all",
      "enabled": true
    }
  ]
}
```

**Penjelasan field:**
| Field | Deskripsi | Nilai |
|-------|-----------|-------|
| `check_interval_minutes` | Interval pengecekan (menit) | Angka (min: 1) |
| `keyword` | Kata kunci pencarian | String |
| `min_price` | Harga minimum (Rupiah) | Angka |
| `max_price` | Harga maksimum (Rupiah) | Angka |
| `condition` | Kondisi barang | `"new"`, `"used"`, `"all"` |
| `enabled` | Aktifkan/nonaktifkan kriteria | `true`/`false` |
| `city` | Kota pencarian | Nama kota |
| `auto_cleanup_days` | Hapus listing lama setelah X hari | Angka |

## 🏃 Menjalankan Bot

### Manual

```bash
# Aktifkan venv (jika pakai)
source venv/bin/activate

# Jalankan bot
python main.py
```

### Menggunakan systemd (Supaya auto-start)

1. Buat service file:

```bash
sudo nano /etc/systemd/system/fb-marketplace-bot.service
```

2. Isi dengan:

```ini
[Unit]
Description=Facebook Marketplace Alert Bot
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/path/to/fb-marketplace-alert
ExecStart=/path/to/fb-marketplace-alert/venv/bin/python main.py
Restart=always
RestartSec=30
Environment=DISPLAY=:99

[Install]
WantedBy=multi-user.target
```

3. Aktifkan service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable fb-marketplace-bot
sudo systemctl start fb-marketplace-bot

# Cek status
sudo systemctl status fb-marketplace-bot

# Lihat log
sudo journalctl -u fb-marketplace-bot -f
```

### Menggunakan Screen (Alternatif sederhana)

```bash
# Buat screen session
screen -S fbbot

# Jalankan bot
python main.py

# Detach: tekan Ctrl+A, lalu D
# Re-attach: screen -r fbbot
```

## 📱 Command Telegram

Setelah bot berjalan, Anda bisa mengontrol bot melalui Telegram:

| Command | Fungsi |
|---------|--------|
| `/start` | Mulai monitoring |
| `/stop` | Hentikan monitoring |
| `/status` | Lihat status bot (uptime, statistik) |
| `/list` | Lihat semua kriteria pencarian |
| `/add <keyword> <min> <max> <condition>` | Tambah kriteria baru |
| `/remove <nomor>` | Hapus kriteria berdasarkan nomor |
| `/interval <menit>` | Ubah interval pengecekan |
| `/help` | Tampilkan bantuan |

**Contoh:**
```
/add RTX 4070 8000000 15000000 used
/remove 3
/interval 10
```

## 📂 Struktur File

```
fb-marketplace-alert/
├── config.json          # Konfigurasi pencarian
├── .env                 # Kredensial (JANGAN commit!)
├── .env.example         # Template kredensial
├── main.py              # Entry point utama
├── scraper.py           # Facebook Marketplace scraper
├── database.py          # SQLite database handler
├── telegram_bot.py      # Telegram bot (notifikasi + kontrol)
├── models.py            # Data classes
├── logger_setup.py      # Konfigurasi logging
├── requirements.txt     # Python dependencies
├── README.md            # Dokumentasi ini
├── marketplace.db       # Database (auto-generated)
├── cookies.json         # Cookies Facebook (auto-generated)
├── logs/                # File log (auto-generated)
│   └── bot.log
└── debug/               # Screenshot debugging (auto-generated)
```

## 🔧 Troubleshooting

### Bot tidak bisa login ke Facebook
- Pastikan email dan password benar di `.env`
- Cek apakah ada checkpoint/verifikasi 2FA di akun Facebook
- Coba login manual di browser biasa dulu untuk clear checkpoint
- Lihat screenshot di folder `debug/`

### Chrome crash di VPS
```bash
# Install Xvfb (virtual display) jika diperlukan
sudo apt install -y xvfb
Xvfb :99 -screen 0 1920x1080x24 &
export DISPLAY=:99
```

### Bot tidak mengirim notifikasi
- Pastikan Bot Token dan Chat ID benar
- Pastikan Anda sudah kirim `/start` ke bot di Telegram
- Cek file log di `logs/bot.log`

### Facebook memblokir scraping
- Tambah interval pengecekan (misal 15-30 menit)
- Gunakan akun Facebook yang berbeda
- Pertimbangkan menggunakan VPN/proxy

## ⚠️ Disclaimer

- Bot ini menggunakan web scraping yang mungkin melanggar Terms of Service Facebook
- Gunakan dengan risiko Anda sendiri
- Disarankan menggunakan akun Facebook secondary
- Jangan set interval terlalu pendek untuk menghindari rate limiting
