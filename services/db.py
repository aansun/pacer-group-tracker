"""Lapisan akses PostgreSQL generik: connection pool + init schema.

Semua modul lain (member_store, sync) memakai get_cursor() dari sini, tidak
pernah membuka koneksi psycopg2 sendiri-sendiri.

PENTING — isolasi schema: database ini bisa jadi dipakai BARENG aplikasi lain
(mis. Supabase project yang sama dipakai beberapa app). Supaya tidak pernah
bentrok/merusak tabel milik aplikasi lain, SEMUA tabel project ini hidup di
schema khusus `itd_pacer_tracker` (bukan `public`), dan setiap koneksi di pool
di-set `search_path` HANYA ke schema ini — jadi query tanpa prefix schema
(mis. `SELECT * FROM members`) otomatis dan selalu mengarah ke tabel kita
sendiri, tidak mungkin salah nyasar ke tabel app lain di `public` atau schema
lain, walau namanya kebetulan sama.
"""
import contextlib

import psycopg2
import psycopg2.extras
import psycopg2.pool

import config

_pool = None

SCHEMA_NAME = "itd_pacer_tracker"

SCHEMA_SQL = f"""
CREATE SCHEMA IF NOT EXISTS {SCHEMA_NAME};

CREATE TABLE IF NOT EXISTS members (
    user_id       TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL,
    access_token  TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    expires_at    DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS activities (
    user_id       TEXT NOT NULL REFERENCES members(user_id) ON DELETE CASCADE,
    activity_date DATE NOT NULL,
    steps         INTEGER NOT NULL DEFAULT 0,
    distance_m    DOUBLE PRECISION NOT NULL DEFAULT 0,
    calories      DOUBLE PRECISION NOT NULL DEFAULT 0,
    active_time_s INTEGER NOT NULL DEFAULT 0,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, activity_date)
);

CREATE INDEX IF NOT EXISTS idx_activities_date ON activities (activity_date);

CREATE TABLE IF NOT EXISTS sync_runs (
    id              SERIAL PRIMARY KEY,
    ran_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    source          TEXT NOT NULL,
    updated_count   INTEGER NOT NULL DEFAULT 0,
    total_count     INTEGER NOT NULL DEFAULT 0,
    error           TEXT,
    failed_members  JSONB
);
"""


def _get_pool():
    global _pool
    if _pool is None:
        if not config.DATABASE_URL:
            raise RuntimeError(
                "DATABASE_URL belum diset. Isi environment variable DATABASE_URL "
                "dengan connection string PostgreSQL (lihat SETUP.md)."
            )
        # search_path di-set per koneksi (bukan per query) supaya SEMUA query di
        # app ini otomatis terisolasi ke schema kita sendiri — lihat catatan di
        # atas. `public` sengaja TIDAK disertakan supaya tidak ada fallback yang
        # bisa nyasar ke tabel aplikasi lain.
        _pool = psycopg2.pool.SimpleConnectionPool(
            1, 5, dsn=config.DATABASE_URL, options=f"-c search_path={SCHEMA_NAME}"
        )
    return _pool


@contextlib.contextmanager
def get_cursor(commit=False):
    """Context manager: pinjam koneksi dari pool, kembalikan cursor dict-like.

    Otomatis commit kalau commit=True dan tidak ada exception, otomatis
    rollback kalau ada exception, dan koneksi selalu dikembalikan ke pool.
    """
    pool = _get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            yield cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def init_schema():
    """Idempoten — aman dipanggil setiap kali aplikasi start (CREATE ... IF NOT EXISTS)."""
    with get_cursor(commit=True) as cur:
        cur.execute(SCHEMA_SQL)
