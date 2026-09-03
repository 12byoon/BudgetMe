"""Standalone Plaid sandbox probe - no browser, no database.

Mints an access token for a sandbox institution via /sandbox/public_token/create,
then prints its accounts and recent transactions. The fastest way to confirm
your Plaid keys work and to see the real response shape.

Requires PLAID_CLIENT_ID / PLAID_SECRET in .env (sandbox secret).

Usage:  python plaid_probe.py
"""
import sys

from dotenv import load_dotenv

load_dotenv()

from budgetMe import plaid_api  # noqa: E402

INSTITUTION_ID = "ins_109508"  # First Platypus Bank (non-OAuth sandbox)


def main():
    if not plaid_api._credentials()["client_id"]:
        print("PLAID_CLIENT_ID / PLAID_SECRET are not set in .env")
        return 1

    try:
        pub = plaid_api._post(
            "/sandbox/public_token/create",
            institution_id=INSTITUTION_ID,
            initial_products=["transactions"],
        )
        access_token, item_id = plaid_api.exchange_public_token(pub["public_token"])
        print(f"item_id: {item_id}")
        print(f"access_token: {access_token}\n")

        accounts = [plaid_api.shape_account(a) for a in plaid_api.fetch_accounts(access_token)]
        added, modified, removed, cursor, is_ready = plaid_api.sync_transactions(access_token)
    except plaid_api.PlaidError as exc:
        print(f"Plaid error: status={exc.status} code={exc.code} - {exc.message}")
        return 1

    txns = [plaid_api.shape_transaction(t) for t in added]
    by_account = {}
    for t in txns:
        by_account.setdefault(t["account_id"], []).append(t)

    print(f"transactions ready: {is_ready}  ({len(txns)} added)\n")
    for acc in accounts:
        print(f"{acc['name']} (••{acc['mask']}, {acc['type']}/{acc['subtype']})")
        print(f"  available: {plaid_api.format_money(acc['available'])}"
              f"   current: {plaid_api.format_money(acc['current'])}")
        for t in sorted(by_account.get(acc["account_id"], []),
                        key=lambda x: x["date"] or "", reverse=True)[:10]:
            tag = " [pending]" if t["pending"] else ""
            print(f"  {t['date']}  {plaid_api.format_money(t['amount']):>12}  "
                  f"{(t['category'] or '-'):<22}  {t['name']}{tag}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
