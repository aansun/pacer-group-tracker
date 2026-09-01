import os
from dotenv import load_dotenv

load_dotenv()

PACER_CLIENT_ID = os.getenv("PACER_CLIENT_ID")
PACER_CLIENT_SECRET = os.getenv("PACER_CLIENT_SECRET")
PACER_AUTH_BASE_URL = os.getenv("PACER_AUTH_BASE_URL", "https://developer.mypacer.com")
PACER_API_BASE_URL = os.getenv("PACER_API_BASE_URL", "https://openapi.mypacer.com")
PACER_REDIRECT_URI = os.getenv("PACER_REDIRECT_URI")

# Penyimpanan utama aplikasi: PostgreSQL. Format standar
# postgresql://user:password@host:port/dbname (Render Postgres, Supabase, Neon,
# Railway, dll semua expose connection string dengan format ini).
DATABASE_URL = os.getenv("DATABASE_URL")

# --- Legacy: Google Sheets ---------------------------------------------------
# Konfigurasi di bawah ini HANYA dipakai oleh scripts/migrate_from_sheets.py
# (migrasi satu kali dari Google Sheets ke Postgres). Aplikasi utama (app.py,
# sync.py, member_store.py) sudah sepenuhnya memakai Postgres, bukan Sheets ini.
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials/google-service-account.json")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_SHEET_WORKSHEET = os.getenv("GOOGLE_SHEET_WORKSHEET", "Raw_Pacer")
GOOGLE_SHEET_HISTORY_WORKSHEET = os.getenv("GOOGLE_SHEET_HISTORY_WORKSHEET", "Raw_Pacer_History")
GOOGLE_MEMBERS_SHEET_ID = os.getenv("GOOGLE_MEMBERS_SHEET_ID")
GOOGLE_MEMBERS_WORKSHEET = os.getenv("GOOGLE_MEMBERS_WORKSHEET", "Members")
# -----------------------------------------------------------------------------

FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "change-me")

LOGIN_USERNAME = os.getenv("LOGIN_USERNAME", "admin")
LOGIN_PASSWORD = os.getenv("LOGIN_PASSWORD", "change-me")

# Token rahasia khusus untuk trigger sync dari cron eksternal (mis. cron-job.org),
# tanpa perlu login/session. Kosongkan untuk menonaktifkan endpoint ini.
CRON_SYNC_TOKEN = os.getenv("CRON_SYNC_TOKEN", "")

# Auto-logout kalau tidak ada aktivitas selama sekian menit (default 60 = 1 jam)
SESSION_TIMEOUT_MINUTES = int(os.getenv("SESSION_TIMEOUT_MINUTES", "60"))

# Werkzeug debug mode HARUS mati di production (bisa membuka remote code execution
# lewat debugger interaktif kalau aktif). Set "true" hanya untuk development lokal.
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"
