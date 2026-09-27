# Budget

Personal wealth tracker: accounts, transactions, budgets, debts, assets, investments and net worth, in EUR and RUB.
Design documents live in [`Spec/00 - Initial`](Spec/00%20-%20Initial/Spec.md).

| Part | Stack | Folder |
|---|---|---|
| Data | SQLite (STRICT tables, WAL), Alembic migrations | `backend/alembic`, `backend/app/db` |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2, Anthropic SDK | `backend/` |
| Web | React 19, TypeScript, Vite, Mantine, ECharts, i18next (EN/RU) | `frontend/` |
| Deploy | Docker Compose: backend + Caddy (TLS, static web, `/api` proxy) | `docker-compose.yml`, `deploy/` |

## Run locally

Prerequisites: [uv](https://docs.astral.sh/uv/) and Node 24.

```bash
# backend (http://localhost:8000, API docs at /api/docs)
cd backend
uv sync
cp .env.example .env              # set BUDGET_SECRET_KEY; BUDGET_ANTHROPIC_API_KEY enables AI suggestions
uv run alembic upgrade head       # create / migrate data/budget.db
uv run python -m app.cli seed     # categories, accounts, rules (structure only, no transactions)
uv run python -m app.cli create-user --email you@example.com --name You --admin
uv run python -m app.cli fetch-fx --since 2020-11-01   # ECB + CBR rates (RUB via the cbr-xml-daily.ru mirror)
uv run uvicorn app.main:app --reload

# web (http://localhost:5173, proxies /api to :8000)
cd frontend
npm install
npm run dev
```

## Tests

```bash
cd backend && uv run pytest && uv run ruff check app tests alembic
cd frontend && npm test && npm run typecheck
```
Parser tests also run against the real bank samples in `Spec/samples/` when that (git-ignored) folder is present.

## Deploy (VPS)

```bash
cat > .env <<EOF
BUDGET_DOMAIN=budget.example.com
BUDGET_SECRET_KEY=$(openssl rand -hex 32)
BUDGET_ANTHROPIC_API_KEY=...
EOF
docker compose up -d --build
docker compose exec backend python -m app.cli create-user --email you@example.com --name You --admin
```
The backend container backs up the database, runs migrations and the (idempotent) seed on every start. It also takes hourly
snapshots to `/data/backups` (volume `budget-data`). Off-site copies of that folder are still to be set up (Data.md §16).

## Importing history

See [Import.md](Spec/00%20-%20Initial/Import.md). In the web app go to **Import**:
1. Upload bank statements (ABN MT940/XLS, ABN Invest, bunq CSV/MT940, ICS PDF), review, commit.
2. Upload the Google Sheet export (`.xlsx`) under *History migration*. Rows after the cut-over dates are matched onto the bank
   data; earlier rows go to their accounts by the rules in Settings → Import rules.
3. **Load year-end balances** (same `.xlsx`), then **Generate balancing**.

## API client

The web app's API types are generated from the backend's OpenAPI schema: `cd frontend && npm run gen:api`.
