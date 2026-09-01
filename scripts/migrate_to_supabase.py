"""Migrasi satu-kali: PostgreSQL lama (Render, schema public) -> PostgreSQL
baru (Supabase, schema itd_pacer_tracker, via connection pooler).

Read-only terhadap database LAMA — tidak pernah menulis balik ke sana.
Idempoten (upsert via ON CONFLICT), aman dijalankan ulang. Target ditentukan
oleh config.DATABASE_URL seperti biasa (services/db.py yang mengurus isolasi
schema itd_pacer_tracker, jadi tidak menyentuh tabel aplikasi lain).

Cara pakai:
    source venv/bin/activate
    OLD_DATABASE_URL=postgresql://user:pass@host/db python -m scripts.migrate_to_supabase
"""
import os
import sys

import psycopg2
import psycopg2.extras

from services import db


def main():
    old_url = os.getenv("OLD_DATABASE_URL")
    if not old_url:
        print("Set OLD_DATABASE_URL ke connection string database lama (Render).")
        sys.exit(1)

    db.init_schema()  # pastikan schema + tabel target (Supabase) sudah ada, idempoten

    src = psycopg2.connect(old_url, sslmode="require")
    src_cur = src.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    src_cur.execute(
        "SELECT user_id, display_name, access_token, refresh_token, expires_at FROM members"
    )
    members = src_cur.fetchall()
    with db.get_cursor(commit=True) as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO members (user_id, display_name, access_token, refresh_token, expires_at)
            VALUES %s
            ON CONFLICT (user_id) DO UPDATE SET
                display_name  = EXCLUDED.display_name,
                access_token  = EXCLUDED.access_token,
                refresh_token = EXCLUDED.refresh_token,
                expires_at    = EXCLUDED.expires_at
            """,
            [
                (m["user_id"], m["display_name"], m["access_token"], m["refresh_token"], m["expires_at"])
                for m in members
            ],
        )
    print(f"{len(members)} anggota dimigrasikan ke Supabase.")

    src_cur.execute(
        "SELECT user_id, activity_date, steps, distance_m, calories, active_time_s FROM activities"
    )
    activities = src_cur.fetchall()
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
            [
                (a["user_id"], a["activity_date"], a["steps"], a["distance_m"], a["calories"], a["active_time_s"])
                for a in activities
            ],
        )
    print(f"{len(activities)} baris aktivitas dimigrasikan ke Supabase.")

    src.close()
    print("\nSelesai. Database lama (Render) TIDAK diubah — aman jadi cadangan sampai diverifikasi.")
    return len(members), len(activities)


if __name__ == "__main__":
    main()
