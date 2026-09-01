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
