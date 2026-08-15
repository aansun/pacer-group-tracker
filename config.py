import os
from dotenv import load_dotenv

load_dotenv()

PACER_CLIENT_ID = os.getenv("PACER_CLIENT_ID")
PACER_CLIENT_SECRET = os.getenv("PACER_CLIENT_SECRET")
PACER_AUTH_BASE_URL = os.getenv("PACER_AUTH_BASE_URL", "http://developer.mypacer.com")
PACER_API_BASE_URL = os.getenv("PACER_API_BASE_URL", "http://openapi.mypacer.com")
PACER_REDIRECT_URI = os.getenv("PACER_REDIRECT_URI")

# Isi salah satu: GOOGLE_SERVICE_ACCOUNT_JSON (isi file JSON dalam satu baris, dipakai di Render)
# atau GOOGLE_SERVICE_ACCOUNT_FILE (path ke file, dipakai untuk dev lokal)
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "credentials/google-service-account.json")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_SHEET_WORKSHEET = os.getenv("GOOGLE_SHEET_WORKSHEET", "Raw_Pacer")

# Spreadsheet TERPISAH khusus token anggota (private, hanya di-share ke service account + admin)
GOOGLE_MEMBERS_SHEET_ID = os.getenv("GOOGLE_MEMBERS_SHEET_ID")
GOOGLE_MEMBERS_WORKSHEET = os.getenv("GOOGLE_MEMBERS_WORKSHEET", "Members")

FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "change-me")

LOGIN_USERNAME = os.getenv("LOGIN_USERNAME", "admin")
LOGIN_PASSWORD = os.getenv("LOGIN_PASSWORD", "change-me")
