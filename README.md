# BudgetMe

A Flask web app that links a bank account through [Plaid](https://plaid.com) and
shows a budget breakdown. Started as a "sunhacks" hackathon project; the
`/breakdown` page renders real account data, the other feature screens are still
static mockups (see **Feature status** below).

> Originally built on Teller.io, which withdrew its API in July 2026. Migrated to
> Plaid's sandbox.

## Requirements

- Python 3.10+ (developed/tested on 3.13)
- A free Plaid account for sandbox API keys (no credit card)

## Setup

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux:
# source .venv/bin/activate

pip install -r requirements.txt

cp .env.example .env      # Windows: copy .env.example .env
```

Then get Plaid sandbox keys:

1. Sign up at https://dashboard.plaid.com/signup (instant, no card).
2. Open https://dashboard.plaid.com/developers/keys and copy your **Client ID**
   and your **Sandbox** secret.
3. Put them in `.env` as `PLAID_CLIENT_ID` and `PLAID_SECRET` (leave
   `PLAID_ENV=sandbox`).

## Run

```bash
python run.py
```

Opens on http://127.0.0.1:8000 (set `HOST` / `PORT` / `FLASK_DEBUG` in `.env` to
change).

### Trying the bank-link flow

1. Go to `/login`, click **Open Bank Login**.
2. In the Plaid Link popup pick **First Platypus Bank** and log in with the
   sandbox credentials: username `user_good`, password `pass_good` (OTP `1234`
   if prompted).
3. You land on `/breakdown`, which lists every linked account with its balances
   and recent transactions.

Sandbox transactions can take a few seconds to populate on the first load; the
page polls briefly, and a refresh always fills them in.

### Checking your keys without the browser

```bash
python plaid_probe.py
```

Mints a sandbox token via Plaid's `/sandbox/public_token/create`, then prints the
accounts and transactions. Fastest way to confirm `.env` is set up right.

## Project layout

```
run.py                  entry point
budgetMe/
  budget.py             Flask app + routes
  plaid_api.py          Plaid client (create_link_token, exchange_public_token, get_overview, PlaidError)
  templates/            Jinja templates (base.html + one per page)
  static/               style.css, app.js
plaid_probe.py          standalone sandbox probe (not part of the app)
tests/test_breakdown.py fixture + error-path checks: python tests/test_breakdown.py
```

## Routes

| Route | Purpose |
|-------|---------|
| `/` | Marketing home |
| `/login` (GET/POST) | GET creates a Plaid link token; POST exchanges the public token and stores the access token in the session |
| `/logout` | Clears the session |
| `/breakdown` | Live: every linked account with balances + recent transactions |
| `/advice` | Mock "advice chatbot" page |
| `/analysis` | Placeholder analytics page (no logic) |
| `/account` | Placeholder profile page (inert) |
| `/settings` | Placeholder settings page (inert) |
| `/createAccount` (GET/POST) | Placeholder signup form (no auth backend) |

## Feature status

| Area | State |
|------|-------|
| Marketing pages (`/`, `/login`) | Done - static |
| Plaid Link bank connect (sandbox) | Working - access token stored in the Flask session |
| `/breakdown` accounts + balances | Working - live from Plaid, all linked accounts |
| `/breakdown` transactions | Working - live per account (`/transactions/sync`), newest first, 25 shown |
| `/breakdown` error handling | Re-link-required token -> error card + reconnect; Plaid/network error -> error card |
| `/breakdown` charts / spending insights | Not started (a "coming soon" note in place of the old fake sections) |
| `/advice` AI chatbot | UI only, returns a canned string, no backend |
| `/analysis` | Route + styled placeholder page; no analysis computed |
| `/account`, `/settings` | Route + styled placeholder pages; all controls inert |
| Account creation (`/createAccount`) | Route + styled form; no database, no auth, submit does nothing |

## Notes

- The Plaid access token lives only in the Flask session (signed cookie), cleared
  by `/logout`. There is no user database. It's a long-lived secret - never
  commit it.
- Plaid `amount` is positive for money leaving the account; `get_overview` flips
  the sign so the rest of the app treats negative = spent, positive = received.
- `.env` (git-ignored) holds `PLAID_CLIENT_ID` / `PLAID_SECRET`.
