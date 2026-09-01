# Setup & Deployment — Pacer Group Tracker

Panduan instalasi, konfigurasi, deploy, dan troubleshooting untuk **Pacer Group Tracker**. Untuk gambaran umum project, lihat [README.md](README.md).

## Daftar Isi

- [Arsitektur & Alur Kerja](#arsitektur--alur-kerja)
- [Struktur Proyek](#struktur-proyek)
- [Persiapan](#persiapan)
- [Konfigurasi Environment Variables](#konfigurasi-environment-variables)
- [Menjalankan Secara Lokal](#menjalankan-secara-lokal)
- [Migrasi dari Google Sheets](#migrasi-dari-google-sheets)
- [Deploy ke Render.com](#deploy-ke-rendercom)
- [Sinkronisasi Otomatis via Cron Eksternal](#sinkronisasi-otomatis-via-cron-eksternal)
- [Keamanan](#keamanan)
- [Troubleshooting](#troubleshooting)

---

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
             │      PostgreSQL        │
             │  • members             │
             │  • activities          │
             │  • sync_runs           │
             └───────────────────────┘
```

**Alur singkat:**

1. Admin login ke dashboard menggunakan username/password.
2. Anggota grup klik **"Hubungkan Anggota"** → diarahkan ke halaman otorisasi Pacer → setelah setuju, token OAuth (access & refresh token) disimpan ke tabel **`members`**.
3. Proses sinkronisasi (`sync.py`) mengambil ringkasan aktivitas harian tiap anggota dari Pacer API menggunakan token tersimpan, lalu meng-**upsert**-nya (per anggota + tanggal, `ON CONFLICT (user_id, activity_date)`) ke tabel **`activities`**. Histori tersimpan permanen tanpa batas — tidak ada lagi konsep sheet "live" vs "arsip" seperti di skema Google Sheets sebelumnya, karena Postgres tidak perlu clear+tulis-ulang seluruh tabel setiap sync.
4. Kegagalan per-anggota (mis. `refresh_token` yang sudah dicabut di sisi Pacer) di-*catch* dan dilewati — tidak menggagalkan sync anggota lain. Daftarnya ditampilkan di dashboard.
5. Sinkronisasi dapat dipicu oleh tiga sumber: **terjadwal** (APScheduler, 5x sehari), **manual** (tombol di dashboard), atau **cron eksternal** (endpoint khusus dengan token rahasia, untuk menjaga aplikasi tetap "bangun" di hosting free tier).

### Kenapa pindah dari Google Sheets ke Postgres

Google Sheets punya keterbatasan skala untuk peran ini: setiap sync harus *clear + tulis ulang seluruh sheet* (tidak ada operasi upsert baris tunggal via API), kena rate limit ("Read/Write requests per minute"), dan sel yang diformat ulang oleh Sheets UI bisa merusak data (mis. `expires_at` yang di-*reformat* jadi angka dengan pemisah ribuan). Postgres menghilangkan semua ini: upsert per baris (`ON CONFLICT DO UPDATE`), tidak ada batas praktis jumlah baris, tipe data (angka, tanggal) terjaga oleh skema, dan tidak perlu lagi logika tambahan (merge/prune/arsip) yang sebelumnya dibutuhkan hanya untuk menyiasati keterbatasan Sheets.

## Struktur Proyek

```
pacer-group-tracker/
├── app.py                     # Entry point Flask: routing, login gate, session timeout, scheduler
├── config.py                  # Pemuatan seluruh environment variables
├── sync.py                    # Logika inti sinkronisasi: fetch Pacer API → upsert Postgres
├── requirements.txt           # Dependensi Python
├── Procfile                   # Perintah start untuk Render (gunicorn, 1 worker)
├── .env.example                # Template environment variables
├── services/
│   ├── pacer_client.py        # OAuth flow & wrapper pemanggilan Pacer API
│   ├── db.py                  # Connection pool Postgres + init schema (members, activities, sync_runs)
│   ├── member_store.py        # CRUD data anggota & token, tabel "members"
│   ├── sheets_client.py       # Legacy — helper baca/tulis Google Sheets, dipakai HANYA oleh scripts/migrate_from_sheets.py
│   └── sync_state.py          # Status sync terakhir (in-memory, untuk tampilan dashboard)
├── scripts/
│   └── migrate_from_sheets.py # Migrasi satu kali: Google Sheets -> Postgres (read-only ke Sheets)
└── templates/
    ├── login.html              # Halaman login
    └── index.html              # Dashboard utama
```

## Persiapan

### Prasyarat

- Python 3.11+ (disarankan mengikuti versi yang dipakai di `render_env_values.txt` / `PYTHON_VERSION`)
- Database **PostgreSQL** (Render Postgres, Supabase, Neon, Railway, atau self-hosted — apa saja yang expose connection string `postgresql://...`)
- Kredensial **Pacer Developer** (`client_id` & `client_secret`) dari [developer.mypacer.com](https://developer.mypacer.com)
- *(Hanya kalau masih migrasi dari versi lama)* Akses ke Google Sheets lama — lihat [Migrasi dari Google Sheets](#migrasi-dari-google-sheets)

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
| `DATABASE_URL` | ✅ | Connection string PostgreSQL, format `postgresql://user:password@host:5432/dbname`. Tabel dibuat otomatis saat aplikasi start |
| `FLASK_SECRET_KEY` | ✅ | Random string panjang untuk signing session cookie |
| `LOGIN_USERNAME` / `LOGIN_PASSWORD` | ✅ | Kredensial login dashboard — **wajib diganti dari default** |
| `CRON_SYNC_TOKEN` | opsional | Token rahasia untuk endpoint `/sync/cron`. Kosongkan untuk menonaktifkan endpoint tersebut |
| `SESSION_TIMEOUT_MINUTES` | opsional | Lama idle sebelum auto-logout, default `60` menit |
| `GOOGLE_SERVICE_ACCOUNT_JSON` / `GOOGLE_SHEET_ID` / dst | legacy | HANYA dipakai `scripts/migrate_from_sheets.py`. Boleh dihapus dari environment setelah migrasi selesai |

## Menjalankan Secara Lokal

```bash
python app.py
```

Buka `http://localhost:5000`, lalu login menggunakan `LOGIN_USERNAME` / `LOGIN_PASSWORD` dari `.env`.

> **Catatan:** untuk testing lokal, pastikan `PACER_REDIRECT_URI` diarahkan ke `http://localhost:5000/pacer/callback` dan URI tersebut juga terdaftar di Pacer Developer Console, jika ingin menguji alur *connect* anggota secara end-to-end.

Tabel `members`, `activities`, dan `sync_runs` dibuat otomatis (`CREATE TABLE IF NOT EXISTS`) saat aplikasi start — tidak perlu migrasi manual untuk instalasi baru.

## Migrasi dari Google Sheets

Untuk instalasi yang sebelumnya memakai versi Google Sheets: jalankan script migrasi satu kali ini SEBELUM deploy versi Postgres ke production. Script ini **read-only** terhadap Google Sheets (tidak pernah menulis/menghapus apa pun di sana) dan **idempoten** (aman dijalankan berkali-kali kalau terputus di tengah jalan).

```bash
# Pastikan .env masih berisi kredensial Google Sheets LAMA (GOOGLE_SERVICE_ACCOUNT_*,
# GOOGLE_SHEET_ID, dst) + DATABASE_URL yang BARU
source venv/bin/activate
python -m scripts.migrate_from_sheets
```

Yang dilakukan script ini:

1. Membaca seluruh anggota dari sheet **Members** → upsert ke tabel `members` (token OAuth ikut terbawa, anggota yang sudah terhubung tidak perlu connect ulang).
2. Membaca **Raw_Pacer** + **Raw_Pacer_History**, digabung & dedup (kalau ada baris yang sama di keduanya, versi dari Raw_Pacer/live yang dipakai karena lebih baru), lalu upsert ke tabel `activities`.
3. Baris lama dari sebelum kolom "User ID" ditambahkan (tidak bisa dipetakan ke anggota dengan aman) dan baris dengan `user_id` yang sudah tidak ada di Members akan **dilewati dengan peringatan** — dicetak jelas di output, bukan hilang diam-diam.

Setelah migrasi, verifikasi jumlah anggota & baris aktivitas di output script sesuai ekspektasi, baru redeploy aplikasi dengan `DATABASE_URL` di-set sebagai penyimpanan utama. Data di Google Sheets tidak disentuh sama sekali — aman dijadikan cadangan sampai yakin migrasi berhasil.

## Deploy ke Render.com

1. Push repository ini ke GitHub.
2. Kalau belum ada: buat **Render Postgres** (New + → PostgreSQL) dan salin **Internal Database URL**-nya.
3. Di [Render Dashboard](https://dashboard.render.com/) → **New +** → **Web Service** → hubungkan ke repository.
4. Environment: **Python 3**. Build command: `pip install -r requirements.txt`. Start command otomatis terbaca dari `Procfile`:
   ```
   web: gunicorn -w 1 --timeout 120 app:app
   ```
   > **Penting:** jangan ubah `-w 1`. Scheduler sinkronisasi otomatis harus berjalan di satu proses saja — jika lebih dari satu worker, jadwal sync akan terpicu berulang kali (duplikasi).
5. Di tab **Environment**, tambahkan seluruh variabel dari `.env.example` (lihat tabel di atas), termasuk `DATABASE_URL` dari langkah 2.
6. Deploy. Setelah mendapat URL publik (`https://xxx.onrender.com`):
   - Update `PACER_REDIRECT_URI` di environment variables Render ke `https://xxx.onrender.com/pacer/callback`.
   - Daftarkan redirect URI yang sama persis di Pacer Developer Console.
7. Bagikan URL aplikasi beserta kredensial login ke anggota grup agar mereka bisa login dan menghubungkan akun Pacer masing-masing.

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
| `200` | Sukses, body: `{"ok": true, "updated_count": 12, "total_count": 340, "failed_members": [...]}` |
| `401` | Token tidak valid |
| `503` | `CRON_SYNC_TOKEN` belum diset di server (endpoint nonaktif secara default) |
| `500` | Sync gagal (mis. error koneksi ke Pacer API/database), body berisi pesan error |

## Keamanan

- **Login gate** — seluruh route (kecuali `/login` dan `/sync/cron`) memerlukan session aktif.
- **Session timeout otomatis** — session berakhir setelah tidak ada aktivitas selama `SESSION_TIMEOUT_MINUTES` (default 60 menit), dihitung secara *sliding* (timer di-reset setiap kali ada request, bukan dari waktu login pertama).
- **Token cron terpisah** — endpoint `/sync/cron` menggunakan mekanisme autentikasi terpisah (token rahasia, dibandingkan dengan `secrets.compare_digest` untuk mencegah *timing attack*), sehingga tidak perlu membuka akses `/sync` (yang butuh login) ke publik.
- **Perbandingan kredensial aman** — pengecekan username/password login menggunakan `secrets.compare_digest`.
- **Token OAuth anggota** disimpan di tabel `members` di database yang sama — pastikan `DATABASE_URL` hanya diberikan ke pihak yang berwenang (admin), sama seperti perlakuan kredensial sensitif lain.

## Troubleshooting

| Masalah | Kemungkinan Penyebab & Solusi |
|---|---|
| Redirect OAuth gagal / "invalid redirect_uri" | Pastikan `PACER_REDIRECT_URI` di environment variables sama persis dengan yang terdaftar di Pacer Developer Console |
| Aplikasi gagal start, error `DATABASE_URL belum diset` | Set environment variable `DATABASE_URL` — lihat [Konfigurasi Environment Variables](#konfigurasi-environment-variables) |
| Endpoint `/sync/cron` selalu 503 | `CRON_SYNC_TOKEN` belum diset di environment variables |
| Session terus logout meski baru dipakai | Periksa nilai `SESSION_TIMEOUT_MINUTES`, atau pastikan client (browser) mengizinkan cookie |
| Jadwal sync tidak jalan otomatis | Kemungkinan aplikasi sedang "tidur" (free tier) — gunakan cron eksternal sebagai pemicu tambahan |
| Anggota daftar Pacer via **Sign in with Apple + Hide My Email**, macet di halaman "Authorize" (khususnya Safari) | Ini terjadi di halaman `developer.mypacer.com`, di luar kendali aplikasi ini. Workaround: matikan "Prevent Cross-Site Tracking" di Safari untuk proses connect ini, coba browser lain, atau ubah ke share email asli lewat Settings → Apple ID → Sign-In & Security → Sign in with Apple. Jika berhasil connect, aplikasi ini sudah menangani `display_name` kosong dengan fallback ke `user_id` agar data anggota tidak tertukar. |
| Setelah migrasi, sebagian baris aktivitas lama tidak muncul | Cek output `scripts/migrate_from_sheets.py` — baris lama tanpa kolom "User ID" atau dengan `user_id` yang tidak ada di tabel `members` sengaja dilewati (dicetak sebagai peringatan) karena tidak bisa dipetakan ke anggota dengan aman |
