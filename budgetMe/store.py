"""SQLite data layer for BudgetMe.

One local database (default: instance/budgetme.db) holds every linked bank
`connection`, its `account`s, and its `txn`s. The Flask routes read and write
through the functions here; they never touch SQL directly.

`txn.amount` is stored **sign-flipped from Plaid** (negative = money spent,
positive = money received) so the rest of the app and the templates don't have
to think about Plaid's convention.

Call `init_db(path)` once at startup before any other function.
"""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

_DB_PATH = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS connection (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id          TEXT UNIQUE,
    access_token     TEXT NOT NULL,
    institution_name TEXT,
    cursor           TEXT NOT NULL DEFAULT '',
    linked_at        TEXT NOT NULL,
    last_synced_at   TEXT,
    status           TEXT NOT NULL DEFAULT 'ok',
    last_error       TEXT
);

CREATE TABLE IF NOT EXISTS account (
    account_id     TEXT PRIMARY KEY,
    connection_id  INTEGER NOT NULL REFERENCES connection(id) ON DELETE CASCADE,
    name           TEXT,
    official_name  TEXT,
    mask           TEXT,
    type           TEXT,
    subtype        TEXT,
    available      REAL,
    current        REAL,
    currency       TEXT,
    updated_at     TEXT
);

CREATE TABLE IF NOT EXISTS txn (
    transaction_id TEXT PRIMARY KEY,
    connection_id  INTEGER NOT NULL REFERENCES connection(id) ON DELETE CASCADE,
    account_id     TEXT,
    date           TEXT,
    name           TEXT,
    merchant_name  TEXT,
    amount         REAL,
    pending        INTEGER,
    category       TEXT
);

