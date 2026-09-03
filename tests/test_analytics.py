"""Checks for budgetMe.analytics.

Plain asserts, no pytest. Run:  python tests/test_analytics.py
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from budgetMe import analytics  # noqa: E402

NOW = date(2026, 8, 31)

# amounts are already sign-flipped: negative = spent, positive = received
TXNS = [
    {"date": "2026-08-30", "amount": -50.00, "category": "Groceries", "merchant_name": "Aldi"},
    {"date": "2026-08-20", "amount": -20.00, "category": "Groceries", "merchant_name": "Aldi"},
    {"date": "2026-08-15", "amount": -12.50, "category": "Food and drink", "merchant_name": "Cafe"},
    {"date": "2026-08-01", "amount": 2000.00, "category": "Income", "merchant_name": None},
    {"date": "2026-07-10", "amount": -100.00, "category": "Travel", "merchant_name": "Airline"},
    # outside the 90-day window:
    {"date": "2026-05-01", "amount": -999.00, "category": "Travel", "merchant_name": "Airline"},
    # in the future (ignored):
    {"date": "2026-09-05", "amount": -30.00, "category": "Groceries", "merchant_name": "Aldi"},
    # unparseable date (ignored):
    {"date": "bad-date", "amount": -1.00, "category": "X", "merchant_name": "Y"},
]


def check(name, cond):
    if not cond:
        raise AssertionError(f"FAILED: {name}")
    print(f"  ok  {name}")


def test_summary():
    s = analytics.summary(TXNS, now=NOW)
    # last 30 days = Aug 1..31: -50, -20, -12.50 spent; +2000 income
    check("spending_30d", s["spending_30d"] == 82.50)
    check("income_30d", s["income_30d"] == 2000.00)
    check("net_30d", s["net_30d"] == 1917.50)
    check("txn_count_30d", s["txn_count_30d"] == 4)


def test_report_categories():
    r = analytics.report(TXNS, now=NOW)
    cats = dict(r["by_category"])
    check("groceries summed (90d)", cats["Groceries"] == 70.00)
    check("travel within 90d only", cats["Travel"] == 100.00)  # the -999 is excluded
    check("income not counted as spending", "Income" not in cats)
    check("future txn excluded", cats["Groceries"] == 70.00)  # the 2026-09-05 -30 is not in
    check("categories sorted desc", r["by_category"][0][0] == "Travel")


def test_report_months_and_merchants():
    r = analytics.report(TXNS, now=NOW, months=3)
    months = {m: (sp, rc, nt) for m, sp, rc, nt in r["by_month"]}
    check("3 month keys", len(r["by_month"]) == 3)
    check("aug spent", months["2026-08"][0] == 82.50)
    check("aug received", months["2026-08"][1] == 2000.00)
    check("jul spent", months["2026-07"][0] == 100.00)

    top = r["top_merchants"]
    check("airline top merchant", top[0][0] == "Airline" and top[0][1] == 100.00)
    check("aldi second", top[1][0] == "Aldi" and top[1][1] == 70.00 and top[1][2] == 2)


def test_empty():
    r = analytics.report([], now=NOW)
    check("empty has_data false", r["has_data"] is False)
    s = analytics.summary([], now=NOW)
    check("empty summary zeros", s["spending_30d"] == 0 and s["txn_count_30d"] == 0)


def main():
    for fn in (test_summary, test_report_categories, test_report_months_and_merchants, test_empty):
        print(fn.__name__)
        fn()
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
