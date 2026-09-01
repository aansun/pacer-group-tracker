"""Migrasi satu-kali: Google Sheets (Members, Raw_Pacer, Raw_Pacer_History) -> Postgres.

Read-only terhadap Google Sheets — TIDAK PERNAH menulis balik ke sana. Aman
dijalankan berkali-kali (idempoten, upsert via ON CONFLICT), jadi kalau
terputus di tengah jalan tinggal dijalankan ulang.

Urutan migrasi penting: Members dulu (tabel `activities` punya FK ke
`members`), baru Raw_Pacer_History + Raw_Pacer.

Cara pakai:
    source venv/bin/activate
    python -m scripts.migrate_from_sheets
"""
import sys

import config
from services import db, sheets_client


def _row_key(row):
    """Sama seperti sync.py versi lama: identitas unik per baris aktivitas.

    Baris dengan User ID (kolom ke-7) di-key by user_id; baris lama tanpa User
    ID (sebelum kolom itu ditambahkan) di-key by nama — dipakai HANYA untuk
    dedup di sisi Sheets sebelum migrasi, bukan disimpan ke Postgres.
    """
    user_id = row[6] if len(row) > 6 and row[6] else None
    if user_id:
        return ("uid", user_id, row[1])
    return ("name", row[0], row[1])


def _merge(*row_lists):
    merged = {}
    for rows in row_lists:
        for row in rows:
            merged[_row_key(row)] = row
    return list(merged.values())


def migrate_members():
    print("== Migrasi Members ==")
    _, rows = sheets_client.read_rows(config.GOOGLE_MEMBERS_WORKSHEET, spreadsheet_id=config.GOOGLE_MEMBERS_SHEET_ID)

    migrated = 0
    with db.get_cursor(commit=True) as cur:
        for row in rows:
            if not row or not row[0]:
                continue
            user_id, display_name, access_token, refresh_token, expires_at = (row + [""] * 5)[:5]
            try:
                expires_at = float(expires_at) if expires_at else 0
            except ValueError:
                expires_at = 0

            cur.execute(
                """
                INSERT INTO members (user_id, display_name, access_token, refresh_token, expires_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    display_name  = EXCLUDED.display_name,
                    access_token  = EXCLUDED.access_token,
                    refresh_token = EXCLUDED.refresh_token,
                    expires_at    = EXCLUDED.expires_at
                """,
                (user_id, display_name or user_id, access_token, refresh_token, expires_at),
            )
            migrated += 1

    print(f"  {migrated} anggota dimigrasikan ke tabel members.")
    return migrated


def migrate_activities():
    print("== Migrasi Aktivitas (Raw_Pacer_History + Raw_Pacer) ==")
    _, history_rows = sheets_client.read_rows(config.GOOGLE_SHEET_HISTORY_WORKSHEET)
    _, live_rows = sheets_client.read_rows(config.GOOGLE_SHEET_WORKSHEET)
    all_rows = _merge(history_rows, live_rows)
    print(f"  {len(history_rows)} baris History + {len(live_rows)} baris live -> {len(all_rows)} baris unik setelah dedup.")

    with db.get_cursor() as cur:
        cur.execute("SELECT user_id FROM members")
        known_user_ids = {r["user_id"] for r in cur.fetchall()}

    to_insert = []
    skipped_no_user_id = 0
    skipped_unknown_member = []
    for row in all_rows:
        if len(row) < 2 or not row[1]:
            continue
        user_id = row[6] if len(row) > 6 and row[6] else None
        if not user_id:
            # Baris lama dari sebelum kolom User ID ditambahkan (hanya ada Nama).
            # Tidak bisa dipetakan ke anggota dengan aman (nama bisa kosong/duplikat
            # — ini justru bug yang sudah kita perbaiki), jadi dilewati.
            skipped_no_user_id += 1
            continue
        if user_id not in known_user_ids:
            skipped_unknown_member.append((user_id, row[1]))
            continue

        steps = row[2] if len(row) > 2 else 0
        distance = row[3] if len(row) > 3 else 0
        calories = row[4] if len(row) > 4 else 0
        active_time = row[5] if len(row) > 5 else 0
        to_insert.append((user_id, row[1], steps or 0, distance or 0, calories or 0, active_time or 0))

    if to_insert:
        import psycopg2.extras
        with db.get_cursor(commit=True) as cur:
            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO activities (user_id, activity_date, steps, distance_m, calories, active_time_s)
                VALUES %s
                ON CONFLICT (user_id, activity_date) DO UPDATE SET
                    steps         = EXCLUDED.steps,
                    distance_m    = EXCLUDED.distance_m,
                    calories      = EXCLUDED.calories,
                    active_time_s = EXCLUDED.active_time_s
                """,
                to_insert,
            )

    print(f"  {len(to_insert)} baris aktivitas dimigrasikan ke tabel activities.")
    if skipped_no_user_id:
        print(f"  PERINGATAN: {skipped_no_user_id} baris lama dilewati (tidak ada User ID, dari sebelum kolom itu ditambahkan).")
    if skipped_unknown_member:
        print(f"  PERINGATAN: {len(skipped_unknown_member)} baris dilewati karena user_id tidak ada di tabel members: {skipped_unknown_member[:10]}{' ...' if len(skipped_unknown_member) > 10 else ''}")
    return len(to_insert)


def main():
    db.init_schema()
    member_count = migrate_members()
    activity_count = migrate_activities()
    print(f"\nSelesai. {member_count} anggota, {activity_count} baris aktivitas di Postgres.")
    print("Data di Google Sheets TIDAK diubah/dihapus — aman dijadikan cadangan/verifikasi silang.")


if __name__ == "__main__":
    sys.exit(main())
