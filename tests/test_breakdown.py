"""Checks for the /breakdown page and the Teller client.

Plain asserts, no pytest dependency. Run:  python tests/test_breakdown.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from budgetMe import budget, teller_api  # noqa: E402
from budgetMe.teller_api import TellerError  # noqa: E402

ACC_CHECKING = "acc_checking_001"
ACC_CARD = "acc_card_002"

ACCOUNTS = [
    {
        "id": ACC_CHECKING,
        "enrollment_id": "enr_1",
        "name": "Everyday Checking",
        "type": "depository",
        "subtype": "checking",
        "currency": "USD",
        "last_four": "1234",
        "status": "open",
        "institution": {"id": "first_national", "name": "First National"},
        "links": {
            "self": f"https://api.teller.io/accounts/{ACC_CHECKING}",
            "balances": f"https://api.teller.io/accounts/{ACC_CHECKING}/balances",
            "transactions": f"https://api.teller.io/accounts/{ACC_CHECKING}/transactions",
        },
    },
    {
        "id": ACC_CARD,
        "enrollment_id": "enr_1",
        "name": "Platinum Card",
        "type": "credit",
        "subtype": "credit_card",
        "currency": "USD",
        "last_four": "7857",
        "status": "open",
        "institution": {"id": "security_cu", "name": "Security Credit Union"},
        "links": {
            "self": f"https://api.teller.io/accounts/{ACC_CARD}",
            "balances": f"https://api.teller.io/accounts/{ACC_CARD}/balances",
            "transactions": f"https://api.teller.io/accounts/{ACC_CARD}/transactions",
        },
    },
]

BALANCES = {
    ACC_CHECKING: {"account_id": ACC_CHECKING, "available": "1543.20", "ledger": "1600.00"},
    ACC_CARD: {"account_id": ACC_CARD, "available": None, "ledger": "-284.19"},
}

TRANSACTIONS = {
    ACC_CHECKING: [
        {
            "id": "txn_a",
            "date": "2024-03-02",
            "description": "Trader Joe's",
            "amount": "-64.31",
            "type": "card_payment",
            "status": "posted",
            "running_balance": "1543.20",
            "details": {"category": "groceries", "counterparty": {"name": "TRADER JOES", "type": "organization"}},
        },
        {
            "id": "txn_b",
            "date": "2024-03-01",
            "description": "Payroll ACME Corp",
            "amount": "2200.00",
            "type": "ach",
            "status": "posted",
            "running_balance": "1607.51",
            "details": {"category": "income", "counterparty": {"name": "ACME CORP", "type": "organization"}},
        },
        {
            "id": "txn_c",
            "date": "2024-03-03",
            "description": "Pending coffee",
            "amount": "-5.75",
            "type": "card_payment",
            "status": "pending",
            "running_balance": None,
            "details": {"category": None, "counterparty": None},
        },
    ],
    ACC_CARD: [],
}


def fake_teller_get(url, access_token):
    if url.endswith("/accounts"):
        return ACCOUNTS
    for acc_id in (ACC_CHECKING, ACC_CARD):
        if url.endswith(f"/accounts/{acc_id}/balances"):
            return BALANCES[acc_id]
        if url.endswith(f"/accounts/{acc_id}/transactions"):
            return TRANSACTIONS[acc_id]
    raise AssertionError(f"unexpected URL: {url}")


def make_client(monkeypatched_get=fake_teller_get, token="token_test"):
    teller_api.teller_get = monkeypatched_get
    budget.app.config.update(TESTING=True)
    client = budget.app.test_client()
    if token is not None:
        with client.session_transaction() as sess:
            sess["access_token"] = token
    return client


def check(name, cond):
    if not cond:
        raise AssertionError(f"FAILED: {name}")
    print(f"  ok  {name}")


def test_renders_real_data():
    client = make_client()
    html = client.get("/breakdown").get_data(as_text=True)
    check("status 200", client.get("/breakdown").status_code == 200)
    check("shows checking institution", "First National" in html)
    check("shows card institution", "Security Credit Union" in html)
    check("formats available balance", "$1,543.20" in html)
    check("null available renders as dash", "—" in html)
    check("negative ledger formatted", "-$284.19" in html)
    check("transaction description shown", "Trader Joe&#39;s" in html or "Trader Joe's" in html)
    check("negative amount styled + formatted", 'class="amount neg"' in html and "-$64.31" in html)
    check("positive amount styled", 'class="amount pos"' in html and "$2,200.00" in html)
    check("pending tag", "pending-tag" in html)
    check("category title-cased", "Groceries" in html)
    check("empty account shows empty row", "No transactions for this account." in html)
    check("no fake data left", "$5,000" not in html and "Savings Goals" not in html)
    check("coming-soon note", "coming soon" in html)


def test_no_token_redirects():
    client = make_client(token=None)
    r = client.get("/breakdown")
    check("no token -> 302", r.status_code == 302)
    check("redirects to /login", "/login" in r.headers["Location"])


def test_expired_token_shows_error_and_clears_session():
    def boom(url, access_token):
        raise TellerError(status=403, code="enrollment.disconnected.credentials_invalid", message="bad token")

    client = make_client(boom)
    r = client.get("/breakdown")
    html = r.get_data(as_text=True)
    check("403 -> 200 with error card", r.status_code == 200 and "error-card" in html)
    check("error names the Teller code", "enrollment.disconnected.credentials_invalid" in html)
    check("error card offers reconnect", "Connect a bank" in html)
    with client.session_transaction() as sess:
        check("session token cleared", "access_token" not in sess)


def test_network_error_shows_error_card():
    def boom(url, access_token):
        raise TellerError(
            status=None,
            message="Couldn't reach Teller. Check your connection and try again.",
        )

    client = make_client(boom)
    r = client.get("/breakdown")
    html = r.get_data(as_text=True)
    check("network error -> 200", r.status_code == 200)
    check("error card rendered", "error-card" in html and "Couldn&#39;t reach Teller" in html)


def test_all_routes_still_ok():
    client = make_client()
    for path in ["/", "/advice", "/login", "/logout", "/account", "/settings", "/analysis", "/createAccount"]:
        code = client.get(path).status_code
        check(f"{path} -> {code}", code in (200, 302))


def main():
    orig = teller_api.teller_get
    try:
        for fn in [
            test_renders_real_data,
            test_no_token_redirects,
            test_expired_token_shows_error_and_clears_session,
            test_network_error_shows_error_card,
            test_all_routes_still_ok,
        ]:
            print(fn.__name__)
            fn()
    finally:
        teller_api.teller_get = orig
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
