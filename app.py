import datetime
import functools
import secrets

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger
from flask import Flask, render_template, redirect, url_for, flash, request, session, jsonify
from flask_wtf import CSRFProtect

import config
from services import member_store, sync_state
from services.pacer_client import get_authorization_url, exchange_code_for_token, PacerClient
from sync import run_sync

app = Flask(__name__)
app.secret_key = config.FLASK_SECRET_KEY
app.permanent_session_lifetime = datetime.timedelta(minutes=config.SESSION_TIMEOUT_MINUTES)

# Proteksi CSRF untuk seluruh form/POST berbasis session (login, sync manual).
# /sync/cron dikecualikan karena memakai autentikasi token terpisah (bukan cookie session).
csrf = CSRFProtect(app)

SCHEDULE_TIMES = ["08:00", "12:00", "15:00", "21:00", "23:55"]


@app.before_request
def _enforce_session_timeout():
    """Paksa logout kalau tidak ada aktivitas selama SESSION_TIMEOUT_MINUTES.

    Setiap request yang datang dari user yang sedang login akan me-refresh
    waktu aktivitas terakhir (sliding expiration), jadi timeout dihitung dari
    request TERAKHIR, bukan dari waktu login.
    """
    if not session.get("logged_in"):
        return

    now = datetime.datetime.now(datetime.timezone.utc).timestamp()
    last_seen = session.get("last_activity")
    timeout_seconds = config.SESSION_TIMEOUT_MINUTES * 60

    if last_seen is not None and (now - last_seen) > timeout_seconds:
        session.clear()
        flash("Sesi berakhir karena tidak ada aktivitas selama 1 jam. Silakan login kembali.", "error")
        return redirect(url_for("login", next=request.path))

    session["last_activity"] = now
    session.permanent = True


def _schedule_trigger(times):
    return OrTrigger([
        CronTrigger(hour=int(h), minute=int(m))
        for h, m in (t.split(":") for t in times)
    ])


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        valid = secrets.compare_digest(username, config.LOGIN_USERNAME) and \
            secrets.compare_digest(password, config.LOGIN_PASSWORD)
        if valid:
            session["logged_in"] = True
            session["username"] = username
            session["last_activity"] = datetime.datetime.now(datetime.timezone.utc).timestamp()
            session.permanent = True
            return redirect(request.args.get("next") or url_for("index"))
        flash("Username atau password salah.", "error")
    return render_template("login.html")


@app.route("/logout", methods=["GET"])
def logout():
    session.clear()
    return redirect(url_for("login"))


def scheduled_sync():
    print(f"[scheduler] menjalankan sync otomatis {datetime.datetime.now().isoformat()}")
    try:
        updated, total = run_sync()
        sync_state.record("scheduled", len(updated), len(total))
    except Exception as exc:
        print(f"[scheduler] sync otomatis gagal: {exc}")
        sync_state.record("scheduled", 0, 0, error=str(exc))


@app.route("/", methods=["GET"])
@login_required
def index():
    members = member_store.list_members()
    state = sync_state.get()
    return render_template(
        "index.html",
        members=members,
        state=state,
        schedule_times=SCHEDULE_TIMES,
    )


@app.route("/pacer/connect", methods=["GET"])
@login_required
def pacer_connect():
    state = secrets.token_urlsafe(16)
    return redirect(get_authorization_url(state))


@app.route("/pacer/callback", methods=["GET"])
@login_required
def pacer_callback():
    auth_result = request.args.get("auth_result")
    code = request.args.get("code")

    is_prefetch = request.headers.get("Sec-Purpose", "").startswith("prefetch") or \
        request.headers.get("Purpose") == "prefetch"
    if is_prefetch:
        return "", 204

    if auth_result != "success":
        flash("Anggota membatalkan atau gagal otorisasi Pacer.", "error")
        return redirect(url_for("index"))

    try:
        token_data = exchange_code_for_token(code)
        user_id = token_data["user_id"]

        client = PacerClient(token_data["access_token"])
        user_info = client.get_user_info(user_id)
        # .get(key, default) tidak cukup: Pacer bisa balikin display_name="" (key ada,
        # nilai kosong) untuk user yang daftar via Apple SSO dengan nama disembunyikan
        # ("Hide My Email"), jadi default itu tidak pernah ke-trigger. Pakai `or` supaya
        # string kosong tetap fallback ke user_id.
        display_name = user_info.get("display_name") or user_id

        member_store.upsert_member(
            user_id=user_id,
            display_name=display_name,
            access_token=token_data["access_token"],
            refresh_token=token_data["refresh_token"],
            expires_in=token_data["expires_in"],
        )
        flash(f"Anggota '{display_name}' berhasil terhubung.", "success")
    except Exception as exc:
        flash(f"Gagal menghubungkan anggota: {exc}", "error")

    return redirect(url_for("index"))


@app.route("/sync", methods=["POST"])
@login_required
def sync():
    try:
        updated, total = run_sync()
        sync_state.record("manual", len(updated), len(total))
        flash(
            f"Sync berhasil: {len(updated)} baris diperbarui, {len(total)} baris total di Google Sheets.",
            "success",
        )
    except Exception as exc:
        sync_state.record("manual", 0, 0, error=str(exc))
        flash(f"Sync gagal: {exc}", "error")
    return redirect(url_for("index"))


@app.route("/sync/cron", methods=["POST", "GET"])
@csrf.exempt  # NOSONAR - aman: endpoint ini tidak memakai session cookie sama
# sekali (autentikasi via token X-Cron-Token yang dibandingkan dengan
# secrets.compare_digest), sehingga tidak rentan terhadap serangan CSRF yang
# mengeksploitasi cookie browser. Exempt ini disengaja, bukan kelalaian.
def sync_cron():
    """Endpoint khusus untuk cron eksternal (mis. cron-job.org), tanpa login/session.

    Autentikasi pakai token rahasia (CRON_SYNC_TOKEN), dikirim via:
    - header 'X-Cron-Token: <token>', atau
    - query/body param '?token=<token>'
    """
    expected = config.CRON_SYNC_TOKEN
    if not expected:
        return jsonify({"ok": False, "error": "CRON_SYNC_TOKEN belum diset di server"}), 503

    provided = request.headers.get("X-Cron-Token") or request.values.get("token") or ""
    if not secrets.compare_digest(provided, expected):
        return jsonify({"ok": False, "error": "token tidak valid"}), 401

    try:
        updated, total = run_sync()
        sync_state.record("cron", len(updated), len(total))
        return jsonify({
            "ok": True,
            "updated_count": len(updated),
            "total_count": len(total),
        })
    except Exception as exc:
        sync_state.record("cron", 0, 0, error=str(exc))
        return jsonify({"ok": False, "error": str(exc)}), 500


scheduler = BackgroundScheduler(timezone="Asia/Makassar")
scheduler.add_job(
    scheduled_sync,
    trigger=_schedule_trigger(SCHEDULE_TIMES),
    id="pacer_sync",
    replace_existing=True,
)
scheduler.start()


if __name__ == "__main__":
    app.run(debug=config.FLASK_DEBUG, use_reloader=False)