CREATE INDEX IF NOT EXISTS idx_txn_date ON txn(date);
CREATE INDEX IF NOT EXISTS idx_txn_account ON txn(account_id);
"""

# Account ordering for the dashboard: spending accounts first, most-active first.
_TYPE_RANK = {"depository": 2, "credit": 1}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_db(path):
    """Point the store at `path` and create tables if needed."""
    global _DB_PATH
    _DB_PATH = path
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with _conn() as db:
        db.executescript(_SCHEMA)


@contextmanager
def _conn():
    if _DB_PATH is None:
        raise RuntimeError("store.init_db(path) must be called first")
    db = sqlite3.connect(_DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# --- connections --------------------------------------------------------

def list_connections():
    with _conn() as db:
        return [dict(r) for r in db.execute("SELECT * FROM connection ORDER BY id")]


def get_connection(connection_id):
    with _conn() as db:
        row = db.execute("SELECT * FROM connection WHERE id = ?", (connection_id,)).fetchone()
        return dict(row) if row else None


def add_connection(item_id, access_token, institution_name):
    """Insert a connection, or refresh the token/name if `item_id` already exists.

    Returns the connection id.
    """
    with _conn() as db:
        existing = db.execute(
            "SELECT id FROM connection WHERE item_id = ?", (item_id,)
        ).fetchone()
        if existing:
            db.execute(
                "UPDATE connection SET access_token = ?, institution_name = ?, "
                "status = 'ok', last_error = NULL WHERE id = ?",
                (access_token, institution_name, existing["id"]),
            )
            return existing["id"]
        cur = db.execute(
            "INSERT INTO connection (item_id, access_token, institution_name, linked_at) "
            "VALUES (?, ?, ?, ?)",
            (item_id, access_token, institution_name, _now()),
        )
        return cur.lastrowid


def delete_connection(connection_id):
    with _conn() as db:
        db.execute("DELETE FROM connection WHERE id = ?", (connection_id,))


def set_cursor(connection_id, cursor):
    with _conn() as db:
        db.execute(
            "UPDATE connection SET cursor = ? WHERE id = ?", (cursor, connection_id)
        )


def set_synced_now(connection_id):
    with _conn() as db:
        db.execute(
            "UPDATE connection SET last_synced_at = ? WHERE id = ?", (_now(), connection_id)
        )


def set_status(connection_id, status, error=None):
    with _conn() as db:
        db.execute(
            "UPDATE connection SET status = ?, last_error = ? WHERE id = ?",
            (status, error, connection_id),
        )


# --- accounts & transactions ------------------------------------------

def upsert_accounts(connection_id, accounts):
    """`accounts` is a list of shaped account dicts (see plaid_api.shape_account)."""
    now = _now()
    with _conn() as db:
        for a in accounts:
            db.execute(
                """INSERT INTO account
                     (account_id, connection_id, name, official_name, mask, type,
                      subtype, available, current, currency, updated_at)
                   VALUES (:account_id, :connection_id, :name, :official_name, :mask,
                           :type, :subtype, :available, :current, :currency, :updated_at)
                   ON CONFLICT(account_id) DO UPDATE SET
                     name=excluded.name, official_name=excluded.official_name,
                     mask=excluded.mask, type=excluded.type, subtype=excluded.subtype,
                     available=excluded.available, current=excluded.current,
                     currency=excluded.currency, updated_at=excluded.updated_at""",
                {**a, "connection_id": connection_id, "updated_at": now},
            )


def apply_transactions(connection_id, added, modified, removed):
    """Apply a /transactions/sync delta. `added`/`modified` are shaped txn dicts
    (see plaid_api.shape_transaction); `removed` is a list of transaction ids."""
    with _conn() as db:
        for t in list(added) + list(modified):
            db.execute(
                """INSERT INTO txn
                     (transaction_id, connection_id, account_id, date, name,
                      merchant_name, amount, pending, category)
                   VALUES (:transaction_id, :connection_id, :account_id, :date, :name,
                           :merchant_name, :amount, :pending, :category)
                   ON CONFLICT(transaction_id) DO UPDATE SET
                     account_id=excluded.account_id, date=excluded.date,
                     name=excluded.name, merchant_name=excluded.merchant_name,
                     amount=excluded.amount, pending=excluded.pending,
                     category=excluded.category""",
                {**t, "connection_id": connection_id},
            )
        for tid in removed:
            db.execute("DELETE FROM txn WHERE transaction_id = ?", (tid,))


# --- read models for the views --------------------------------------

def accounts_with_transactions():
    """The shape breakdown.html consumes: one entry per account, newest txns first,
    ordered spending-accounts-first / most-active-first."""
    with _conn() as db:
        accounts = [dict(r) for r in db.execute(
            "SELECT a.*, c.institution_name FROM account a "
            "JOIN connection c ON c.id = a.connection_id"
        )]
        txns = [dict(r) for r in db.execute(
            "SELECT * FROM txn ORDER BY date DESC, transaction_id DESC"
        )]

    by_account = {}
    for t in txns:
        by_account.setdefault(t["account_id"], []).append({
            "date": t["date"],
            "name": t["name"],
            "merchant_name": t["merchant_name"],
            "category": t["category"],
            "pending": bool(t["pending"]),
            "amount": t["amount"],
        })

    out = []
    for a in accounts:
        out.append({
            "account": {
                "name": a["name"],
                "official_name": a["official_name"],
                "mask": a["mask"],
                "type": a["type"],
                "subtype": a["subtype"],
            },
            "institution_name": a["institution_name"],
            "available": a["available"],
            "current": a["current"],
            "currency": a["currency"],
            "transactions": by_account.get(a["account_id"], []),
        })

    out.sort(
        key=lambda o: (
            _TYPE_RANK.get(o["account"]["type"], 0),
            len(o["transactions"]),
            abs(o["current"] or 0),
        ),
        reverse=True,
    )
    return out


def all_transactions():
    """Flat list of every stored transaction, for analytics."""
    with _conn() as db:
        return [
            {
                "date": r["date"],
                "name": r["name"],
                "merchant_name": r["merchant_name"],
                "category": r["category"],
                "amount": r["amount"],
                "pending": bool(r["pending"]),
                "account_id": r["account_id"],
            }
            for r in db.execute("SELECT * FROM txn")
        ]


def connection_summaries():
    """Per-connection info for the /connections page."""
    with _conn() as db:
        return [dict(r) for r in db.execute(
            "SELECT c.id, c.institution_name, c.linked_at, c.last_synced_at, "
            "c.status, c.last_error, "
            "(SELECT COUNT(*) FROM account a WHERE a.connection_id = c.id) AS account_count "
            "FROM connection c ORDER BY c.id"
        )]
