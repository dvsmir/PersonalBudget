# Backend Service — FastAPI

Part of the [Spec](Spec.md). Uses the schema in [Data.md](Data.md). Serves the clients in [Frontend.md](Frontend.md).

## 1. Responsibilities
- The **only** component that touches the database. It owns every business rule, invariant and derived figure.
- Exposes a versioned JSON REST API (`/api/v1`) for the web app and, later, the Android app.
- Hosts all **connectors**: file importers, bank API sync, FX and price feeds, and the AI categoriser.
- Runs scheduled jobs: FX rates, prices, Bunq sync, backups, budget month roll-over.

## 2. Tech stack

| Concern | Choice |
|---|---|
| Runtime | Python 3.12+, managed with `uv` |
| Web | FastAPI + Uvicorn. Pydantic v2 schemas |
| ORM / migrations | SQLAlchemy 2.x (sync engine; SQLite is local and fast) + Alembic |
| Money | `int` minor units inside the domain. `Decimal` for rates and prices. A `Money` value object |
| Auth | argon2-cffi (passwords), PyJWT (access tokens), pyotp (TOTP) |
| Files | `openpyxl` (xlsx), stdlib `csv`, `lxml` (CAMT.053 XML) |
| HTTP clients | `httpx` (ECB, CBR, prices, Bunq) |
| AI | Official `anthropic` Python SDK |
| Jobs | APScheduler, in-process (a single instance is enough) |
| Tests | pytest, a real in-memory SQLite per test, `hypothesis` for money/FX invariants |
| Lint/type | ruff, mypy (strict on `domain/` and `services/`) |

## 3. Code structure

```
backend/
  app/
    main.py                 # FastAPI app factory, middleware, routers
    config.py               # pydantic-settings (env vars)
    db/                     # engine, session, SQLAlchemy models, alembic/
    domain/                 # pure logic, no I/O: Money, FX math, loan math, invariants
    services/               # use-cases; transactional; call repositories + domain
      ledger.py             #   create/update/delete txn, validate invariants, compute amount_ref
      accounts.py           #   balances, reconciliation
      fx.py                 #   rate lookup, conversion, revaluation
      debts.py              #   schedules, payment split suggestion, payoff forecast
      investments.py        #   holdings, valuation, gains
      budget.py             #   templates, month generation, plan vs actual
      reports.py            #   dashboards, net worth, NW bridge
      imports.py            #   batch lifecycle, dedupe, commit
      categoriser.py        #   AI suggestions
    connectors/
      base.py               # Importer protocol
      mt940.py  abn_xls.py  abn_invest.py  bunq_csv.py  bunq_api.py  ics_pdf.py
      gsheet_std.py  gsheet_block.py  generic_csv.py  matcher.py
      fx_ecb.py  fx_cbr.py  prices.py
    api/v1/                 # routers: thin; validate → service → schema
    jobs/                   # scheduled job definitions
    i18n/                   # server-side messages (errors, emails) en/ru
  tests/
```
Rules:
- **Routers** hold no logic.
- **Services** own one DB transaction per request.
- **Domain** code is pure and fully unit-tested.

## 4. Domain rules implemented here

### 4.1 Ledger writes (`services/ledger.py`)
- **Validation:** each txn kind is checked against the invariants table in Data §7.1. Violations return `422` with a machine-readable code.
- **EUR values:** `amount_ref` for every leg and split is computed from `fx.rate(date, currency)`. With no rate for the date, the latest earlier rate is used and `ref_estimated=1` is set.
- **Transfers:** a transfer between different currencies is a **conversion**. `fx_diff_ref = Σ legs.amount_ref` is computed; a negative value means we lost on the spread. When `conversion_cost_category_id` is set, an extra expense split is posted instead of leaving it in the NW bridge.
- **Debt payments:** the backend **suggests** the interest/principal split for a date and amount (see §4.3). The client may override it, but splits must still sum to the leg.
- **Cost type:** it is stored only when the user overrides the default. Reports resolve it via the view.
- **Audit:** every write adds an `audit_log` entry with a before/after diff.
- **Locked periods (optional setting):** edits dated before `lock_date` are refused unless the caller is an admin.

