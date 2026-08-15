# Pacer Group Tracker (versi deploy - Render)

Versi ini dipisah dari project lokal (`../pacer-group-tracker`) supaya bisa di-deploy ke internet:

- **Halaman login** di depan seluruh halaman (username/password, session-based) — supaya tidak sembarang orang bisa lihat daftar anggota atau trigger sync.
- **Tidak ada penyimpanan file lokal** — daftar anggota (`Members`) dan data aktivitas (`Raw_Pacer`) dua-duanya disimpan di Google Sheets, karena disk di hosting gratis biasanya tidak permanen (hilang tiap redeploy/restart).
- Struktur & logic OAuth Pacer sama persis dengan project lokal (termasuk fix signature `pacer_oauth`).

## Sebelum deploy

1. **Test dulu secara lokal**:
   ```bash
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   python app.py
   ```
   Buka `http://localhost:5000`, login pakai `LOGIN_USERNAME` / `LOGIN_PASSWORD` di `.env` (default: `admin` / `kideco-healthy-2026` — **ganti ini**).

   > Catatan: matikan dulu server project lama (`../pacer-group-tracker`) karena sama-sama pakai port 5000.

2. Pastikan tab **"Members"** otomatis terbuat di Google Sheet yang sama saat pertama kali ada yang connect (kode akan bikin sendiri kalau belum ada).

## Deploy ke Render.com (gratis)

1. Push folder ini ke repository GitHub (baru, terpisah dari project lokal).
2. Di [Render Dashboard](https://dashboard.render.com/) → **New +** → **Web Service** → connect ke repo tadi.
3. Environment: **Python 3**. Build command: `pip install -r requirements.txt`. Start command otomatis terbaca dari `Procfile` (`gunicorn -w 1 app:app`) — **jangan ubah `-w 1`**, karena scheduler jadwal otomatis harus jalan di 1 proses saja (kalau lebih dari 1 worker, jadwalnya akan dobel-dobel).
4. Di tab **Environment**, tambahkan semua variabel dari `.env.example`:
   - `PACER_CLIENT_ID`, `PACER_CLIENT_SECRET`
   - `PACER_AUTH_BASE_URL`, `PACER_API_BASE_URL`
   - `PACER_REDIRECT_URI` → isi `https://<nama-app-kamu>.onrender.com/pacer/callback` (nama app baru diketahui setelah service pertama kali dibuat, bisa diedit lagi setelahnya)
   - `GOOGLE_SERVICE_ACCOUNT_JSON` → **paste seluruh isi file `credentials/google-service-account.json` sebagai satu baris** (bukan path file, karena file tidak ikut ter-deploy)
   - `GOOGLE_SHEET_ID`, `GOOGLE_SHEET_WORKSHEET`, `GOOGLE_MEMBERS_WORKSHEET`
   - `FLASK_SECRET_KEY` → random string panjang
   - `LOGIN_USERNAME`, `LOGIN_PASSWORD` → ganti dari default
5. Deploy. Setelah dapat URL publik (`https://xxx.onrender.com`), **update `PACER_REDIRECT_URI`** di environment variables Render ke URL final, lalu **daftarkan redirect URI yang sama persis** di developer console Pacer (developer.mypacer.com).
6. Bagikan link `https://xxx.onrender.com` + username/password login ke anggota grup supaya mereka bisa login dan klik "Hubungkan Anggota".

## Keterbatasan free tier yang perlu diketahui

- **App "tidur" setelah ~15 menit tanpa traffic**, lalu perlu ~10-30 detik untuk bangun saat ada request masuk. Ini mempengaruhi jadwal sync otomatis (08:00, 12:00, 15:00, 21:00, 23:55 WITA) — kalau app lagi tidur pas jam terjadwal, job di dalam proses tidak akan terpicu. Solusi paling sederhana: daftarkan URL `https://xxx.onrender.com/sync` (method POST, perlu login/cookie — lihat catatan di bawah) ke layanan cron gratis seperti [cron-job.org](https://cron-job.org) di 5 jam yang sama, supaya sync tetap terpicu + app tetap "dibangunkan".
  - Karena `/sync` sekarang di-gate login, cron eksternal tidak bisa langsung POST ke situ tanpa session. Kalau mau otomatis-lewat-cron yang benar-benar reliable, kabari saya — saya bisa tambahkan endpoint terpisah dengan token rahasia khusus untuk cron (tanpa perlu login), supaya tidak perlu buka akses `/sync` ke publik.
- Google Sheets API punya rate limit (100 request/100 detik per project) — untuk jumlah anggota kecil (puluhan) harusnya jauh di bawah limit itu.

## Struktur

- `app.py` — server Flask + login gate + scheduler
- `sync.py` — ambil data Pacer, upsert ke Google Sheets (tab `Raw_Pacer`)
- `services/pacer_client.py` — OAuth & pemanggilan API Pacer
- `services/member_store.py` — daftar anggota, disimpan di tab Google Sheets `Members`
- `services/sheets_client.py` — helper baca/tulis generik ke Google Sheets
- `services/sync_state.py` — status sync terakhir (in-memory, reset tiap restart — hanya untuk tampilan)
