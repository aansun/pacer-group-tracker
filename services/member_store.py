import time

from services import db


def upsert_member(user_id, display_name, access_token, refresh_token, expires_in):
    expires_at = time.time() + expires_in
    with db.get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO members (user_id, display_name, access_token, refresh_token, expires_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, now())
            ON CONFLICT (user_id) DO UPDATE SET
                display_name  = EXCLUDED.display_name,
                access_token  = EXCLUDED.access_token,
                refresh_token = EXCLUDED.refresh_token,
                expires_at    = EXCLUDED.expires_at,
                updated_at    = now()
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


def list_members():
    with db.get_cursor() as cur:
        cur.execute(
            "SELECT user_id, display_name, access_token, refresh_token, expires_at FROM members"
        )
        rows = cur.fetchall()
    return {
        row["user_id"]: {
            "display_name": row["display_name"],
            "access_token": row["access_token"],
            "refresh_token": row["refresh_token"],
            "expires_at": row["expires_at"],
        }
        for row in rows
    }


def get_member(user_id):
    with db.get_cursor() as cur:
        cur.execute(
            "SELECT display_name, access_token, refresh_token, expires_at FROM members WHERE user_id = %s",
            (user_id,),
        )
        row = cur.fetchone()
    return dict(row) if row else None
