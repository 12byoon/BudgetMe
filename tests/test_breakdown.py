"""Checks for the /breakdown page and the Plaid client.

Plain asserts, no pytest dependency. Run:  python tests/test_breakdown.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from budgetMe import budget, plaid_api  # noqa: E402
from budgetMe.plaid_api import PlaidError  # noqa: E402

ACC_CHECKING = "acc_checking_001"
ACC_CARD = "acc_card_002"

ACCOUNTS = [
    {
        "account_id": ACC_CHECKING,
        "name": "Plaid Checking",
        "official_name": "Plaid Gold Standard 0% Interest Checking",
        "mask": "0000",
        "type": "depository",
        "subtype": "checking",
        "balances": {"available": 1543.2, "current": 1600.0, "iso_currency_code": "USD", "limit": None},
    },
    {
        "account_id": ACC_CARD,
        "name": "Plaid Credit Card",
        "official_name": "Plaid Diamond 12.5% APR Interest Credit Card",
        "mask": "3333",
        "type": "credit",
        "subtype": "credit card",
        "balances": {"available": None, "current": 284.19, "iso_currency_code": "USD", "limit": 2000},
    },
]

# Plaid sign convention: + = money out, - = money in.
TXNS_ADDED = [
    {
        "transaction_id": "txn_a",
        "account_id": ACC_CHECKING,
        "date": "2024-03-02",
        "name": "PURCHASE WM SUPERCENTER #1700",
        "merchant_name": "Walmart",
        "amount": 64.31,
        "pending": False,
        "personal_finance_category": {"primary": "GENERAL_MERCHANDISE", "detailed": "GENERAL_MERCHANDISE_SUPERSTORES"},
    },
    {
        "transaction_id": "txn_b",
        "account_id": ACC_CHECKING,
        "date": "2024-03-01",
        "name": "ACME CORP DIRECT DEP",
        "merchant_name": None,
        "amount": -2200.00,
        "pending": False,
        "personal_finance_category": {"primary": "INCOME", "detailed": "INCOME_WAGES"},
    },
    {
        "transaction_id": "txn_c",
        "account_id": ACC_CHECKING,
        "date": "2024-03-03",
        "name": "STARBUCKS",
        "merchant_name": "Starbucks",
        "amount": 5.75,
        "pending": True,
        "personal_finance_category": {"primary": "FOOD_AND_DRINK", "detailed": "FOOD_AND_DRINK_COFFEE"},
    },
]


def fake_post(path, **body):
    if path == "/link/token/create":
        return {"link_token": "link-sandbox-test", "expiration": "2099-01-01T00:00:00Z", "request_id": "r"}
    if path == "/item/public_token/exchange":
        return {"access_token": "access-sandbox-test", "item_id": "item-test", "request_id": "r"}
    if path == "/accounts/get":
        return {"accounts": ACCOUNTS, "item": {}, "request_id": "r"}
    if path == "/transactions/sync":
        return {
            "added": TXNS_ADDED,
            "modified": [],
            "removed": [],
            "next_cursor": "cursor-done",
            "has_more": False,
            "transactions_update_status": "HISTORICAL_UPDATE_COMPLETE",
            "accounts": ACCOUNTS,
            "request_id": "r",
        }
    raise AssertionError(f"unexpected Plaid path: {path}")


def make_client(post=fake_post, token="access-sandbox-test"):
    plaid_api._post = post
    budget.app.config.update(TESTING=True)
    client = budget.app.test_client()
    if token is not None:
        with client.session_transaction() as sess:
            sess["access_token"] = token
            sess["institution_name"] = "First Platypus Bank"
    return client


def check(name, cond):
    if not cond:
        raise AssertionError(f"FAILED: {name}")
    print(f"  ok  {name}")


def test_renders_real_data():
    client = make_client()
    html = client.get("/breakdown").get_data(as_text=True)
    check("status 200", client.get("/breakdown").status_code == 200)
    check("institution name shown", "First Platypus Bank" in html)
    check("checking account name", "Plaid Checking" in html)
    check("credit account name", "Plaid Credit Card" in html)
    check("available balance formatted", "$1,543.20" in html)
    check("current balance formatted", "$1,600.00" in html)
    check("null available renders as dash", "—" in html)
    check("purchase flipped to negative + styled", 'class="amount neg"' in html and "-$64.31" in html)
    check("paycheck flipped to positive + styled", 'class="amount pos"' in html and "$2,200.00" in html)
    check("pending tag", "pending-tag" in html and "STARBUCKS" in html)
    check("PFC category humanized", "General merchandise" in html)
    check("empty account row", "No transactions for this account yet." in html)
    check("no fake data left", "$5,000" not in html and "Savings Goals" not in html)
    check("coming-soon note", "coming soon" in html)


def test_no_token_redirects():
    client = make_client(token=None)
    r = client.get("/breakdown")
    check("no token -> 302", r.status_code == 302)
    check("redirects to /login", "/login" in r.headers["Location"])


def test_relink_shows_error_and_clears_session():
    def boom(path, **body):
        if path == "/link/token/create":
            return fake_post(path, **body)
        raise PlaidError(status=400, code="ITEM_LOGIN_REQUIRED", message="login required")

    client = make_client(boom)
    r = client.get("/breakdown")
    html = r.get_data(as_text=True)
    check("relink -> 200 with error card", r.status_code == 200 and "error-card" in html)
    check("error names the Plaid code", "ITEM_LOGIN_REQUIRED" in html)
    check("error card offers reconnect", "Connect a bank" in html)
    with client.session_transaction() as sess:
        check("session token cleared", "access_token" not in sess)


def test_network_error_shows_error_card():
    def boom(path, **body):
        if path == "/link/token/create":
            return fake_post(path, **body)
        raise PlaidError(status=None, message="Couldn't reach Plaid. Check your connection and try again.")

    client = make_client(boom)
    r = client.get("/breakdown")
    html = r.get_data(as_text=True)
    check("network error -> 200", r.status_code == 200)
    check("error card rendered", "error-card" in html and "Couldn&#39;t reach Plaid" in html)


def test_login_shows_link_error_without_keys():
    def no_keys(path, **body):
        raise PlaidError(status=400, code="INVALID_API_KEYS", message="invalid keys")

    client = make_client(no_keys, token=None)
    html = client.get("/login").get_data(as_text=True)
    check("login renders 200", client.get("/login").status_code == 200)
    check("shows setup hint", "PLAID_CLIENT_ID" in html)
    check("link button disabled", "disabled" in html)


def test_all_routes_ok():
    client = make_client()
    for path in ["/", "/advice", "/login", "/logout", "/account", "/settings", "/analysis", "/createAccount"]:
        code = client.get(path).status_code
        check(f"{path} -> {code}", code in (200, 302))


def main():
    original = plaid_api._post
    try:
        for fn in [
            test_renders_real_data,
            test_no_token_redirects,
            test_relink_shows_error_and_clears_session,
            test_network_error_shows_error_card,
            test_login_shows_link_error_without_keys,
            test_all_routes_ok,
        ]:
            print(fn.__name__)
            fn()
    finally:
        plaid_api._post = original
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