### 4.2 FX (`services/fx.py`)
- **`rate(date, from, to)`** chains through EUR, e.g. RUB→USD = (EUR→USD) / (EUR→RUB).
- **`value_at(balance, currency, date)`** gives the EUR value used for balances and net worth at a date.
- **Revaluation:** FX revaluation for a period is the change in EUR value of foreign-currency balances, minus the EUR value of the flows in between.

### 4.3 Debts (`services/debts.py`)
- **Outstanding principal:** follows Data §9.
- **Expected schedule:** built from `repayment_type` and the rate periods. Annuity uses `PMT` on the remaining term; linear is fixed principal plus interest on the balance.
- **`suggest_split(debt, date, amount)`:** interest = outstanding × rate / 12, principal = amount − interest. For `free` loans (parents), everything is principal.
- **Outputs:** repaid this month and year ("returns"), remaining term, payoff date forecast, and expected vs actual payments (missed or extra).

### 4.4 Investments (`services/investments.py`)
- **Holdings:** built from trades. Valuation uses the latest price. Contributions = transfers into investment accounts.
- **Gain:** Δ value − net contributions (simple, no time-weighted return in v1).

### 4.5 Reports (`services/reports.py`)
All reports take `currency_mode = native | reference`. Native returns one series per currency; reference returns everything in EUR.

