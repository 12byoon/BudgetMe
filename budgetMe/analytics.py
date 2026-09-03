"""Spending analytics — pure functions over a list of transactions.

No Flask, no DB. Each transaction is a dict with at least:
    date          "YYYY-MM-DD"
    amount        float, sign-flipped: negative = spent, positive = received
    category      str | None   (humanized Plaid PFC primary)
    merchant_name str | None

`now` is injectable so the windows are testable.
"""
from collections import defaultdict
from datetime import date, timedelta


def _parse(txns):
    """Yield (datetime.date, txn) for transactions with a valid ISO date."""
    for t in txns:
        raw = t.get("date")
        if not raw:
            continue
        try:
            yield date.fromisoformat(raw), t
        except ValueError:
            continue


def summary(txns, now=None):
    """Headline numbers for the last 30 days (dashboard)."""
    now = now or date.today()
    cutoff = now - timedelta(days=30)
    spending = income = count = 0.0
    for d, t in _parse(txns):
        if d < cutoff or d > now:
            continue
        count += 1
        amt = t.get("amount") or 0
        if amt < 0:
            spending += -amt
        elif amt > 0:
            income += amt
    return {
        "spending_30d": round(spending, 2),
        "income_30d": round(income, 2),
        "net_30d": round(income - spending, 2),
        "txn_count_30d": int(count),
    }


def report(txns, now=None, category_days=90, months=6, merchant_limit=10):
    """Fuller breakdown for the /analysis page."""
    now = now or date.today()
    cat_cutoff = now - timedelta(days=category_days)

    by_category = defaultdict(float)
    by_month = defaultdict(lambda: [0.0, 0.0])  # [spent, received]
    merchants = defaultdict(lambda: [0.0, 0])   # [spent, count]

    month_keys = _recent_months(now, months)
    earliest_month = month_keys[0]

    for d, t in _parse(txns):
        if d > now:
            continue
        amt = t.get("amount") or 0
        spent = -amt if amt < 0 else 0.0
        received = amt if amt > 0 else 0.0

        if cat_cutoff <= d and spent:
            by_category[t.get("category") or "Uncategorized"] += spent
            name = t.get("merchant_name") or t.get("name") or "Unknown"
            merchants[name][0] += spent
            merchants[name][1] += 1

        mkey = f"{d.year:04d}-{d.month:02d}"
        if mkey >= earliest_month:
            by_month[mkey][0] += spent
            by_month[mkey][1] += received

    category_rows = sorted(
        ((c, round(v, 2)) for c, v in by_category.items()),
        key=lambda x: x[1],
        reverse=True,
    )
    month_rows = [
        (
            m,
            round(by_month[m][0], 2),
            round(by_month[m][1], 2),
            round(by_month[m][1] - by_month[m][0], 2),
        )
        for m in month_keys
    ]
    merchant_rows = sorted(
        ((n, round(v[0], 2), v[1]) for n, v in merchants.items()),
        key=lambda x: x[1],
        reverse=True,
    )[:merchant_limit]

    return {
        "by_category": category_rows,
        "by_month": month_rows,
        "top_merchants": merchant_rows,
        "range_label": f"last {category_days} days",
        "has_data": bool(category_rows or any(r[1] or r[2] for r in month_rows)),
    }


def _recent_months(now, count):
    """['YYYY-MM', ...] oldest first, ending with the current month."""
    keys = []
    y, m = now.year, now.month
    for _ in range(count):
        keys.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return list(reversed(keys))
