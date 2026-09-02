# BudgetMe

A Flask web app that links a bank account through [Teller](https://teller.io) and
shows a budget breakdown. Started as a "sunhacks" hackathon project; most screens
are still static mockups (see **Feature status** below).

## Requirements

- Python 3.10+ (developed/tested on 3.13)

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

`.env` works as-is for local development. It ships with a public Teller **sandbox**
app id, so the bank-link flow works without any account setup.

## Run

```bash
python run.py
```

Opens on http://127.0.0.1:8000 (set `HOST` / `PORT` / `FLASK_DEBUG` in `.env` to
change).

### Trying the bank-link flow

1. Go to `/login`, click **Open Bank Login**.
2. In Teller Connect pick any institution and log in with the sandbox
   credentials: username `username`, password `password`.
3. On success you land on `/breakdown`, which lists every account from the
   (fake) sandbox enrollment with its balances and recent transactions.

Sandbox data is synthetic but served by the real `api.teller.io`, so the
machine running the app needs outbound HTTPS to `api.teller.io`.

## Project layout

```
run.py                  entry point
budgetMe/
  budget.py             Flask app + routes
  teller_api.py         Teller API client (get_overview, TellerError, money helpers)
  templates/            Jinja templates (base.html + one per page)
  static/               style.css, app.js
teller.py               standalone Teller API probe (mTLS, not part of the app)
tests/test_breakdown.py fixture + error-path checks (python tests/test_breakdown.py)
```

## Routes

| Route | Purpose |
|-------|---------|
| `/` | Marketing home |
| `/login` (GET/POST) | Teller Connect page; POST stores the access token in the session |
| `/logout` | Clears the session token |
| `/breakdown` | Live: every connected account with its balances + recent transactions (from Teller) |
| `/advice` | Mock "advice chatbot" page |
| `/analysis` | Placeholder analytics page (no logic) |
| `/account` | Placeholder profile page (inert) |
| `/settings` | Placeholder settings page (inert) |
| `/createAccount` (GET/POST) | Placeholder signup form (no auth backend) |

## Feature status

| Area | State |
|------|-------|
| Marketing pages (`/`, `/login`) | Done - static |
| Teller Connect bank link (sandbox) | Working - token stored in the Flask session |
| `/breakdown` accounts + balances | Working - live from Teller, all accounts in the enrollment |
| `/breakdown` transactions | Working - live per account, newest first, capped at 25 shown |
| `/breakdown` error handling | Expired/revoked token -> flash + redirect to `/login`; Teller/network error -> styled error card |
| `/breakdown` charts / spending insights | Not started (a "coming soon" note in place of the old fake sections) |
| `/advice` AI chatbot | UI only, returns a canned string, no backend |
| `/analysis` | Route + styled placeholder page; no analysis computed |
| `/account`, `/settings` | Route + styled placeholder pages; all controls inert |
| Account creation (`/createAccount`) | Route + styled form; no database, no auth, submit does nothing |

## Notes

- The Teller access token lives in the Flask session (per browser), cleared by
  `/logout`. There is no user database.
- `teller.py` is independent of the web app and needs Teller client certificates
  (not sandbox). Configure `TELLER_ACCESS_TOKEN` / `TELLER_CERT_FILE` /
  `TELLER_KEY_FILE` in `.env` if you use it.
