"""Teller API client.

All HTTP calls to https://api.teller.io live here so the Flask routes stay thin.
Teller uses HTTP basic auth with the enrollment access token as the username and
an empty password. No client certificate is needed in the sandbox environment.

The standalone `teller.py` at the repo root is a separate mTLS probe and is
unrelated to this module.
"""
import logging
from decimal import Decimal, InvalidOperation

import requests

log = logging.getLogger(__name__)

TELLER_API = "https://api.teller.io"

# Statuses where the access token / enrollment is no longer usable and the user
# needs to reconnect their bank.
_AUTH_STATUSES = (401, 403, 404)


class TellerError(Exception):
    """A Teller API call failed.

    `status` is the HTTP status (or None for a network-level failure). `code` is
    Teller's machine-readable error code when present (e.g.
    "enrollment.disconnected.credentials_invalid").
    """

    def __init__(self, status=None, code=None, message=None):
        self.status = status
        self.code = code
        self.message = message or "Teller request failed"
        super().__init__(self.message)


def teller_get(url, access_token):
    """GET a Teller API URL and return parsed JSON (a dict or a list).

    Raises TellerError on network failure or an error response.
    """
    try:
        resp = requests.get(url, auth=(access_token, ""), timeout=30)
    except requests.RequestException as exc:
        log.warning("Teller request failed: %s %s", url, exc)
        raise TellerError(
            status=None,
            message="Couldn't reach Teller. Check your connection and try again.",
        ) from exc

    if resp.status_code in _AUTH_STATUSES:
        code = message = None
        try:
            err = (resp.json() or {}).get("error") or {}
            code = err.get("code")
            message = err.get("message")
        except ValueError:
            pass
        raise TellerError(status=resp.status_code, code=code, message=message)

    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:
        log.warning("Teller returned %s for %s", resp.status_code, url)
        raise TellerError(
            status=resp.status_code,
            message="Teller returned an error. Please try again.",
        ) from exc

    return resp.json()


def _dec(value):
    """Parse a Teller money string into a Decimal, or None."""
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def format_money(value):
    """Format a Decimal (or None) as '$1,234.56' / '-$12.00' / '—'."""
    if not isinstance(value, Decimal):
        value = _dec(value)
    if value is None:
        return "—"
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def _transaction_view(txn):
    details = txn.get("details") or {}
    counterparty = details.get("counterparty") or {}
    return {
        "date": txn.get("date"),
        "description": txn.get("description"),
        "category": details.get("category"),
        "counterparty": counterparty.get("name"),
        "status": txn.get("status"),
        "amount": _dec(txn.get("amount")),
        "running_balance": _dec(txn.get("running_balance")),
    }


def get_overview(access_token):
    """Return a list of account overviews for the enrollment.

    Each entry: {
        "account": <raw account dict>,
        "available": Decimal | None,
        "ledger": Decimal | None,
        "transactions": [<transaction view>, ...],   # newest first
    }
    """
    accounts = teller_get(f"{TELLER_API}/accounts", access_token)
    if not isinstance(accounts, list):
        accounts = []

    overview = []
    for account in accounts:
        links = account.get("links") or {}

        balances = {}
        if links.get("balances"):
            balances = teller_get(links["balances"], access_token) or {}

        transactions = []
        if links.get("transactions"):
            raw = teller_get(links["transactions"], access_token) or []
            transactions = [_transaction_view(t) for t in raw if isinstance(t, dict)]

        overview.append(
            {
                "account": account,
                "available": _dec(balances.get("available")),
                "ledger": _dec(balances.get("ledger")),
                "transactions": transactions,
            }
        )
    return overview
