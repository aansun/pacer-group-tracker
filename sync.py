import datetime
import time

import config
from services import member_store, sheets_client
from services.pacer_client import PacerClient, refresh_access_token

HEADER = ["Nama", "Tanggal", "Langkah", "Jarak (m)", "Kalori", "Waktu Aktif (s)"]
FETCH_DAYS_BACK = 2  # cukup untuk menangkap update hari ini + koreksi keterlambatan sync sebelumnya


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
    for user_id, member in members.items():
        access_token = _ensure_fresh_token(user_id, member)
        client = PacerClient(access_token)

        daily = client.get_daily_activity_summary(
            user_id,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )

        for day in daily:
            rows.append([
                member["display_name"],
                day.get("recorded_for_date"),
                day.get("steps", 0),
                day.get("total_distance", 0),
                day.get("calories", 0),
                day.get("active_time", 0),
            ])

    return rows


def _merge(existing_rows, new_rows):
    merged = {(row[0], row[1]): row for row in existing_rows}
    for row in new_rows:
        merged[(row[0], row[1])] = row
    return sorted(merged.values(), key=lambda r: (r[0], r[1]))


def run_sync():
    """Ambil data terbaru dari Pacer (beberapa hari terakhir) dan gabungkan
    (upsert per anggota+tanggal) ke histori yang sudah ada di Google Sheets."""
    _, existing_rows = sheets_client.read_rows(config.GOOGLE_SHEET_WORKSHEET)
    new_rows = _fetch_recent_rows(FETCH_DAYS_BACK)
    merged_rows = _merge(existing_rows, new_rows)

    sheets_client.write_rows(config.GOOGLE_SHEET_WORKSHEET, HEADER, merged_rows)
    print(f"Data tersinkron ke Google Sheets ({len(merged_rows)} baris total, {len(new_rows)} baris diperbarui)")

    return new_rows, merged_rows


if __name__ == "__main__":
    updated, total = run_sync()
    print(f"Sync selesai, {len(updated)} baris diperbarui, {len(total)} baris total.")
