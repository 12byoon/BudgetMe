"""BudgetMe - Flask app that pulls bank data from Plaid.

Live data path: Plaid Link (browser) -> POST /login exchanges the public token
for an access token stored in the session -> GET /breakdown renders every linked
account with its balances and recent transactions (see budgetMe/plaid_api.py).
Other feature pages are still static mockups; see README.md.
"""
import os
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

from budgetMe.plaid_api import (
    PlaidError,
    create_link_token,
    exchange_public_token,
    format_money,
    get_overview,
)

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

_RELINK_CODES = ("ITEM_LOGIN_REQUIRED", "INVALID_ACCESS_TOKEN")


@app.template_filter("money")
def _money(value):
    return format_money(value)


@app.route("/")
def home():
    return render_template("index.html", title="BudgetMe")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        payload = request.get_json(silent=True) or {}
        public_token = payload.get("public_token")
        if not public_token:
            return {"error": "public_token missing"}, 400
        try:
            access_token = exchange_public_token(public_token)
        except PlaidError as exc:
            return {"error": exc.message}, 400
        session["access_token"] = access_token
        session["institution_name"] = payload.get("institution_name")
        return {"ok": True, "redirect": url_for("breakdown")}

    user_id = session.setdefault("plaid_user_id", uuid4().hex)
    link_token = link_error = None
    try:
        link_token = create_link_token(user_id)
    except PlaidError:
        link_error = (
            "Couldn't start the bank link. Make sure PLAID_CLIENT_ID and "
            "PLAID_SECRET are set in .env, then reload."
        )
    return render_template(
        "login.html",
        title="Login - BudgetMe",
        link_token=link_token,
        link_error=link_error,
    )


@app.route("/logout")
def logout():
    session.pop("access_token", None)
    session.pop("institution_name", None)
    return redirect(url_for("home"))


@app.route("/breakdown")
def breakdown():
    access_token = session.get("access_token")
    if not access_token:
        return redirect(url_for("login"))

    try:
        accounts = get_overview(access_token, session.get("institution_name"))
    except PlaidError as exc:
        app.logger.warning("Plaid error on /breakdown: status=%s code=%s", exc.status, exc.code)
        if exc.code in _RELINK_CODES:
            session.pop("access_token", None)
            session.pop("institution_name", None)
            error = f"Your bank connection needs to be re-linked - connect again. (Plaid: {exc.code})"
        elif exc.code == "INVALID_API_KEYS":
            error = "Plaid rejected the API keys - check PLAID_CLIENT_ID / PLAID_SECRET in .env."
        else:
            error = exc.message or "Couldn't load your accounts. Please try again."
        return render_template(
            "breakdown.html", title="My Breakdown - BudgetMe", accounts=[], error=error
        )

    return render_template(
        "breakdown.html", title="My Breakdown - BudgetMe", accounts=accounts, error=None
    )


# --- Placeholder pages -------------------------------------------------------
# These render styled pages so the nav/dropdown links resolve. None of them
# have a backend yet; forms and controls are inert scaffolding.


@app.route("/account")
def account():
    return render_template("account.html", title="Account - BudgetMe")


@app.route("/settings")
def settings():
    return render_template("settings.html", title="Settings - BudgetMe")


@app.route("/analysis")
def analysis():
    return render_template("analysis.html", title="Analysis - BudgetMe")


@app.route("/createAccount", methods=["GET", "POST"])
def create_account():
    # No auth backend yet - a POST just re-renders the page.
    return render_template("createAccount.html", title="Create Account - BudgetMe")
