# Pacer Group Tracker

Aplikasi web internal untuk memantau aktivitas harian (langkah, jarak, kalori, waktu aktif) anggota grup **Pacer**, tersinkronisasi otomatis ke **Google Sheets** sebagai sumber data terpusat. Dibangun dengan Flask (Python) dan dirancang untuk berjalan di hosting gratis seperti [Render.com](https://render.com).

> Versi ini adalah versi **deploy/production**, terpisah dari environment pengembangan lokal, dengan tambahan lapisan keamanan (login gate, session timeout) dan penyimpanan data yang sepenuhnya stateless (tidak bergantung pada disk lokal).

## Fitur Utama

- **Autentikasi OAuth 2.0 dengan Pacer API** — anggota grup menghubungkan akun Pacer masing-masing lewat alur *connect* satu klik.
- **Sinkronisasi data otomatis & manual** — data aktivitas harian diambil dari Pacer API dan di-*upsert* (insert/update berdasarkan anggota + tanggal) ke Google Sheets, baik lewat jadwal otomatis (APScheduler), tombol manual di dashboard, maupun pemicu cron eksternal.
- **Penyimpanan sepenuhnya di Google Sheets** — tidak ada data yang disimpan di disk server, sehingga aman terhadap redeploy/restart pada hosting yang disk-nya tidak permanen.
- **Halaman login berbasis session** — seluruh halaman dan endpoint sync dilindungi autentikasi username/password, dengan auto-logout saat idle.
- **Dashboard riwayat sync** — menampilkan waktu sync terakhir, metode yang digunakan, serta hasilnya.

## Dokumentasi Lengkap

Untuk arsitektur, struktur proyek, instalasi, konfigurasi environment variables, deploy ke Render, sinkronisasi via cron eksternal, keamanan, keterbatasan free tier, dan troubleshooting — lihat **[SETUP.md](SETUP.md)**.
