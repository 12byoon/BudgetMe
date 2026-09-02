"""BudgetMe - Flask app that pulls bank data from the Teller API.

Most pages are still static mockups; see README.md for feature status. The only
live data path today is: Teller Connect (browser) -> POST /login -> session token
-> GET /breakdown fetches the account balance.
"""
import os

import requests
from dotenv import load_dotenv
from flask import (
    Flask,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

TELLER_API = "https://api.teller.io"
TELLER_APP_ID = os.environ.get("TELLER_APP_ID", "app_p4epsc4h1j499fkuv0000")
TELLER_ENV = os.environ.get("TELLER_ENV", "sandbox")


def teller_get(url, access_token):
    """GET a Teller API URL using the enrollment access token.

    Teller uses HTTP basic auth with the access token as the username and an
    empty password. Returns parsed JSON (a dict or a list, depending on the
    endpoint).
    """
    resp = requests.get(url, auth=(access_token, ""), timeout=30)
    resp.raise_for_status()
    return resp.json()


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

    accounts = teller_get(f"{TELLER_API}/accounts", access_token)
    account = accounts[0] if isinstance(accounts, list) and accounts else {}
    links = account.get("links", {})

    balances = {}
    transactions = []
    if links.get("balances"):
        balances = teller_get(links["balances"], access_token)
    if links.get("transactions"):
        transactions = teller_get(links["transactions"], access_token)

    return render_template(
        "breakdown.html",
        title="My Breakdown - BudgetMe",
        institution=(account.get("institution") or {}).get("name"),
        currency=account.get("currency"),
        balance=balances.get("available"),
        transactions=transactions,
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
