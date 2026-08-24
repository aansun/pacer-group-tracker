import time

import config
from services import sheets_client

HEADER = ["user_id", "display_name", "access_token", "refresh_token", "expires_at"]
WORKSHEET = config.GOOGLE_MEMBERS_WORKSHEET
SPREADSHEET_ID = config.GOOGLE_MEMBERS_SHEET_ID


def _parse_expires_at(value):
    if not value:
        return 0
    try:
        return float(value)
    except ValueError:
        # Sel expires_at kadang rusak (mis. diformat ulang oleh Google Sheets
        # jadi ada pemisah ribuan seperti "17,876,707,931,684,900", biasanya
        # akibat sel sempat disentuh manual di UI Sheets). Anggap kedaluwarsa
        # (0) supaya token di-refresh otomatis saat sync berikutnya, alih-alih
        # meng-crash seluruh halaman untuk semua anggota.
        return 0


def _read_all():
    _, rows = sheets_client.read_rows(WORKSHEET, spreadsheet_id=SPREADSHEET_ID)
    members = {}
    for row in rows:
        if not row or not row[0]:
            continue
        user_id, display_name, access_token, refresh_token, expires_at = (row + [""] * 5)[:5]
        members[user_id] = {
            "display_name": display_name,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": _parse_expires_at(expires_at),
        }
    return members


def _write_all(members):
    rows = [
        [user_id, m["display_name"], m["access_token"], m["refresh_token"], str(m["expires_at"])]
        for user_id, m in members.items()
    ]
    sheets_client.write_rows(WORKSHEET, HEADER, rows, spreadsheet_id=SPREADSHEET_ID)


def upsert_member(user_id, display_name, access_token, refresh_token, expires_in):
    members = _read_all()
    members[user_id] = {
        "display_name": display_name,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": time.time() + expires_in,
    }
    _write_all(members)


def update_access_token(user_id, access_token, expires_in):
    members = _read_all()
    members[user_id]["access_token"] = access_token
    members[user_id]["expires_at"] = time.time() + expires_in
    _write_all(members)


def list_members():
    return _read_all()


def get_member(user_id):
    return _read_all().get(user_id)
