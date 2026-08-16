# Pacer Group Tracker

Aplikasi web internal untuk memantau aktivitas harian (langkah, jarak, kalori, waktu aktif) anggota grup **Pacer**, tersinkronisasi otomatis ke **Google Sheets** sebagai sumber data terpusat. Dibangun dengan Flask (Python) dan dirancang untuk berjalan di hosting gratis seperti [Render.com](https://render.com).

> Versi ini adalah versi **deploy/production**, terpisah dari environment pengembangan lokal, dengan tambahan lapisan keamanan (login gate, session timeout) dan penyimpanan data yang sepenuhnya stateless (tidak bergantung pada disk lokal).

---

## Daftar Isi

- [Fitur Utama](#fitur-utama)
- [Arsitektur & Alur Kerja](#arsitektur--alur-kerja)
- [Struktur Proyek](#struktur-proyek)
- [Persiapan](#persiapan)
- [Konfigurasi Environment Variables](#konfigurasi-environment-variables)
- [Menjalankan Secara Lokal](#menjalankan-secara-lokal)
- [Deploy ke Render.com](#deploy-ke-rendercom)
- [Sinkronisasi Otomatis via Cron Eksternal](#sinkronisasi-otomatis-via-cron-eksternal)
- [Keamanan](#keamanan)
- [Keterbatasan Free Tier](#keterbatasan-free-tier)
- [Troubleshooting](#troubleshooting)

---

## Fitur Utama

- **Autentikasi OAuth 2.0 dengan Pacer API** — anggota grup menghubungkan akun Pacer masing-masing lewat alur *connect* satu klik.
- **Sinkronisasi data otomatis & manual** — data aktivitas harian diambil dari Pacer API dan di-*upsert* (insert/update berdasarkan anggota + tanggal) ke Google Sheets, baik lewat jadwal otomatis (APScheduler), tombol manual di dashboard, maupun pemicu cron eksternal.
- **Penyimpanan sepenuhnya di Google Sheets** — tidak ada data yang disimpan di disk server, sehingga aman terhadap redeploy/restart pada hosting yang disk-nya tidak permanen.
- **Halaman login berbasis session** — seluruh halaman dan endpoint sync dilindungi autentikasi username/password.
- **Auto-logout karena idle** — session otomatis berakhir setelah periode tidak ada aktivitas (default 60 menit), mengurangi risiko akses tak sah dari sesi yang lupa di-*logout*.
- **Dashboard riwayat sync** — menampilkan waktu sync terakhir, metode yang digunakan (terjadwal, manual, atau cron eksternal), serta hasilnya (jumlah baris diperbarui/total, atau pesan error jika gagal).
- **Endpoint cron khusus dengan token rahasia** — memungkinkan trigger sync dari layanan cron eksternal tanpa membuka akses sync ke publik atau memerlukan session login.

## Arsitektur & Alur Kerja

```
┌─────────────┐      OAuth 2.0       ┌─────────────┐
│   Anggota    │ ───────────────────▶ │  Pacer API   │
│   Grup       │ ◀─────────────────── │              │
└─────────────┘   access/refresh     └─────────────┘
       │              token                 │
       │ login via dashboard                │ ambil data aktivitas
       ▼                                     ▼
┌───────────────────────────────────────────────────┐
│                Flask App (app.py)                  │
│  ┌──────────────┐  ┌───────────┐  ┌─────────────┐ │
│  │ Login gate   │  │ Scheduler │  │ /sync/cron  │ │
│  │ + session    │  │(APScheduler)│ │(token-based)│ │
│  │  timeout     │  └───────────┘  └─────────────┘ │
│  └──────────────┘                                  │
└───────────────────────────────────────────────────┘
                        │
                        ▼
             ┌───────────────────────┐
             │     Google Sheets      │
             │  • Raw_Pacer (data)    │
             │  • Members (token OAuth│
             │    anggota, terpisah)  │
             └───────────────────────┘
```

**Alur singkat:**

1. Admin login ke dashboard menggunakan username/password.
2. Anggota grup klik **"Hubungkan Anggota"** → diarahkan ke halaman otorisasi Pacer → setelah setuju, token OAuth (access & refresh token) disimpan ke Google Sheet **Members** (spreadsheet terpisah, privat).
3. Proses sinkronisasi (`sync.py`) mengambil ringkasan aktivitas harian tiap anggota dari Pacer API menggunakan token tersimpan, lalu menggabungkannya (upsert per anggota + tanggal) ke Google Sheet **Raw_Pacer**.
4. Sinkronisasi dapat dipicu oleh tiga sumber: **terjadwal** (APScheduler, 5x sehari), **manual** (tombol di dashboard), atau **cron eksternal** (endpoint khusus dengan token rahasia, untuk menjaga aplikasi tetap "bangun" di hosting free tier).

## Struktur Proyek

```
pacer-group-tracker/
├── app.py                     # Entry point Flask: routing, login gate, session timeout, scheduler
├── config.py                  # Pemuatan seluruh environment variables
├── sync.py                    # Logika inti sinkronisasi: fetch Pacer API → upsert Google Sheets
├── requirements.txt           # Dependensi Python
├── Procfile                   # Perintah start untuk Render (gunicorn, 1 worker)
├── .env.example                # Template environment variables
├── services/
│   ├── pacer_client.py        # OAuth flow & wrapper pemanggilan Pacer API
│   ├── member_store.py        # CRUD data anggota & token, disimpan di sheet "Members"
│   ├── sheets_client.py       # Helper generik baca/tulis Google Sheets (via gspread)
│   └── sync_state.py          # Status sync terakhir (in-memory, untuk tampilan dashboard)
└── templates/
    ├── login.html              # Halaman login
    └── index.html              # Dashboard utama
```

## Persiapan

### Prasyarat

- Python 3.11+ (disarankan mengikuti versi yang dipakai di `render_env_values.txt` / `PYTHON_VERSION`)
- Akun **Google Cloud** dengan Service Account yang punya akses ke Google Sheets API
- Kredensial **Pacer Developer** (`client_id` & `client_secret`) dari [developer.mypacer.com](https://developer.mypacer.com)
- Dua Google Spreadsheet terpisah:
  - Satu untuk data aktivitas (`Raw_Pacer`)
  - Satu untuk token anggota (`Members`) — **wajib dipisah** karena berisi data sensitif (refresh token OAuth)
- Kedua spreadsheet di atas sudah di-*share* ke email Service Account dengan akses **Editor**

### Instalasi Dependensi

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Konfigurasi Environment Variables

Salin `.env.example` menjadi `.env`, lalu isi seluruh variabel berikut:

| Variabel | Wajib | Keterangan |
|---|---|---|
| `PACER_CLIENT_ID` | ✅ | Client ID aplikasi Pacer |
| `PACER_CLIENT_SECRET` | ✅ | Client Secret aplikasi Pacer |
| `PACER_AUTH_BASE_URL` | ✅ | Default: `http://developer.mypacer.com` |
| `PACER_API_BASE_URL` | ✅ | Default: `http://openapi.mypacer.com` |
| `PACER_REDIRECT_URI` | ✅ | URL callback OAuth, harus sama persis dengan yang didaftarkan di Pacer Developer Console |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | * | Isi file JSON Service Account dalam satu baris (dipakai saat deploy) |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | * | Path ke file JSON Service Account (dipakai untuk dev lokal saja) |
| `GOOGLE_SHEET_ID` | ✅ | ID atau URL spreadsheet data aktivitas |
| `GOOGLE_SHEET_WORKSHEET` | ✅ | Nama tab, default `Raw_Pacer` |
| `GOOGLE_MEMBERS_SHEET_ID` | ✅ | ID atau URL spreadsheet token anggota (terpisah, privat) |
| `GOOGLE_MEMBERS_WORKSHEET` | ✅ | Nama tab, default `Members` |
| `FLASK_SECRET_KEY` | ✅ | Random string panjang untuk signing session cookie |
| `LOGIN_USERNAME` / `LOGIN_PASSWORD` | ✅ | Kredensial login dashboard — **wajib diganti dari default** |
| `CRON_SYNC_TOKEN` | opsional | Token rahasia untuk endpoint `/sync/cron`. Kosongkan untuk menonaktifkan endpoint tersebut |
| `SESSION_TIMEOUT_MINUTES` | opsional | Lama idle sebelum auto-logout, default `60` menit |

`*` Isi salah satu dari `GOOGLE_SERVICE_ACCOUNT_JSON` atau `GOOGLE_SERVICE_ACCOUNT_FILE`.

## Menjalankan Secara Lokal

```bash
python app.py
```

Buka `http://localhost:5000`, lalu login menggunakan `LOGIN_USERNAME` / `LOGIN_PASSWORD` dari `.env`.

> **Catatan:** untuk testing lokal, pastikan `PACER_REDIRECT_URI` diarahkan ke `http://localhost:5000/pacer/callback` dan URI tersebut juga terdaftar di Pacer Developer Console, jika ingin menguji alur *connect* anggota secara end-to-end.

Tab **Members** dan **Raw_Pacer** akan otomatis dibuat di spreadsheet terkait jika belum ada.

## Deploy ke Render.com

1. Push repository ini ke GitHub.
2. Di [Render Dashboard](https://dashboard.render.com/) → **New +** → **Web Service** → hubungkan ke repository.
3. Environment: **Python 3**. Build command: `pip install -r requirements.txt`. Start command otomatis terbaca dari `Procfile`:
   ```
   web: gunicorn -w 1 --timeout 120 app:app
   ```
   > **Penting:** jangan ubah `-w 1`. Scheduler sinkronisasi otomatis harus berjalan di satu proses saja — jika lebih dari satu worker, jadwal sync akan terpicu berulang kali (duplikasi).
4. Di tab **Environment**, tambahkan seluruh variabel dari `.env.example` (lihat tabel di atas).
5. Deploy. Setelah mendapat URL publik (`https://xxx.onrender.com`):
   - Update `PACER_REDIRECT_URI` di environment variables Render ke `https://xxx.onrender.com/pacer/callback`.
   - Daftarkan redirect URI yang sama persis di Pacer Developer Console.
6. Bagikan URL aplikasi beserta kredensial login ke anggota grup agar mereka bisa login dan menghubungkan akun Pacer masing-masing.

## Sinkronisasi Otomatis via Cron Eksternal

Karena hosting free tier "tidur" setelah idle, jadwal sync internal (APScheduler) bisa gagal terpicu bila aplikasi sedang tidak aktif. Untuk mengatasi ini, tersedia endpoint khusus `POST /sync/cron` yang bisa dipanggil tanpa login/session, cukup dengan token rahasia.

### Langkah setup

1. Set environment variable `CRON_SYNC_TOKEN` di Render (gunakan random string panjang, contoh generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"`).
2. Daftarkan job terjadwal di layanan cron gratis seperti [cron-job.org](https://cron-job.org), sesuai jadwal sync internal (contoh: `08:00, 12:00, 15:00, 21:00, 23:55` WITA), yang memanggil:

   ```
   POST https://xxx.onrender.com/sync/cron
   Header: X-Cron-Token: <isi CRON_SYNC_TOKEN>
   ```

   Alternatif jika layanan cron tidak mendukung header kustom, token dapat dikirim melalui query string:

   ```
   POST https://xxx.onrender.com/sync/cron?token=<isi CRON_SYNC_TOKEN>
   ```

### Response

| Status | Kondisi |
|---|---|
| `200` | Sukses, body: `{"ok": true, "updated_count": 12, "total_count": 340}` |
| `401` | Token tidak valid |
| `503` | `CRON_SYNC_TOKEN` belum diset di server (endpoint nonaktif secara default) |
| `500` | Sync gagal (mis. error koneksi ke Pacer API/Google Sheets), body berisi pesan error |

## Keamanan

- **Login gate** — seluruh route (kecuali `/login` dan `/sync/cron`) memerlukan session aktif.
- **Session timeout otomatis** — session berakhir setelah tidak ada aktivitas selama `SESSION_TIMEOUT_MINUTES` (default 60 menit), dihitung secara *sliding* (timer di-reset setiap kali ada request, bukan dari waktu login pertama).
- **Token cron terpisah** — endpoint `/sync/cron` menggunakan mekanisme autentikasi terpisah (token rahasia, dibandingkan dengan `secrets.compare_digest` untuk mencegah *timing attack*), sehingga tidak perlu membuka akses `/sync` (yang butuh login) ke publik.
- **Pemisahan spreadsheet data & token** — token OAuth anggota (sensitif) disimpan di spreadsheet terpisah dari data aktivitas, dengan akses dibatasi hanya untuk Service Account dan admin.
- **Perbandingan kredensial aman** — pengecekan username/password login menggunakan `secrets.compare_digest`.

## Keterbatasan Free Tier

- **Cold start** — aplikasi "tidur" setelah ±15 menit tanpa traffic, dan butuh 10–30 detik untuk bangun saat ada request masuk. Ini bisa membuat jadwal sync internal terlewat jika aplikasi kebetulan sedang tidur. Solusi: gunakan endpoint `/sync/cron` yang didaftarkan ke cron eksternal (lihat bagian di atas) agar sync tetap terpicu sekaligus membangunkan aplikasi.
- **Rate limit Google Sheets API** — 100 request per 100 detik per project. Untuk jumlah anggota dalam skala puluhan, penggunaan normal masih jauh di bawah limit tersebut.
- **`sync_state`** disimpan in-memory — riwayat sync terakhir akan ter-reset setiap kali aplikasi restart/redeploy (hanya untuk keperluan tampilan, bukan sumber data utama).

## Troubleshooting

| Masalah | Kemungkinan Penyebab & Solusi |
|---|---|
| Redirect OAuth gagal / "invalid redirect_uri" | Pastikan `PACER_REDIRECT_URI` di environment variables sama persis dengan yang terdaftar di Pacer Developer Console |
| Sync gagal dengan error terkait Google Sheets | Pastikan spreadsheet sudah di-*share* ke email Service Account dengan akses Editor |
| Endpoint `/sync/cron` selalu 503 | `CRON_SYNC_TOKEN` belum diset di environment variables |
| Session terus logout meski baru dipakai | Periksa nilai `SESSION_TIMEOUT_MINUTES`, atau pastikan client (browser) mengizinkan cookie |
| Jadwal sync tidak jalan otomatis | Kemungkinan aplikasi sedang "tidur" (free tier) — gunakan cron eksternal sebagai pemicu tambahan |
