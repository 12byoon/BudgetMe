"""Standalone Plaid sandbox probe - no browser needed.

Uses /sandbox/public_token/create to mint an access token for a sandbox
institution, then dumps the accounts and recent transactions. This is the
fastest way to confirm your Plaid keys work and to see the real response shape.

Requires PLAID_CLIENT_ID / PLAID_SECRET in .env (sandbox secret).

Usage:  python plaid_probe.py
"""
import json
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
        access_token = plaid_api.exchange_public_token(pub["public_token"])
        print(f"access_token: {access_token}\n")

        overview = plaid_api.get_overview(access_token, institution_name="First Platypus Bank")
    except plaid_api.PlaidError as exc:
        print(f"Plaid error: status={exc.status} code={exc.code} - {exc.message}")
        return 1

    for entry in overview:
        acc = entry["account"]
        print(f"{acc['name']} (••{acc['mask']}, {acc['type']}/{acc['subtype']})")
        print(f"  available: {plaid_api.format_money(entry['available'])}"
              f"   current: {plaid_api.format_money(entry['current'])}")
        for t in entry["transactions"][:10]:
            tag = " [pending]" if t["pending"] else ""
            print(f"  {t['date']}  {plaid_api.format_money(t['amount']):>12}  "
                  f"{(t['category'] or '-'):<22}  {t['name']}{tag}")
        print()

    print("--- raw /accounts/get ---")
    print(json.dumps(plaid_api._post("/accounts/get", access_token=access_token), indent=2)[:2000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
