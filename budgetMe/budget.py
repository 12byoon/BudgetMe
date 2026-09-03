"""BudgetMe - a local personal dashboard for bank data from Plaid.

Flow: Plaid Link (browser) -> POST /login exchanges the public token and does an
initial sync -> everything is stored in a local SQLite database
(instance/budgetme.db) -> /breakdown and /analysis serve from that store ->
POST /sync pulls only new/changed transactions from Plaid.

See budgetMe/store.py (data layer), budgetMe/plaid_api.py (Plaid client),
budgetMe/analytics.py (spending math).
"""
import os
from datetime import datetime, timezone
from uuid import uuid4

from dotenv import load_dotenv
from flask import (
    Flask,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from budgetMe import analytics, plaid_api, store
from budgetMe.plaid_api import PlaidError

load_dotenv()

app = Flask(__name__)

_DEBUG = os.environ.get("FLASK_DEBUG", "1") == "1"
_secret = os.environ.get("SECRET_KEY")
if not _secret:
    if _DEBUG:
        _secret = "dev-only-insecure-key"
        app.logger.warning("SECRET_KEY not set - using an insecure development key.")
    else:
        raise RuntimeError("SECRET_KEY must be set when FLASK_DEBUG is off.")
app.secret_key = _secret

store.init_db(os.environ.get("BUDGETME_DB") or os.path.join(app.instance_path, "budgetme.db"))

_RELINK_CODES = ("ITEM_LOGIN_REQUIRED", "INVALID_ACCESS_TOKEN")


@app.template_filter("money")
def _money(value):
    return plaid_api.format_money(value)


@app.template_filter("monthlabel")
def _monthlabel(ym):
    """'2026-08' -> 'Aug 2026'."""
    try:
        return datetime.strptime(ym, "%Y-%m").strftime("%b %Y")
    except (ValueError, TypeError):
        return ym


@app.template_filter("ago")
def _ago(iso_ts):
    """'2026-09-02T20:15:00+00:00' -> 'a few seconds ago' / '5 minutes ago' / ..."""
    if not iso_ts:
        return ""
    try:
        then = datetime.fromisoformat(iso_ts)
    except ValueError:
        return iso_ts
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    secs = (datetime.now(timezone.utc) - then).total_seconds()
    if secs < 60:
        return "a few seconds ago"
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        n = int(secs // size)
        if n:
            return f"{n} {unit}{'s' if n != 1 else ''} ago"
    return "just now"


def sync_connection(connection_id):
    """Refresh one connection's accounts + transactions from Plaid.

    Records the outcome on the connection row and never re-raises, so one broken
    bank doesn't stop the others.
    """
    conn = store.get_connection(connection_id)
    if not conn:
        return
    try:
        accounts = plaid_api.fetch_accounts(conn["access_token"])
        store.upsert_accounts(connection_id, [plaid_api.shape_account(a) for a in accounts])

        added, modified, removed, cursor, _ready = plaid_api.sync_transactions(
            conn["access_token"], conn["cursor"]
        )
        store.apply_transactions(
            connection_id,
            [plaid_api.shape_transaction(t) for t in added],
            [plaid_api.shape_transaction(t) for t in modified],
            removed,
        )
        store.set_cursor(connection_id, cursor)
        store.set_synced_now(connection_id)
        store.set_status(connection_id, "ok")
    except PlaidError as exc:
        app.logger.warning(
            "sync failed for connection %s: %s %s", connection_id, exc.status, exc.code
        )
        if exc.code in _RELINK_CODES:
            store.set_status(connection_id, "needs_relink", exc.code)
        else:
            store.set_status(connection_id, "error", exc.message)


@app.route("/")
def home():
    return redirect(url_for("breakdown"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        payload = request.get_json(silent=True) or {}
        public_token = payload.get("public_token")
        if not public_token:
            return {"error": "public_token missing"}, 400
        try:
            access_token, item_id = plaid_api.exchange_public_token(public_token)
        except PlaidError as exc:
            return {"error": exc.message}, 400
        connection_id = store.add_connection(
            item_id, access_token, payload.get("institution_name")
        )
        sync_connection(connection_id)
        return {"ok": True, "redirect": url_for("breakdown")}

    user_id = session.setdefault("plaid_user_id", uuid4().hex)
    link_token = link_error = None
    try:
        link_token = plaid_api.create_link_token(user_id)
    except PlaidError:
        link_error = (
            "Couldn't start the bank link. Make sure PLAID_CLIENT_ID and "
            "PLAID_SECRET are set in .env, then reload."
        )
    return render_template(
        "login.html",
        title="Connect a bank - BudgetMe",
        link_token=link_token,
        link_error=link_error,
        has_connections=bool(store.list_connections()),
    )


@app.route("/breakdown")
def breakdown():
    if not store.list_connections():
        return redirect(url_for("login"))
    return render_template(
        "breakdown.html",
        title="My Breakdown - BudgetMe",
        accounts=store.accounts_with_transactions(),
        summary=analytics.summary(store.all_transactions()),
        connections=store.connection_summaries(),
    )


@app.route("/sync", methods=["POST"])
def sync():
    for conn in store.list_connections():
        sync_connection(conn["id"])
    return redirect(url_for("breakdown"))


@app.route("/analysis")
def analysis():
    if not store.list_connections():
        return redirect(url_for("login"))
    return render_template(
        "analysis.html",
        title="Analysis - BudgetMe",
        report=analytics.report(store.all_transactions()),
    )


@app.route("/connections")
def connections():
    return render_template(
        "connections.html",
        title="Connections - BudgetMe",
        connections=store.connection_summaries(),
    )


@app.route("/connections/<int:connection_id>/delete", methods=["POST"])
def disconnect(connection_id):
    store.delete_connection(connection_id)
    if store.list_connections():
        return redirect(url_for("connections"))
    return redirect(url_for("login"))
