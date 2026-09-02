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
2. In the Teller Connect popup pick any sandbox institution and use the test
   credentials Teller shows.
3. On success you land on `/breakdown`, which displays your (sandbox) account
   balance. Everything else on that page is placeholder data.

## Project layout

```
run.py                  entry point
budgetMe/
  budget.py             Flask app + routes + Teller API calls
  templates/            Jinja templates (base.html + one per page)
  static/               style.css, app.js
teller.py               standalone Teller API probe (mTLS, not part of the app)
```

## Feature status

| Area | State |
|------|-------|
| Marketing pages (`/`, `/login`, `/advice`) | Done - static |
| Teller Connect bank link (sandbox) | Working - token stored in the Flask session |
| `/breakdown` account balance | Working - live from Teller |
| `/breakdown` transactions | Data is fetched and passed to the template as `transactions`, but the table still shows hardcoded rows |
| `/breakdown` savings / investments / goals | Placeholder numbers |
| `/breakdown` charts | Empty placeholder boxes, no charting library |
| `/advice` AI chatbot | UI only, returns a canned string, no backend |
| `/analysis` page | Placeholder template, no route |
| Account creation / login / `/account` / `/settings` | Templates only, no routes, no database, no auth |

## Notes

- The Teller access token lives in the Flask session (per browser), cleared by
  `/logout`. There is no user database.
- `teller.py` is independent of the web app and needs Teller client certificates
  (not sandbox). Configure `TELLER_ACCESS_TOKEN` / `TELLER_CERT_FILE` /
  `TELLER_KEY_FILE` in `.env` if you use it.
