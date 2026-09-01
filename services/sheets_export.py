"""Export read-only dari Postgres ke Google Sheets, untuk kebutuhan laporan
yang lebih familiar (pivot table, dilihat non-teknis, dsb).

Postgres tetap satu-satunya sumber kebenaran permanen — sheet ini HANYA
cerminan `SHEETS_EXPORT_RETENTION_DAYS` hari terakhir (bukan histori penuh)
supaya tetap ringan dan tidak kena rate limit Sheets API. Dipanggil dari
sync.py setiap kali sync berhasil; kegagalan di sini tidak menggagalkan sync
ke Postgres (best-effort).
"""
import datetime

import config
from services import db, sheets_client

HEADER = ["Nama", "Tanggal", "Langkah", "Jarak (m)", "Kalori", "Waktu Aktif (s)", "User ID"]


def export_recent_activities():
    """Tulis ulang GOOGLE_SHEET_WORKSHEET dengan data N hari terakhir dari
    Postgres. Return jumlah baris yang di-export, atau None kalau export
    dinonaktifkan (GOOGLE_SHEET_ID kosong).
    """
    if not config.GOOGLE_SHEET_ID:
        return None

    cutoff = (
        datetime.date.today() - datetime.timedelta(days=config.SHEETS_EXPORT_RETENTION_DAYS)
    ).isoformat()

    with db.get_cursor() as cur:
        cur.execute(
            """
            SELECT m.display_name, a.activity_date, a.steps, a.distance_m,
                   a.calories, a.active_time_s, a.user_id
            FROM activities a
            JOIN members m ON m.user_id = a.user_id
            WHERE a.activity_date >= %s
            ORDER BY m.display_name, a.activity_date
            """,
            (cutoff,),
        )
        rows = [
            [
                r["display_name"],
                r["activity_date"].isoformat(),
                r["steps"],
                r["distance_m"],
                r["calories"],
                r["active_time_s"],
                r["user_id"],
            ]
            for r in cur.fetchall()
        ]

    sheets_client.write_rows(
        config.GOOGLE_SHEET_WORKSHEET, HEADER, rows, spreadsheet_id=config.GOOGLE_SHEET_ID
    )
    return len(rows)


def build_wide_steps_matrix():
    """Susun matriks wide/pivot steps-only sesuai format sheet `Data_Pacer` yang
    sudah ada (dipakai sheet turunan seperti Score_Pacer, Mart_Raw_Pacer, dst):

    - Baris 1-2: kosong (spacer, ikut format asli)
    - Baris 3 : kolom A kosong, kolom B+ = nama anggota
    - Baris 4 : kolom A "Tanggal", kolom B+ = User ID anggota (identitas asli
                kolom, BUKAN nama — supaya tidak rawan tabrakan nama)
    - Baris 5+: satu baris per tanggal, kolom A = tanggal, kolom B+ = steps

    Kolom anggota yang SUDAH ADA di template dipertahankan urutannya (supaya
    formula di sheet turunan yang mereferensikan posisi kolom tidak rusak).
    Anggota baru yang belum punya kolom otomatis ditambahkan di akhir.

    HANYA `steps` yang diambil (bukan jarak/kalori/waktu aktif), sesuai
    permintaan — dan mengambil SELURUH histori (bukan dibatasi retensi seperti
    export ke Raw_Pacer) karena bentuk pivot ini hanya bertambah lebar per
    tanggal baru, bukan per anggota+tanggal, jadi tetap ringan.

    Return (matrix, jumlah_baris_tanggal, jumlah_kolom_anggota, ordered_ids).
    """
    ws = sheets_client.get_worksheet(config.DATA_PACER_WORKSHEET, spreadsheet_id=config.GOOGLE_SHEET_ID)
    existing_ids_row = ws.row_values(4)
    existing_ids = existing_ids_row[1:] if len(existing_ids_row) > 1 else []

    with db.get_cursor() as cur:
        cur.execute("SELECT user_id, display_name FROM members ORDER BY display_name")
        member_names = {r["user_id"]: r["display_name"] for r in cur.fetchall()}

    ordered_ids = [uid for uid in existing_ids if uid in member_names]
    ordered_ids += [uid for uid in member_names if uid not in ordered_ids]

    with db.get_cursor() as cur:
        cur.execute("SELECT user_id, activity_date, steps FROM activities ORDER BY activity_date")
        by_date = {}
        for r in cur.fetchall():
            by_date.setdefault(r["activity_date"], {})[r["user_id"]] = r["steps"]

    ncols = 1 + len(ordered_ids)
    name_row = [""] + [member_names[uid] for uid in ordered_ids]
    id_row = ["Tanggal"] + ordered_ids
    data_rows = [
        [d.isoformat()] + [by_date[d].get(uid, "") for uid in ordered_ids]
        for d in sorted(by_date)
    ]

    matrix = [[""] * ncols, [""] * ncols, name_row, id_row] + data_rows
    return matrix, len(data_rows), len(ordered_ids), ordered_ids


def export_wide_steps_matrix():
    """Tulis build_wide_steps_matrix() ke sheet Data_Pacer. Return
    (jumlah_baris_tanggal, jumlah_kolom_anggota), atau None kalau export
    dinonaktifkan (GOOGLE_SHEET_ID kosong).
    """
    if not config.GOOGLE_SHEET_ID:
        return None

    matrix, n_dates, n_members, _ = build_wide_steps_matrix()
    ws = sheets_client.get_worksheet(config.DATA_PACER_WORKSHEET, spreadsheet_id=config.GOOGLE_SHEET_ID)
    ws.clear()
    ws.update(range_name="A1", values=matrix, value_input_option="USER_ENTERED")
    if n_dates:
        # Samakan format tampilan tanggal (M/D/YYYY, konvensi yang sudah dipakai
        # template ini) — nilai aslinya tetap date asli, ini cuma kosmetik supaya
        # tidak campur "7/11/2026" vs "2026-09-01" di kolom yang sama.
        last_row = 4 + n_dates
        ws.format(f"A5:A{last_row}", {"numberFormat": {"type": "DATE", "pattern": "M/D/YYYY"}})
    return n_dates, n_members
