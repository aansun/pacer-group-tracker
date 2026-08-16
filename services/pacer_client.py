import hashlib
import urllib.parse

import requests

import config


def _encoded_signature():
    """Authorization header for oauth2/access_token.

    Salt string yang benar adalah "pacer_oauth" (tanpa angka 2) —
    dokumentasi resmi Pacer menulis "pacer_oauth2" tapi itu tidak bekerja
    terhadap API live; dikonfirmasi lewat reference implementation
    ankamv.medium.com "Using Python to connect to Pacer's API step by step".

    NOTE keamanan: MD5 dipakai di sini BUKAN untuk keperluan kriptografi kita
    sendiri, melainkan karena ini adalah skema signature yang diwajibkan oleh
    Pacer API pihak ketiga (di luar kendali kita) — bukan untuk hashing
    password/data sensitif milik aplikasi ini. Algoritma tidak bisa diganti
    tanpa memutus kompatibilitas dengan Pacer API.
    """
    app_secret_hash = hashlib.md5(  # NOSONAR - wajib MD5, ditentukan skema OAuth Pacer API
        (config.PACER_CLIENT_SECRET + "pacer_oauth").encode("utf-8")
    ).hexdigest()
    return hashlib.md5(  # NOSONAR - wajib MD5, ditentukan skema OAuth Pacer API
        (app_secret_hash + config.PACER_CLIENT_ID).encode("utf-8")
    ).hexdigest()


def get_authorization_url(state):
    params = {
        "client_id": config.PACER_CLIENT_ID,
        "redirect_uri": config.PACER_REDIRECT_URI,
        "state": state,
    }
    return f"{config.PACER_AUTH_BASE_URL}/oauth2/dialog?{urllib.parse.urlencode(params)}"


def exchange_code_for_token(code):
    resp = requests.post(
        f"{config.PACER_API_BASE_URL}/oauth2/access_token",
        headers={
            "Authorization": _encoded_signature(),
            "Content-Type": "application/json",
        },
        json={
            "client_id": config.PACER_CLIENT_ID,
            "code": code,
            "redirect_uri": config.PACER_REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=15,
    )
    resp.raise_for_status()
    body = resp.json()
    if not body.get("success"):
        raise RuntimeError(f"Pacer token exchange failed: {body}")
    return body["data"]  # access_token, refresh_token, expires_in, user_id


def refresh_access_token(refresh_token):
    resp = requests.post(
        f"{config.PACER_API_BASE_URL}/oauth2/access_token",
        headers={
            "Authorization": _encoded_signature(),
            "Content-Type": "application/json",
        },
        json={
            "client_id": config.PACER_CLIENT_ID,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=15,
    )
    resp.raise_for_status()
    body = resp.json()
    if not body.get("success"):
        raise RuntimeError(f"Pacer token refresh failed: {body}")
    return body["data"]  # access_token, expires_in, user_id


class PacerClient:
    """Client untuk satu user Pacer yang sudah terautentikasi (access_token miliknya)."""

    def __init__(self, access_token):
        self.access_token = access_token

    def _get(self, path, params=None):
        resp = requests.get(
            f"{config.PACER_API_BASE_URL}{path}",
            headers={"Authorization": f"Bearer {self.access_token}"},
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        body = resp.json()
        if not body.get("success"):
            raise RuntimeError(f"Pacer API error: {body}")
        return body["data"]

    def get_user_info(self, user_id):
        return self._get(f"/users/{user_id}")

    def get_daily_activity_summary(self, user_id, start_date, end_date, accept_manual_input=True):
        return self._get(
            f"/users/{user_id}/activities/daily.json",
            params={
                "start_date": start_date,
                "end_date": end_date,
                "accept_manual_input": str(accept_manual_input).lower(),
            },
        )["daily_activities"]

    def get_session_activities(self, user_id, start_date, end_date):
        return self._get(
            f"/users/{user_id}/activities/session.json",
            params={"start_date": start_date, "end_date": end_date},
        )["session_activities"]
