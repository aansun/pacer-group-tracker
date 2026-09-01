import datetime
import time

import psycopg2.extras

import config
from services import db, member_store, sheets_export
from services.pacer_client import PacerClient, refresh_access_token

FETCH_DAYS_BACK = 2  # cukup untuk menangkap update hari ini + koreksi keterlambatan sync sebelumnya


def _ensure_fresh_token(user_id, member):
    if time.time() < member["expires_at"] - 60:
        return member["access_token"]

    data = refresh_access_token(member["refresh_token"])
    member_store.update_access_token(user_id, data["access_token"], data["expires_in"])
    return data["access_token"]


def _fetch_recent_rows(days_back):
    """Ambil aktivitas harian tiap anggota dari Pacer API.

    Kegagalan per-anggota (mis. refresh_token invalid karena akses dicabut di
    sisi Pacer) di-catch dan dilewati, tidak menggagalkan anggota lain.
    """
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
            failed.append((member["display_name"] or user_id, str(exc)))
            continue

        for day in daily:
            rows.append((
                user_id,
                day.get("recorded_for_date"),
                day.get("steps", 0),
                day.get("total_distance", 0),
                day.get("calories", 0),
                day.get("active_time", 0),
            ))

    return rows, failed


def _upsert_activities(rows):
    """Upsert per anggota+tanggal ke tabel `activities`.

    ON CONFLICT menggantikan seluruh logika merge/prune/arsip manual yang
    dulu diperlukan untuk Google Sheets — Postgres menyimpan histori penuh
    tanpa batas secara native, tidak ada lagi "sheet live" vs "arsip".
    """
    if not rows:
        return
    with db.get_cursor(commit=True) as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO activities
                (user_id, activity_date, steps, distance_m, calories, active_time_s, updated_at)
            VALUES %s
            ON CONFLICT (user_id, activity_date) DO UPDATE SET
                steps         = EXCLUDED.steps,
                distance_m    = EXCLUDED.distance_m,
                calories      = EXCLUDED.calories,
                active_time_s = EXCLUDED.active_time_s,
                updated_at    = now()
            """,
            rows,
            template="(%s, %s, %s, %s, %s, %s, now())",
        )


def run_sync():
    """Ambil data terbaru dari Pacer (beberapa hari terakhir) dan upsert ke
    tabel `activities` di Postgres. Histori tersimpan permanen, tidak pernah
    dipangkas — beda dari skema Google Sheets sebelumnya yang perlu sheet
    "live" + arsip terpisah karena keterbatasan ukuran/API sheet.

    Setelah Postgres ter-update, coba export ke Google Sheets (lihat
    services/sheets_export.py) — dua bentuk: cerminan N hari terakhir ke
    Raw_Pacer (format lama), dan matriks steps-only wide/pivot ke Data_Pacer
    (dipakai sheet turunan Score_Pacer/Mart_Raw_Pacer). Keduanya best-effort —
    kalau export gagal (quota, jaringan, dsb), sync ke Postgres TETAP
    dianggap berhasil.
    """
    new_rows, failed_members = _fetch_recent_rows(FETCH_DAYS_BACK)
    _upsert_activities(new_rows)

    with db.get_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM activities")
        total_count = cur.fetchone()["n"]

    print(
        f"Data tersinkron ke Postgres: {len(new_rows)} baris diupsert, "
        f"{total_count} baris total di tabel activities"
    )
    if failed_members:
        print(f"Gagal sync untuk {len(failed_members)} anggota: {failed_members}")

    try:
        exported = sheets_export.export_recent_activities()
        if exported is not None:
            print(f"Export ke Google Sheets: {exported} baris ({config.SHEETS_EXPORT_RETENTION_DAYS} hari terakhir)")
    except Exception as exc:
        print(f"PERINGATAN: export ke Google Sheets (Raw_Pacer) gagal, Postgres tetap aman: {exc}")

    try:
        wide_result = sheets_export.export_wide_steps_matrix()
        if wide_result is not None:
            n_dates, n_members = wide_result
            print(f"Export matriks steps ke {config.DATA_PACER_WORKSHEET}: {n_dates} tanggal x {n_members} anggota")
    except Exception as exc:
        print(f"PERINGATAN: export ke {config.DATA_PACER_WORKSHEET} gagal, Postgres tetap aman: {exc}")

    return len(new_rows), total_count, failed_members


if __name__ == "__main__":
    updated_count, total_count, failed_members = run_sync()
    print(f"Sync selesai, {updated_count} baris diperbarui, {total_count} baris total.")
    if failed_members:
        print(f"Anggota gagal disinkron: {failed_members}")
