"""BudgetMe - Flask app that pulls bank data from the Teller API.

Live data path: Teller Connect (browser) -> POST /login -> session token ->
GET /breakdown renders every account, its balances and recent transactions
(see budgetMe/teller_api.py). Other pages are still static mockups; see
README.md for feature status.
"""
import os

from dotenv import load_dotenv
from flask import (
    Flask,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from budgetMe.teller_api import TellerError, format_money, get_overview

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

TELLER_APP_ID = os.environ.get("TELLER_APP_ID", "app_p4epsc4h1j499fkuv0000")
TELLER_ENV = os.environ.get("TELLER_ENV", "sandbox")


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
        access_token = payload.get("accessToken")
        if not access_token:
            return {"error": "accessToken missing"}, 400
        session["access_token"] = access_token
        return {"ok": True, "redirect": url_for("breakdown")}
    return render_template(
        "login.html",
        title="Login - BudgetMe",
        teller_app_id=TELLER_APP_ID,
        teller_env=TELLER_ENV,
    )


@app.route("/logout")
def logout():
    session.pop("access_token", None)
    return redirect(url_for("home"))


@app.route("/breakdown")
def breakdown():
    access_token = session.get("access_token")
    if not access_token:
        return redirect(url_for("login"))

    try:
        accounts = get_overview(access_token)
    except TellerError as exc:
        app.logger.warning("Teller error on /breakdown: status=%s code=%s", exc.status, exc.code)
        if exc.status in (401, 403, 404):
            # Token is no longer usable - drop it so "Connect a bank" starts fresh.
            session.pop("access_token", None)
            detail = f" (Teller: {exc.code})" if exc.code else ""
            error = (
                "Your bank connection isn't working anymore - connect again to "
                f"refresh it.{detail}"
            )
        else:
            error = exc.message or "Couldn't reach Teller. Please try again."
        return render_template(
            "breakdown.html",
            title="My Breakdown - BudgetMe",
            accounts=[],
            error=error,
        )

    return render_template(
        "breakdown.html",
        title="My Breakdown - BudgetMe",
        accounts=accounts,
        error=None,
    )


@app.route("/advice")
def advice():
    return render_template("advice.html", title="Financial Advice - BudgetMe")


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
