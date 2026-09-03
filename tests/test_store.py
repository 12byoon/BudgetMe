"""Checks for budgetMe.store (the SQLite data layer).

Plain asserts, no pytest. Run:  python tests/test_store.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from budgetMe import store  # noqa: E402


def check(name, cond):
    if not cond:
        raise AssertionError(f"FAILED: {name}")
    print(f"  ok  {name}")


def fresh_db():
    path = Path(tempfile.mkdtemp()) / "t.db"
    store.init_db(str(path))
    return path


ACC = {
    "account_id": "acc1", "name": "Checking", "official_name": "Big Checking",
    "mask": "0000", "type": "depository", "subtype": "checking",
    "available": 100.0, "current": 110.0, "currency": "USD",
}
TXN = {
    "transaction_id": "t1", "account_id": "acc1", "date": "2026-08-01",
    "name": "Coffee", "merchant_name": "Cafe", "amount": -4.50, "pending": 0,
    "category": "Food and drink",
}


def test_connection_crud_and_upsert():
    fresh_db()
    cid = store.add_connection("item_a", "tok_1", "First Bank")
    check("add returns id", isinstance(cid, int))
    check("one connection", len(store.list_connections()) == 1)

    same = store.add_connection("item_a", "tok_2", "First Bank")
    check("upsert on item_id keeps one row", same == cid and len(store.list_connections()) == 1)
    check("upsert refreshed token", store.get_connection(cid)["access_token"] == "tok_2")

    store.add_connection("item_b", "tok_3", "Second Bank")
    check("second bank -> two rows", len(store.list_connections()) == 2)


def test_accounts_and_transactions():
    fresh_db()
    cid = store.add_connection("item_a", "tok", "First Bank")
    store.upsert_accounts(cid, [ACC])
    store.apply_transactions(cid, [TXN], [], [])

    rows = store.accounts_with_transactions()
    check("one account entry", len(rows) == 1)
    check("institution joined in", rows[0]["institution_name"] == "First Bank")
    check("balance carried", rows[0]["current"] == 110.0)
    check("txn attached", rows[0]["transactions"][0]["name"] == "Coffee")

    # modify
    store.apply_transactions(cid, [], [{**TXN, "amount": -9.0}], [])
    check("modify updates in place",
          store.accounts_with_transactions()[0]["transactions"][0]["amount"] == -9.0)
    check("still one txn", len(store.all_transactions()) == 1)

    # remove
    store.apply_transactions(cid, [], [], ["t1"])
    check("remove deletes txn", store.all_transactions() == [])

    # account upsert
    store.upsert_accounts(cid, [{**ACC, "current": 200.0}])
    check("account upsert updates", store.accounts_with_transactions()[0]["current"] == 200.0)


def test_cascade_delete():
    fresh_db()
    cid = store.add_connection("item_a", "tok", "First Bank")
    store.upsert_accounts(cid, [ACC])
    store.apply_transactions(cid, [TXN], [], [])
    store.delete_connection(cid)
    check("connection gone", store.list_connections() == [])
    check("accounts cascaded", store.accounts_with_transactions() == [])
    check("txns cascaded", store.all_transactions() == [])


def test_status_and_summaries():
    fresh_db()
    cid = store.add_connection("item_a", "tok", "First Bank")
    store.upsert_accounts(cid, [ACC])
    store.set_cursor(cid, "cur_123")
    store.set_synced_now(cid)
    store.set_status(cid, "needs_relink", "ITEM_LOGIN_REQUIRED")

    conn = store.get_connection(cid)
    check("cursor saved", conn["cursor"] == "cur_123")
    check("synced timestamp set", conn["last_synced_at"] is not None)
    check("status saved", conn["status"] == "needs_relink")

    s = store.connection_summaries()[0]
    check("summary account count", s["account_count"] == 1)
    check("summary carries status", s["status"] == "needs_relink")


def main():
    for fn in (
        test_connection_crud_and_upsert,
        test_accounts_and_transactions,
        test_cascade_delete,
        test_status_and_summaries,
    ):
        print(fn.__name__)
        fn()
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
