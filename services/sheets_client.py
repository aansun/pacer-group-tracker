import json
import re

import gspread
from google.oauth2.service_account import Credentials

import config

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

_gc = None


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

    _gc = gspread.authorize(creds)
    return _gc


def get_worksheet(title, spreadsheet_id=None, rows=1000, cols=20):
    spreadsheet_id = spreadsheet_id or config.GOOGLE_SHEET_ID
    sheet = _client().open_by_key(_extract_sheet_id(spreadsheet_id))
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
