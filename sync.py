import datetime
import time

import config
from services import member_store, sheets_client
from services.pacer_client import PacerClient, refresh_access_token

HEADER = ["Nama", "Tanggal", "Langkah", "Jarak (m)", "Kalori", "Waktu Aktif (s)", "User ID"]
FETCH_DAYS_BACK = 2  # cukup untuk menangkap update hari ini + koreksi keterlambatan sync sebelumnya
LIVE_RETENTION_DAYS = config.RAW_PACER_LIVE_RETENTION_DAYS


def _ensure_fresh_token(user_id, member):
    if time.time() < member["expires_at"] - 60:
        return member["access_token"]

    data = refresh_access_token(member["refresh_token"])
    member_store.update_access_token(user_id, data["access_token"], data["expires_in"])
    return data["access_token"]


def _fetch_recent_rows(days_back):
    members = member_store.list_members()

    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=days_back - 1)

    rows = []
    failed = []
    for user_id, member in members.items():
        try:
            access_token = _ensure_fresh_token(user_id, member)
            client = PacerClient(access_token)

            daily = client.get_daily_activity_summary(
                user_id,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
            )
        except Exception as exc:
            # Satu anggota dengan refresh_token invalid (mis. akses dicabut di
            # sisi Pacer) tidak boleh menggagalkan sync anggota lain. Dicatat
            # supaya admin tahu siapa yang perlu hubungkan ulang.
            failed.append((member["display_name"] or user_id, str(exc)))
            continue

        for day in daily:
            rows.append([
                member["display_name"] or user_id,
                day.get("recorded_for_date"),
                day.get("steps", 0),
                day.get("total_distance", 0),
                day.get("calories", 0),
                day.get("active_time", 0),
                user_id,
            ])

    return rows, failed


def _row_key(row):
    """Identitas unik per baris untuk upsert.

    Baris baru selalu punya User ID (kolom ke-7), jadi di-key berdasarkan itu +
    tanggal. Baris lama (sebelum kolom User ID ditambahkan) belum punya nilai ini,
    jadi fallback ke (Nama, Tanggal) seperti perilaku lama supaya histori lama tidak
    dobel/tertimpa. Key by user_id mencegah tabrakan saat display_name kosong atau
    sama antar-anggota (mis. akun Apple SSO dengan nama disembunyikan).
    """
    user_id = row[6] if len(row) > 6 and row[6] else None
    if user_id:
        return ("uid", user_id, row[1])
    return ("name", row[0], row[1])


def _merge(existing_rows, new_rows):
    merged = {_row_key(row): row for row in existing_rows}
    for row in new_rows:
        merged[_row_key(row)] = row
    return sorted(merged.values(), key=lambda r: (r[0], r[1]))


def _finalized_rows(rows):
    """Baris yang tanggalnya H-1 (kemarin) atau lebih lama — dianggap "final" dan
    layak diarsipkan. Data hari ini (H) sengaja TIDAK diarsipkan dulu karena masih
    bisa berubah sepanjang hari (sync jalan beberapa kali sehari); begitu hari
    berganti, data H-1 otomatis ikut diarsipkan di sync berikutnya.
    """
    today = datetime.date.today().isoformat()
    return [row for row in rows if len(row) > 1 and row[1] and row[1] < today]


def _prune_old_rows(rows, retention_days):
    """Buang baris yang tanggalnya lebih tua dari `retention_days` hari dari sekarang.

    Dipakai HANYA untuk sheet "live" (dashboard). Baris yang dibuang di sini tidak
    hilang — sudah diupsert ke GOOGLE_SHEET_HISTORY_WORKSHEET terlebih dulu di
    run_sync() sebelum fungsi ini dipanggil.
    """
    cutoff = (datetime.date.today() - datetime.timedelta(days=retention_days)).isoformat()
    return [row for row in rows if len(row) > 1 and row[1] and row[1] >= cutoff]


def run_sync():
    """Ambil data terbaru dari Pacer (beberapa hari terakhir), lalu simpan ke dua sheet:

    - GOOGLE_SHEET_HISTORY_WORKSHEET (Raw_Pacer_History): arsip permanen, di-upsert
      per anggota+tanggal, TIDAK PERNAH dipangkas — ini yang menjamin histori tidak
      pernah hilang. Hanya diisi baris H-1 ke belakang (lihat _finalized_rows).
    - GOOGLE_SHEET_WORKSHEET (Raw_Pacer): sheet "live" untuk dashboard, di-upsert lalu
      dipangkas ke LIVE_RETENTION_DAYS hari terakhir supaya tetap ringkas dan tidak
      membesar tanpa batas (tiap sync clear + tulis ulang seluruh sheet ini). Sheet
      ini tetap menyimpan data hari ini (H) karena itu satu-satunya tempat data H
      terlihat sebelum diarsipkan besok.

    Kegagalan per-anggota (mis. refresh_token invalid) di-catch di
    _fetch_recent_rows dan tidak menggagalkan sync anggota lain; daftarnya
    dikembalikan lewat `failed_members` supaya bisa ditampilkan ke admin.
    """
    new_rows, failed_members = _fetch_recent_rows(FETCH_DAYS_BACK)
    _, existing_live_rows = sheets_client.read_rows(config.GOOGLE_SHEET_WORKSHEET)

    # 1. Arsipkan ke History dulu — hanya baris H-1 ke belakang (data hari ini belum
    #    "final", jangan diarsipkan dulu). Baris live yang sudah ada ikut disertakan
    #    supaya data lama yang masih di Raw_Pacer tidak hilang saat fitur ini
    #    pertama kali aktif.
    _, history_rows = sheets_client.read_rows(config.GOOGLE_SHEET_HISTORY_WORKSHEET)
    candidate_history = _merge(_merge(history_rows, existing_live_rows), new_rows)
    merged_history = _finalized_rows(candidate_history)
    sheets_client.write_rows(config.GOOGLE_SHEET_HISTORY_WORKSHEET, HEADER, merged_history)

    # 2. Upsert + pangkas sheet live untuk dashboard.
    merged_live = _merge(existing_live_rows, new_rows)
    pruned_live = _prune_old_rows(merged_live, LIVE_RETENTION_DAYS)
    sheets_client.write_rows(config.GOOGLE_SHEET_WORKSHEET, HEADER, pruned_live)

    print(
        f"Data tersinkron: History {len(merged_history)} baris total, "
        f"Raw_Pacer (live) {len(pruned_live)} baris, {len(new_rows)} baris diperbarui"
    )
    if failed_members:
        print(f"Gagal sync untuk {len(failed_members)} anggota: {failed_members}")

    return new_rows, pruned_live, failed_members


if __name__ == "__main__":
    updated, total, failed_members = run_sync()
    print(f"Sync selesai, {len(updated)} baris diperbarui, {len(total)} baris total.")
    if failed_members:
        print(f"Anggota gagal disinkron: {failed_members}")
