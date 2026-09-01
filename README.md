# Pacer Group Tracker

Aplikasi web internal untuk memantau aktivitas harian (langkah, jarak, kalori, waktu aktif) anggota grup **Pacer**, tersinkronisasi otomatis ke **PostgreSQL** sebagai sumber data terpusat. Dibangun dengan Flask (Python) dan dirancang untuk berjalan di hosting gratis seperti [Render.com](https://render.com).

> Versi ini adalah versi **deploy/production**, terpisah dari environment pengembangan lokal, dengan tambahan lapisan keamanan (login gate, session timeout).

## Fitur Utama

- **Autentikasi OAuth 2.0 dengan Pacer API** — anggota grup menghubungkan akun Pacer masing-masing lewat alur *connect* satu klik.
- **Sinkronisasi data otomatis & manual** — data aktivitas harian diambil dari Pacer API dan di-*upsert* (insert/update berdasarkan anggota + tanggal) ke PostgreSQL, baik lewat jadwal otomatis (APScheduler), tombol manual di dashboard, maupun pemicu cron eksternal. Histori tersimpan permanen tanpa batas.
- **Tahan terhadap kegagalan per-anggota** — satu anggota dengan token bermasalah tidak menggagalkan sync anggota lain; daftarnya ditampilkan di dashboard.
- **Halaman login berbasis session** — seluruh halaman dan endpoint sync dilindungi autentikasi username/password, dengan auto-logout saat idle.
- **Dashboard riwayat sync** — menampilkan waktu sync terakhir, metode yang digunakan, serta hasilnya.

## Dokumentasi Lengkap

Untuk arsitektur, struktur proyek, instalasi, konfigurasi environment variables, migrasi dari Google Sheets, deploy ke Render, sinkronisasi via cron eksternal, keamanan, dan troubleshooting — lihat **[SETUP.md](SETUP.md)**.
