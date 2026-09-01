"""Backfill langkah (steps) untuk rentang tanggal tertentu langsung dari Pacer API.

Dipakai untuk mengisi histori yang tidak bisa dimigrasikan dari Google Sheets
(baris lama dari sebelum kolom "User ID" ditambahkan, sebelum ~23 Agustus —
lihat scripts/migrate_from_sheets.py). Sengaja HANYA mengambil & menyimpan
`steps`, sesuai permintaan — kolom lain (distance_m, calories, active_time_s)
TIDAK disentuh kalau baris sudah ada (supaya tidak menimpa data yang sudah
benar dari migrasi Sheets), atau default 0 kalau baris baru.

Cara pakai:
    source venv/bin/activate
    python -m scripts.backfill_steps 2026-07-11 2026-07-31
"""
import datetime
import sys

import psycopg2.extras

from services import db, member_store
from services.pacer_client import PacerClient
from sync import _ensure_fresh_token


def backfill(start_date, end_date):
    db.init_schema()
    members = member_store.list_members()

    total_rows = 0
    failed = []

    for user_id, member in members.items():
        display_name = member["display_name"] or user_id
        try:
            access_token = _ensure_fresh_token(user_id, member)
            client = PacerClient(access_token)
            daily = client.get_daily_activity_summary(
                user_id,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
            )
        except Exception as exc:
            failed.append((display_name, str(exc)))
            print(f"  GAGAL {display_name}: {exc}")
            continue

        rows = [
            (user_id, day.get("recorded_for_date"), day.get("steps", 0))
            for day in daily
            if day.get("recorded_for_date")
        ]
        if not rows:
            print(f"  {display_name}: tidak ada data pada rentang ini")
            continue

        with db.get_cursor(commit=True) as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO activities (user_id, activity_date, steps)
                VALUES %s
                ON CONFLICT (user_id, activity_date) DO UPDATE SET
                    steps      = EXCLUDED.steps,
                    updated_at = now()
                """,
                rows,
            )
        total_rows += len(rows)
        print(f"  {display_name}: {len(rows)} hari")

    print(f"\nSelesai. {total_rows} baris steps di-upsert dari Pacer API ({start_date} s/d {end_date}).")
    if failed:
        print(f"Gagal untuk {len(failed)} anggota: {failed}")
    return total_rows, failed


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python -m scripts.backfill_steps YYYY-MM-DD YYYY-MM-DD")
        sys.exit(1)
    _start = datetime.date.fromisoformat(sys.argv[1])
    _end = datetime.date.fromisoformat(sys.argv[2])
    backfill(_start, _end)
