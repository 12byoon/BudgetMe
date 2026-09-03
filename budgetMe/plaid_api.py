"""Plaid API client.

All HTTP calls to Plaid live here so the Flask routes stay thin. Plaid
authenticates with `client_id` + `secret` in the JSON body of every request
(no client certificate). Sandbox base URL is https://sandbox.plaid.com.

Token dance:
  create_link_token(user_id)     -> link_token   (handed to Plaid Link in the browser)
  exchange_public_token(pub_tok) -> (access_token, item_id)   (long-lived; store it)
  fetch_accounts(access_token)   -> raw account list
  sync_transactions(token, cur)  -> (added, modified, removed, next_cursor, is_ready)

`shape_account` / `shape_transaction` normalise Plaid's raw JSON for the store
and templates, including flipping the transaction amount sign (Plaid: + = money
out; app: - = spent).
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
_READY_STATUSES = ("HISTORICAL_UPDATE_COMPLETE", "INITIAL_UPDATE_COMPLETE")


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
    data = _post("/item/public_token/exchange", public_token=public_token)
    return data["access_token"], data.get("item_id")


# --- fetching -----------------------------------------------------------

def fetch_accounts(access_token):
    return _post("/accounts/get", access_token=access_token).get("accounts") or []


def sync_transactions(access_token, cursor=""):
    """Pull a /transactions/sync delta.

    Returns (added, modified, removed_ids, next_cursor, is_ready). On the initial
    pull (cursor == "") the sandbox may report NOT_READY for a few seconds; this
    polls a handful of times before giving up with is_ready=False.
    """
    added, modified, removed = [], [], []
    is_ready = True
    for attempt in range(5):
        data = _post(
            "/transactions/sync", access_token=access_token, cursor=cursor, count=500
        )
        added.extend(data.get("added") or [])
        modified.extend(data.get("modified") or [])
        removed.extend(t.get("transaction_id") for t in (data.get("removed") or []))
        cursor = data.get("next_cursor") or cursor

        if data.get("has_more"):
            continue

        status = data.get("transactions_update_status")
        if added or modified or removed or status in _READY_STATUSES:
            break
        # nothing yet and not marked ready
        if not cursor and attempt < 4:
            time.sleep(1.5)
            continue
        is_ready = status in _READY_STATUSES
        break

    return added, modified, removed, cursor, is_ready


# --- shaping ----------------------------------------------------------

def _dec(value):
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _to_float(value):
    d = _dec(value)
    return float(d) if d is not None else None


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


def shape_account(raw):
    b = raw.get("balances") or {}
    return {
        "account_id": raw.get("account_id"),
        "name": raw.get("name"),
        "official_name": raw.get("official_name"),
        "mask": raw.get("mask"),
        "type": raw.get("type"),
        "subtype": raw.get("subtype"),
        "available": _to_float(b.get("available")),
        "current": _to_float(b.get("current")),
        "currency": b.get("iso_currency_code"),
    }


def shape_transaction(raw):
    # Plaid `amount` is positive when money LEAVES the account. Flip it so the
    # rest of the app treats negative = spent, positive = received.
    amt = _to_float(raw.get("amount"))
    if amt is not None:
        amt = -amt
    return {
        "transaction_id": raw.get("transaction_id"),
        "account_id": raw.get("account_id"),
        "date": raw.get("date"),
        "name": raw.get("name"),
        "merchant_name": raw.get("merchant_name"),
        "amount": amt,
        "pending": 1 if raw.get("pending") else 0,
        "category": _pfc_label(raw),
    }
