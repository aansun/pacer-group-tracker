import datetime
import functools
import secrets

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger
from flask import Flask, render_template, redirect, url_for, flash, request, session

import config
from services import member_store, sync_state
from services.pacer_client import get_authorization_url, exchange_code_for_token, PacerClient
from sync import run_sync

app = Flask(__name__)
app.secret_key = config.FLASK_SECRET_KEY

SCHEDULE_TIMES = ["08:00", "12:00", "15:00", "21:00", "23:55"]


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
            return redirect(request.args.get("next") or url_for("index"))
        flash("Username atau password salah.", "error")
    return render_template("login.html")


@app.route("/logout")
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


@app.route("/")
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


@app.route("/pacer/connect")
@login_required
def pacer_connect():
    state = secrets.token_urlsafe(16)
    return redirect(get_authorization_url(state))


@app.route("/pacer/callback")
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

        member_store.upsert_member(
            user_id=user_id,
            display_name=user_info.get("display_name", user_id),
            access_token=token_data["access_token"],
            refresh_token=token_data["refresh_token"],
            expires_in=token_data["expires_in"],
        )
        flash(f"Anggota '{user_info.get('display_name', user_id)}' berhasil terhubung.", "success")
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


scheduler = BackgroundScheduler(timezone="Asia/Makassar")
scheduler.add_job(
    scheduled_sync,
    trigger=_schedule_trigger(SCHEDULE_TIMES),
    id="pacer_sync",
    replace_existing=True,
)
scheduler.start()


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
