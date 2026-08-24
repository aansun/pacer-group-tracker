import json
import re

import gspread
from google.oauth2.service_account import Credentials

import config

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

_gc = None
# Cache per spreadsheet_id: open_by_key() melakukan fetch metadata (1 API read)
# setiap kali dipanggil. Tanpa cache ini, tiap read_rows/write_rows membuka ulang
# spreadsheet dan gampang menabrak quota "Read requests per minute" Google Sheets API.
_spreadsheets = {}


def _extract_sheet_id(value):
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", value)
    return match.group(1) if match else value


def _client():
    global _gc
    if _gc is not None:
        return _gc

    if config.GOOGLE_SERVICE_ACCOUNT_JSON:
        info = json.loads(config.GOOGLE_SERVICE_ACCOUNT_JSON)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file(
            config.GOOGLE_SERVICE_ACCOUNT_FILE, scopes=SCOPES
        )

    # BackOffHTTPClient otomatis retry dengan exponential backoff saat Google
    # membalas 429 (quota exceeded), alih-alih langsung melempar APIError.
    _gc = gspread.authorize(creds, http_client=gspread.BackOffHTTPClient)
    return _gc


def _open_spreadsheet(spreadsheet_id):
    key = _extract_sheet_id(spreadsheet_id)
    if key not in _spreadsheets:
        _spreadsheets[key] = _client().open_by_key(key)
    return _spreadsheets[key]


def get_worksheet(title, spreadsheet_id=None, rows=1000, cols=20):
    spreadsheet_id = spreadsheet_id or config.GOOGLE_SHEET_ID
    sheet = _open_spreadsheet(spreadsheet_id)
    try:
        return sheet.worksheet(title)
    except gspread.exceptions.WorksheetNotFound:
        return sheet.add_worksheet(title=title, rows=rows, cols=cols)


def read_rows(worksheet_title, spreadsheet_id=None):
    ws = get_worksheet(worksheet_title, spreadsheet_id=spreadsheet_id)
    all_rows = ws.get_all_values()
    if not all_rows:
        return None, []
    header, *rows = all_rows
    return header, rows


def write_rows(worksheet_title, header, rows, spreadsheet_id=None):
    ws = get_worksheet(worksheet_title, spreadsheet_id=spreadsheet_id)
    ws.clear()
    ws.append_row(header)
    if rows:
        ws.append_rows(rows)
