"""Plaid API client.

All HTTP calls to Plaid live here so the Flask routes stay thin. Plaid
authenticates with `client_id` + `secret` in the JSON body of every request
(no client certificate). Sandbox base URL is https://sandbox.plaid.com.

Token dance:
  create_link_token(user_id)     -> link_token   (handed to Plaid Link in the browser)
  exchange_public_token(pub_tok) -> access_token (long-lived; store in the session)
  get_overview(access_token)     -> per-account balances + recent transactions
"""
import logging
import os
import time
from decimal import Decimal, InvalidOperation

import requests

log = logging.getLogger(__name__)

_HOSTS = {
    "sandbox": "https://sandbox.plaid.com",
    "production": "https://production.plaid.com",
}


def _base_url():
    return _HOSTS.get(os.environ.get("PLAID_ENV", "sandbox").lower(), _HOSTS["sandbox"])


def _credentials():
    return {
        "client_id": os.environ.get("PLAID_CLIENT_ID", ""),
        "secret": os.environ.get("PLAID_SECRET", ""),
    }


class PlaidError(Exception):
    """A Plaid API call failed.

    `status` is the HTTP status (None for a network-level failure). `code` is
    Plaid's `error_code`, e.g. "ITEM_LOGIN_REQUIRED", "INVALID_ACCESS_TOKEN",
    "INVALID_API_KEYS".
    """

    def __init__(self, status=None, code=None, error_type=None, message=None):
        self.status = status
        self.code = code
        self.error_type = error_type
        self.message = message or "Plaid request failed"
        super().__init__(self.message)


def _post(path, **body):
    """POST to a Plaid endpoint and return parsed JSON. Raises PlaidError."""
    try:
        resp = requests.post(
            f"{_base_url()}{path}", json={**_credentials(), **body}, timeout=30
        )
    except requests.RequestException as exc:
        log.warning("Plaid request failed: %s %s", path, exc)
        raise PlaidError(
            status=None,
            message="Couldn't reach Plaid. Check your connection and try again.",
        ) from exc

    if resp.status_code >= 400:
        data = {}
        try:
            data = resp.json() or {}
        except ValueError:
            pass
        log.warning("Plaid %s -> %s %s", path, resp.status_code, data.get("error_code"))
        raise PlaidError(
            status=resp.status_code,
            code=data.get("error_code"),
            error_type=data.get("error_type"),
            message=data.get("display_message") or data.get("error_message"),
        )

    return resp.json()


# --- token dance ----------------------------------------------------------

def create_link_token(user_id, client_name="BudgetMe"):
    return _post(
        "/link/token/create",
        client_name=client_name,
        language="en",
        country_codes=["US"],
        user={"client_user_id": str(user_id)},
        products=["transactions"],
    )["link_token"]


def exchange_public_token(public_token):
    return _post("/item/public_token/exchange", public_token=public_token)["access_token"]


# --- reading data -------------------------------------------------------

def _dec(value):
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def format_money(value):
    """Format a number/Decimal (or None) as '$1,234.56' / '-$12.00' / '—'."""
    if not isinstance(value, Decimal):
        value = _dec(value)
    if value is None:
        return "—"
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def _pfc_label(txn):
    primary = (txn.get("personal_finance_category") or {}).get("primary")
    return primary.replace("_", " ").capitalize() if primary else None


def _transaction_view(txn):
    # Plaid `amount` is POSITIVE when money LEAVES the account (a purchase) and
    # negative when it comes in. Flip it so the rest of the app treats
    # negative = spent, positive = received.
    amount = _dec(txn.get("amount"))
    if amount is not None:
        amount = -amount
    return {
        "date": txn.get("date"),
        "name": txn.get("name"),
        "merchant_name": txn.get("merchant_name"),
        "category": _pfc_label(txn),
        "pending": bool(txn.get("pending")),
        "amount": amount,
    }


def _sync_transactions(access_token):
    """Pull all transactions via /transactions/sync, polling a few times while
    the sandbox finishes its initial load."""
    added, cursor = [], ""
    for attempt in range(5):
        data = _post(
            "/transactions/sync", access_token=access_token, cursor=cursor, count=500
        )
        added.extend(data.get("added") or [])
        cursor = data.get("next_cursor") or cursor
        if data.get("has_more"):
            continue
        done = data.get("transactions_update_status") in (
            "HISTORICAL_UPDATE_COMPLETE",
            "INITIAL_UPDATE_COMPLETE",
        )
        if added or done:
            break
        if attempt < 4:
            time.sleep(1.5)
    return added


def get_overview(access_token, institution_name=None):
    """Return a list of per-account overviews.

    Each entry: {
        "account": {name, official_name, mask, type, subtype},
        "institution_name": str | None,
        "available": Decimal | None,
        "current": Decimal | None,
        "currency": str | None,
        "transactions": [<transaction view>, ...],   # newest first
    }
    """
    accounts = _post("/accounts/get", access_token=access_token).get("accounts") or []
    raw_txns = _sync_transactions(access_token)

    by_account = {}
    for t in raw_txns:
        by_account.setdefault(t.get("account_id"), []).append(t)

    overview = []
    for acc in accounts:
        balances = acc.get("balances") or {}
        txns = by_account.get(acc.get("account_id"), [])
        txns.sort(key=lambda t: t.get("date") or "", reverse=True)
        overview.append(
            {
                "account": {
                    "name": acc.get("name"),
                    "official_name": acc.get("official_name"),
                    "mask": acc.get("mask"),
                    "type": acc.get("type"),
                    "subtype": acc.get("subtype"),
                },
                "institution_name": institution_name,
                "available": _dec(balances.get("available")),
                "current": _dec(balances.get("current")),
                "currency": balances.get("iso_currency_code"),
                "transactions": [_transaction_view(t) for t in txns],
            }
        )

    # Order the cards for a budgeting view: spending accounts (checking/savings,
    # then credit) first, most-active first, then everything else. Keeps the
    # useful cards on top when an institution returns many accounts.
    type_rank = {"depository": 2, "credit": 1}
    overview.sort(
        key=lambda o: (
            type_rank.get(o["account"]["type"], 0),
            len(o["transactions"]),
            abs(o["current"] or 0),
        ),
        reverse=True,
    )
    return overview
