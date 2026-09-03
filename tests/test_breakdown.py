"""End-to-end route checks for BudgetMe (store-backed).

Plain asserts, no pytest. Run:  python tests/test_breakdown.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Point the app's store at a throwaway DB before importing it.
os.environ["BUDGETME_DB"] = str(Path(tempfile.mkdtemp()) / "test.db")

from budgetMe import budget, plaid_api, store  # noqa: E402
from budgetMe.plaid_api import PlaidError  # noqa: E402

ACC_CHECKING = {
    "account_id": "acc_chk", "name": "Plaid Checking", "official_name": "Gold Checking",
    "mask": "0000", "type": "depository", "subtype": "checking",
    "available": 1543.20, "current": 1600.00, "currency": "USD",
}
ACC_CARD = {
    "account_id": "acc_crd", "name": "Plaid Credit Card", "official_name": "Diamond Card",
    "mask": "3333", "type": "credit", "subtype": "credit card",
    "available": None, "current": 284.19, "currency": "USD",
}
TXNS = [
    {"transaction_id": "t1", "account_id": "acc_chk", "date": "2026-08-02",
     "name": "WALMART", "merchant_name": "Walmart", "amount": -64.31, "pending": 0,
     "category": "General merchandise"},
    {"transaction_id": "t2", "account_id": "acc_chk", "date": "2026-08-01",
     "name": "ACME PAYROLL", "merchant_name": None, "amount": 2200.00, "pending": 0,
     "category": "Income"},
    {"transaction_id": "t3", "account_id": "acc_chk", "date": "2026-08-03",
     "name": "STARBUCKS", "merchant_name": "Starbucks", "amount": -5.75, "pending": 1,
     "category": "Food and drink"},
]

# Raw Plaid shapes for the /login + /sync paths (monkeypatched _post).
RAW_ACCOUNTS = [
    {"account_id": "acc_chk", "name": "Plaid Checking", "official_name": "Gold Checking",
     "mask": "0000", "type": "depository", "subtype": "checking",
     "balances": {"available": 1543.20, "current": 1600.00, "iso_currency_code": "USD"}},
]
RAW_TXNS = [
    {"transaction_id": "t1", "account_id": "acc_chk", "date": "2026-08-02", "name": "WALMART",
     "merchant_name": "Walmart", "amount": 64.31, "pending": False,
     "personal_finance_category": {"primary": "GENERAL_MERCHANDISE"}},
]


def raw_post(path, **body):
    if path == "/link/token/create":
        return {"link_token": "link-sandbox-test"}
    if path == "/item/public_token/exchange":
        return {"access_token": "access-test", "item_id": "item-test"}
    if path == "/accounts/get":
        return {"accounts": RAW_ACCOUNTS}
    if path == "/transactions/sync":
        return {"added": RAW_TXNS, "modified": [], "removed": [], "next_cursor": "cur1",
                "has_more": False, "transactions_update_status": "HISTORICAL_UPDATE_COMPLETE"}
    raise AssertionError(f"unexpected Plaid path: {path}")


def reset_db():
    store.init_db(os.environ["BUDGETME_DB"])
    with store._conn() as db:
        db.executescript("DELETE FROM txn; DELETE FROM account; DELETE FROM connection;")


def seed_full():
    reset_db()
    cid = store.add_connection("item-1", "access-test", "First Platypus Bank")
    store.upsert_accounts(cid, [ACC_CHECKING, ACC_CARD])
    store.apply_transactions(cid, TXNS, [], [])
    return cid


def client():
    budget.app.config.update(TESTING=True)
    return budget.app.test_client()


def check(name, cond):
    if not cond:
        raise AssertionError(f"FAILED: {name}")
    print(f"  ok  {name}")


def test_no_connections_redirects():
    reset_db()
    for path in ("/", "/breakdown", "/analysis"):
        r = client().get(path)
        check(f"{path} -> redirect", r.status_code == 302)
    check("root -> /breakdown", "/breakdown" in client().get("/").headers["Location"])
    check("breakdown -> /login", "/login" in client().get("/breakdown").headers["Location"])


def test_breakdown_renders_store_data():
    seed_full()
    html = client().get("/breakdown").get_data(as_text=True)
    check("both accounts", "Plaid Checking" in html and "Plaid Credit Card" in html)
    check("institution", "First Platypus Bank" in html)
    check("balance formatted", "$1,600.00" in html)
    check("null available dash", "—" in html)
    check("spend is red", 'class="amount neg"' in html and "-$64.31" in html)
    check("income is green", 'class="amount pos"' in html and "$2,200.00" in html)
    check("pending tag", "pending-tag" in html and "STARBUCKS" in html)
    check("category shown", "General merchandise" in html)
    check("30-day summary present", "Last 30 days" in html and "Sync now" in html)
    check("checking sorted before credit card",
          html.index("Plaid Checking") < html.index("Plaid Credit Card"))


def test_analysis_renders_report():
    seed_full()
    html = client().get("/analysis").get_data(as_text=True)
    check("analysis 200", client().get("/analysis").status_code == 200)
    check("category table", "General merchandise" in html and "Food and drink" in html)
    check("monthly section", "Monthly cash flow" in html)
    check("top merchants", "Walmart" in html)


def test_sync_updates_store():
    reset_db()
    store.add_connection("item-1", "access-test", "First Platypus Bank")
    plaid_api._post = raw_post
    try:
        r = client().post("/sync")
        check("sync redirects to breakdown",
              r.status_code == 302 and "/breakdown" in r.headers["Location"])
        check("accounts stored", len(store.accounts_with_transactions()) == 1)
        check("txn stored + sign flipped", store.all_transactions()[0]["amount"] == -64.31)
        check("cursor persisted", store.list_connections()[0]["cursor"] == "cur1")
    finally:
        plaid_api._post = raw_post  # leave a harmless stub; restored in main()


def test_login_post_creates_connection():
    reset_db()
    plaid_api._post = raw_post
    r = client().post("/login", json={"public_token": "public-x",
                                      "institution_name": "First Platypus Bank"})
    check("login post ok", r.get_json().get("ok") is True)
    check("connection created", len(store.list_connections()) == 1)
    check("initial sync ran", len(store.all_transactions()) == 1)


def test_relink_warning_but_others_render():
    cid = seed_full()
    store.set_status(cid, "needs_relink", "ITEM_LOGIN_REQUIRED")
    # add a healthy second bank
    cid2 = store.add_connection("item-2", "access-2", "Second Bank")
    store.upsert_accounts(
        cid2, [{**ACC_CHECKING, "account_id": "acc_2", "name": "Second Checking"}]
    )
    html = client().get("/breakdown").get_data(as_text=True)
    check("warning card for broken bank",
          "needs attention" in html and "First Platypus Bank" in html)
    check("healthy bank still renders", "Second Checking" in html)


def test_disconnect_removes_connection():
    cid = seed_full()
    r = client().post(f"/connections/{cid}/delete")
    check("disconnect redirects", r.status_code == 302)
    check("connection gone", store.list_connections() == [])
    check("data cascaded", store.all_transactions() == [])


def test_login_shows_error_without_keys():
    reset_db()
    def no_keys(path, **body):
        raise PlaidError(status=400, code="INVALID_API_KEYS", message="bad keys")
    plaid_api._post = no_keys
    html = client().get("/login").get_data(as_text=True)
    check("login 200", client().get("/login").status_code == 200)
    check("setup hint shown", "PLAID_CLIENT_ID" in html)
    check("button disabled", "disabled" in html)


def main():
    original = plaid_api._post
    try:
        for fn in (
            test_no_connections_redirects,
            test_breakdown_renders_store_data,
            test_analysis_renders_report,
            test_sync_updates_store,
            test_login_post_creates_connection,
            test_relink_warning_but_others_render,
            test_disconnect_removes_connection,
            test_login_shows_error_without_keys,
        ):
            print(fn.__name__)
            fn()
    finally:
        plaid_api._post = original
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
