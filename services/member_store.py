import time

from services import db

# Baru dianggap "perlu hubungkan ulang" setelah gagal BERTURUT-TURUT sebanyak
# ini. Sync jalan ~5x/hari, jadi 3 kali gagal berturut-turut berarti sudah
# gagal konsisten selama lebih dari setengah hari — bukan blip API sesaat dari
# Pacer (yang biasanya cuma gagal sekali lalu normal lagi di percobaan
# berikutnya).
SYNC_ERROR_THRESHOLD = 3


def upsert_member(user_id, display_name, access_token, refresh_token, expires_in):
    expires_at = time.time() + expires_in
    with db.get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO members (user_id, display_name, access_token, refresh_token, expires_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, now())
            ON CONFLICT (user_id) DO UPDATE SET
                display_name      = EXCLUDED.display_name,
                access_token      = EXCLUDED.access_token,
                refresh_token     = EXCLUDED.refresh_token,
                expires_at        = EXCLUDED.expires_at,
                updated_at        = now(),
                sync_error_count  = 0,
                last_sync_error   = NULL,
                last_sync_error_at = NULL
            """,
            (user_id, display_name, access_token, refresh_token, expires_at),
        )


def update_access_token(user_id, access_token, expires_in):
    expires_at = time.time() + expires_in
    with db.get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE members SET access_token = %s, expires_at = %s, updated_at = now() WHERE user_id = %s",
            (access_token, expires_at, user_id),
        )


def mark_sync_error(user_id, error_message):
    """Catat satu kegagalan fetch Pacer API. Tidak langsung dianggap "perlu
    hubungkan ulang" — cuma menaikkan counter, lihat SYNC_ERROR_THRESHOLD."""
    with db.get_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE members SET
                sync_error_count    = sync_error_count + 1,
                last_sync_error     = %s,
                last_sync_error_at  = now()
            WHERE user_id = %s
            """,
            (error_message, user_id),
        )


def clear_sync_error(user_id):
    """Satu kali fetch berhasil pun cukup untuk mereset status error sepenuhnya."""
    with db.get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE members SET sync_error_count = 0, last_sync_error = NULL, last_sync_error_at = NULL WHERE user_id = %s",
            (user_id,),
        )


def list_members():
    with db.get_cursor() as cur:
        cur.execute(
            """
            SELECT user_id, display_name, access_token, refresh_token, expires_at,
                   sync_error_count, last_sync_error, last_sync_error_at
            FROM members
            """
        )
        rows = cur.fetchall()
    return {
        row["user_id"]: {
            "display_name": row["display_name"],
            "access_token": row["access_token"],
            "refresh_token": row["refresh_token"],
            "expires_at": row["expires_at"],
            "sync_error_count": row["sync_error_count"],
            "last_sync_error": row["last_sync_error"],
            "last_sync_error_at": row["last_sync_error_at"],
        }
        for row in rows
    }


def friendly_sync_error(raw_error):
    """Terjemahkan error teknis dari Pacer API jadi kalimat yang bisa
    dipahami admin (untuk disampaikan ke anggota terkait)."""
    text = (raw_error or "").lower()
    if "getaccountiderror" in text:
        return "Akses ke akun Pacer sudah tidak valid — kemungkinan dicabut atau akun Pacer-nya dihapus/diganti."
    if "invalid_grant" in text or "refresh_token" in text:
        return "Sesi koneksi ke Pacer sudah kedaluwarsa."
    return "Gagal mengambil data dari Pacer beberapa kali berturut-turut."


def members_needing_reconnect(members):
    """Filter dict dari list_members(): anggota yang gagal sync BERTURUT-TURUT
    melebihi SYNC_ERROR_THRESHOLD (bukan cuma sekali gagal — itu biasanya blip
    API sesaat dari Pacer yang akan normal lagi di percobaan berikutnya)."""
    return {
        uid: m for uid, m in members.items()
        if m.get("sync_error_count", 0) >= SYNC_ERROR_THRESHOLD
    }


def get_member(user_id):
    with db.get_cursor() as cur:
        cur.execute(
            "SELECT display_name, access_token, refresh_token, expires_at FROM members WHERE user_id = %s",
            (user_id,),
        )
        row = cur.fetchone()
    return dict(row) if row else None