| Report | Output |
|---|---|
| `month_summary(month)` | Income & costs by category → subcategory, by cost type; totals; debt principal repaid; transfers to savings/investments; cash-flow; plan vs actual |
| `year_overview(year)` | Per month: income, costs, balance, funds at month-end (mirrors the sheet's "Year summary"); per category: sum and avg/month |
| `net_worth(from, to, step=month)` | Series of funds, available funds, investments, assets, debts, net worth |
| `net_worth_bridge(from, to)` | Components as defined in Spec §3.2 |
| `account_balances(date)` | Per account, native + EUR; per currency totals |
| `budget_status(month)` | Per category: plan, actual, remaining, % used |
| `project_summary(id)` | Totals by category, over time, vs project budget |
| `category_trend(category, from, to)` | Monthly series for one category (drill-down) |

## 5. Connectors

### 5.1 Importer contract
```python
class Importer(Protocol):
    source: str
    def sniff(self, filename: str, head: bytes) -> bool: ...          # auto-detect format
    def parse(self, file: BinaryIO, ctx: ImportContext) -> Iterable[ParsedRow]: ...
# ParsedRow: date, amount (minor), currency, account_hint, counterparty,
#            description, external_id, raw: dict
```
Pipeline for every file-based source:

```
upload → sniff/choose importer → parse → map account (by IBAN/card in file, or chosen in UI)
      → dedupe (external_id, else dedupe_key) → detect transfers → AI suggest → REVIEW (UI)
      → commit accepted rows as txns (single DB transaction) → batch = committed
```
- **Idempotency:** re-uploading a file with the same SHA-256 is rejected. Overlapping statements are safe because of dedupe.
- **Transfer detection:** a debit in one own account is matched to a credit of the same amount (or a plausible FX amount) in another own account within ±3 days. A counterparty IBAN that equals one of our own accounts also counts. Matches are proposed as one `transfer` txn and override the AI.
- **Credit-card repayment:** ABN → credit card account is detected as a transfer, by counterparty (ICS) or amount match.
- **Debt payments:** rows whose counterparty matches a debt's lender are proposed as `debt_payment` with the suggested split.

### 5.2 Sources, classification rules and historical migration
Specified in **[Import.md](Import.md)**: formats per bank (ABN MT940/XLS, ABN Invest, Bunq, ICS PDF), own-account identifiers, transfer detection, dedupe keys, and the Google Sheet migration (match mode against bank exports, sheet-only mode with balance anchors, exception rules).

## 6. AI categoriser (`services/categoriser.py`)

### 6.1 Behaviour (D14: AI only, always reviewed)
- **Scope:** every imported row that isn't a detected transfer or debt payment gets an AI suggestion: `kind`, `category_id` (subcategory where possible), `cost_type`, `project_id`, `confidence`, and a short `rationale`.
- **Nothing auto-commits.** The review UI shows the suggestion pre-filled. The user accepts, edits or skips it.
- **Learning happens through context, not rules.** Every request includes the user's most similar **confirmed** past transactions (FTS5 trigram search on counterparty/description, top 5–10 per row) as examples. Corrections therefore improve later suggestions automatically.

### 6.2 Request design
| Aspect | Design |
|---|---|
| SDK | `anthropic` Python SDK, `client.messages.parse(...)` with a Pydantic output schema (structured outputs), so the response is validated JSON |
| Model | Setting `ai_model`, default `claude-opus-5`. Can be switched in Settings (e.g. to a cheaper model) after comparing quality on your own data |
| Batching | 25–50 rows per request. Each row has an index. The output is a list keyed by that index |
| Prompt caching | The system prompt (instructions, the full category tree with `description` hints, cost-type rules, active projects) is stable and marked with `cache_control`. Per-row examples and rows come after it. Cache hit rate is logged |
| Bulk | Sheet history and other large backfills go through the Message Batches API. Results are keyed by `custom_id` = import_row id |
| Privacy | Sent: date, amount, currency, counterparty, description, account *type*. Never sent: IBANs, card numbers, user names |
| Failure | On API error or timeout the rows stay `new` without a suggestion and can be categorised manually. Retry is available per batch |
| Cost control | `ai_call_log` stores token usage per call. A monthly soft budget raises a warning in the UI |
| Output guard | Category ids are validated against the live tree. An unknown or archived id sets the suggestion to "uncategorised" |

## 7. API (v1)

All endpoints are under `/api/v1`, JSON, with RFC 7807 problem responses for errors. The OpenAPI schema is generated and is the **contract** for the web and Android clients (TS client generated from it).

| Area | Endpoints |
|---|---|
| Auth | `POST /auth/login` (email+password[+totp]) · `POST /auth/refresh` · `POST /auth/logout` · `GET /me` · `PATCH /me` (locale, password) · `POST /me/totp` |
| Users (admin) | `GET/POST /users` · `PATCH /users/{id}` |
| Accounts | `GET/POST /accounts` · `GET/PATCH /accounts/{id}` · `GET /accounts/{id}/balance-series` · `POST /accounts/{id}/reconcile` |
| Categories | `GET /categories` (tree) · `POST` · `PATCH /{id}` · `POST /{id}/archive` · `POST /categories/merge` |
| Transactions | `GET /txns` (filters: date range, account, category, project, kind, cost_type, text, amount range; cursor paging) · `POST /txns` · `GET/PUT/DELETE /txns/{id}` · `POST /txns/bulk-update` (category/project/cost_type for many) |
| Helpers | `POST /txns/suggest-debt-split` · `GET /fx/rate?date&from&to` |
| Debts | `GET/POST /debts` · `GET/PATCH /debts/{id}` · `GET /debts/{id}/schedule` · `POST /debts/{id}/snapshots` · `POST /debts/{id}/rate-periods` |
| Earmarks | `GET/POST /earmarks` · `PATCH /earmarks/{id}` · `GET /earmarks/{id}/movements` |
| Assets | `GET/POST /assets` · `PATCH /assets/{id}` · `POST /assets/{id}/valuations` |
| Investments | `GET/POST /securities` · `GET /investments/holdings?date` · trades via `POST /txns` (kind=investment) |
| Budget | `GET/POST/PATCH/DELETE /budget/template` · `POST /budget/{month}/generate` · `GET /budget/{month}` · `PATCH /budget/lines/{id}` |
| Projects | `GET/POST /projects` · `PATCH /projects/{id}` · `GET /projects/{id}/summary` |
| Imports | `POST /imports` (multipart file + source + account) → batch · `GET /imports` · `GET /imports/{id}` · `GET /imports/{id}/rows` · `PATCH /imports/{id}/rows/{rowId}` (edit proposal / accept / skip) · `POST /imports/{id}/rows/bulk` · `POST /imports/{id}/suggest` (re-run AI) · `POST /imports/{id}/commit` · `DELETE /imports/{id}` |
| Reports | `GET /reports/month/{YYYY-MM}` · `/reports/year/{YYYY}` · `/reports/net-worth` · `/reports/net-worth-bridge` · `/reports/balances` · `/reports/budget/{YYYY-MM}` · `/reports/category-trend` |
| Settings | `GET/PATCH /settings` · `GET /currencies` · `GET /health` |
| Export | `GET /export/txns.csv` · `GET /export/full.json` (portability) |

Conventions:
- **Money:** in JSON it is `{"amount": "-12.34", "currency": "EUR"}`, a decimal string in major units, so no float issues in JS or Kotlin.
- **Lists:** `?cursor=&limit=` paging. Sorting is whitelisted.
- **Optimistic concurrency:** `updated_at` goes in `If-Match`, and a mismatch returns `409`. This matters with two users.

## 8. Security

| Topic | Design |
|---|---|
| Transport | Caddy reverse proxy, automatic TLS, HSTS. Backend only on the internal Docker network |
| Web auth | Short-lived access JWT (15 min) in memory plus a refresh token in an httpOnly, Secure, SameSite=Strict cookie. CSRF: double-submit token on cookie-authenticated mutating calls |
| Android auth | Same login endpoint with `client=android`. The refresh token is stored in the Android Keystore |
| Passwords | argon2id. Login rate limit (5/min/IP + per account), lockout with backoff |
| 2FA | Optional TOTP per user (strongly recommended on a public VPS) |
| Secrets | Env/`.env` loaded by pydantic-settings: JWT key, Anthropic key, Bunq key, backup encryption key. DB-stored secrets are encrypted with a key from the env |
| Authorisation | Household model: all users see all data. `admin` manages users and settings |
| Headers | Strict CSP (served with the SPA), X-Content-Type-Options, frame-ancestors none |
| Uploads | Size limit (10 MB), parsed in memory, never executed, not persisted |

## 9. Jobs (APScheduler)

| Job | Schedule | Action |
|---|---|---|
| `fx_fetch` | Daily 17:00 CET + on startup | ECB (EUR→USD, …) and CBR (RUB). Backfill gaps. Recompute `ref_estimated` rows |
| `price_fetch` | Daily after market close | Prices for securities with an automatic source |
| `bunq_sync` | Every 6h (v1.x) | Pull new transactions into an import batch for review |
| `budget_rollover` | 1st of month 00:05 | Generate `budget_line` rows from the template if missing |
| `backup` | Hourly snapshot, nightly off-site | See Data §16 |
| `debt_check` | Daily | Flag expected debt payments that did not happen (shown on dashboard) |

## 10. Deployment
- **Containers:** `docker-compose` with `caddy` (TLS + static SPA + `/api` proxy), `backend` (uvicorn, 1 worker plus the in-process scheduler) and `backup` (sidecar, or cron inside the backend).
- **Volumes:** `/data/budget.db` and `/data/backups`.
- **Migrations:** Alembic runs on container start (`alembic upgrade head`), after a pre-migration backup.
- **Observability:** structured JSON logs, `/api/v1/health`, and optional Sentry-compatible error reporting (off by default).
- **CI:** lint, type-check, tests, build images, restore-from-backup smoke test.

## 11. Testing strategy
- **Domain:** property tests for money arithmetic and FX. For example, a conversion never changes income or expense, and Σ bridge components = Δ net worth.
- **Services:** against a real SQLite with fixtures shaped like the sheet (EUR+RUB months, a conversion, a mortgage payment, an earmark).
- **Importers:** golden files (anonymised samples from each bank) → expected parsed rows.
- **AI:** a recorded-response fake in tests, plus an offline eval script. It measures agreement of suggestions with your already-categorised 2025–2026 history, and is used to choose the model.
- **API:** contract tests generated from OpenAPI.

## 12. Open questions — backend
1. **Bunq API:** is it OK to create a Bunq API key for read-only sync (v1.x), or stay with CSV export?
2. **Investment price source:** ABN Invest holds funds (VANG SP500, iShares) and single stocks in USD/GBP/EUR (Alphabet, Realty Income, BP, Shell). Is a free provider (e.g. Yahoo-style quotes by ticker/ISIN) acceptable, or manual prices? Manual price entry is the fallback.
3. **Notifications:** do you want e-mail or push for "import waiting for review", "expected mortgage payment missing" or "budget exceeded"? None are planned for v1.
