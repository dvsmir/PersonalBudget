# Data Layer — SQLite

Part of the [Spec](Spec.md). This document defines the storage model. Business rules that the database cannot enforce are listed per entity and implemented in the backend service layer.

## 1. Engine & conventions

| Topic | Rule |
|---|---|
| Engine | SQLite ≥ 3.45, one file `budget.db`. The backend is the only writer |
| Pragmas | `journal_mode=WAL`, `foreign_keys=ON`, `synchronous=NORMAL`, `busy_timeout=5000` |
| Tables | `STRICT` tables. Integer surrogate PKs (`id INTEGER PRIMARY KEY`) |
| Money | `INTEGER` minor units + `currency TEXT` (ISO 4217). Never REAL |
| Rates / prices / units | `TEXT` decimal strings (parsed as Python `Decimal`), e.g. `'97.1234'` |
| Dates | `TEXT 'YYYY-MM-DD'`. Months `TEXT 'YYYY-MM'`. Timestamps `TEXT` UTC ISO-8601 |
| Enums | `TEXT` + `CHECK (col IN (...))` |
| Soft delete | Reference data (accounts, categories, projects…) is **archived** (`archived_at`), never deleted once used. Transactions can be deleted, and the audit log keeps the history |
| Audit columns | `created_at`, `created_by`, `updated_at`, `updated_by` on all user-editable tables (omitted below for brevity) |
| Migrations | Alembic, one migration per change, checked in. Never edit the schema by hand |
| Reporting currency | `setting('reporting_currency') = 'EUR'`. `*_ref` columns are in this currency |

## 2. Entity overview

```
user ─┐
      └─ (created_by on everything)

currency ── fx_rate

account ──< txn_leg >── txn ──< txn_split >── category (2-level)
                         │           ├──── project
                         │           ├──── debt        (principal part)
                         │           ├──── earmark
                         │           └──── asset       (capitalised purchase)
                         └── import_row (origin)

debt ──< debt_rate_period          asset ──< asset_valuation
debt ──< debt_balance_snapshot     asset >── debt (e.g. mortgage ↔ house)

security ──< security_price
account(investment) ──< investment_trade >── security

budget_template_line   budget_line (per month)
import_batch ──< import_row ──> ai_suggestion
audit_log, setting
```

## 3. Users & settings

```sql
CREATE TABLE user (
  id            INTEGER PRIMARY KEY,
  email         TEXT NOT NULL UNIQUE,
  display_name  TEXT NOT NULL,
  password_hash TEXT NOT NULL,                 -- argon2id
  totp_secret   TEXT,                          -- encrypted at rest; NULL = 2FA off
  locale        TEXT NOT NULL DEFAULT 'en' CHECK (locale IN ('en','ru')),
  role          TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('admin','member')),
  is_active     INTEGER NOT NULL DEFAULT 1
) STRICT;

CREATE TABLE auth_session (                    -- refresh tokens (web cookie + Android)
  id            INTEGER PRIMARY KEY,
  user_id       INTEGER NOT NULL REFERENCES user(id),
  token_hash    TEXT NOT NULL UNIQUE,
  client        TEXT NOT NULL CHECK (client IN ('web','android')),
  created_at    TEXT NOT NULL,
  expires_at    TEXT NOT NULL,
  revoked_at    TEXT
) STRICT;

CREATE TABLE setting (                         -- household-wide key/value
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL                          -- JSON
) STRICT;
```
Examples of settings: `reporting_currency`, `conversion_cost_category_id` (NULL means conversion cost stays in the NW bridge), `ai_model`, `cutover_date`.

## 4. Currencies & FX

```sql
CREATE TABLE currency (
  code        TEXT PRIMARY KEY,                -- 'EUR','RUB','USD'
  name        TEXT NOT NULL,
  symbol      TEXT NOT NULL,                   -- '€','₽','$'
  minor_units INTEGER NOT NULL DEFAULT 2       -- RUB 2, but UI shows 0 decimals
) STRICT;

CREATE TABLE fx_rate (
  date      TEXT NOT NULL,
  base      TEXT NOT NULL REFERENCES currency(code),   -- always reporting currency (EUR)
  quote     TEXT NOT NULL REFERENCES currency(code),
  rate      TEXT NOT NULL,                             -- 1 base = rate quote
  source    TEXT NOT NULL CHECK (source IN ('ecb','cbr','manual')),
  PRIMARY KEY (date, base, quote)
) STRICT;
```
Rules:
- **Rate lookup:** the rate for date *d* is the latest row with `date ≤ d`. Weekends and holidays fall back to the previous business day.
- EUR/RUB comes from the Central Bank of Russia (ECB stopped publishing RUB in March 2022). Other pairs come from the ECB.

## 5. Accounts

```sql
CREATE TABLE account (
  id               INTEGER PRIMARY KEY,
  name             TEXT NOT NULL UNIQUE,       -- 'ABN', 'Bunq', 'Sparen ABN', 'Rubles', 'Cash', 'Credit card'
  type             TEXT NOT NULL CHECK (type IN
                     ('current','savings','cash','credit_card','investment')),
  currency         TEXT NOT NULL REFERENCES currency(code),
  institution      TEXT,                       -- 'ABN AMRO', 'bunq', 'ICS'
  external_ref     TEXT,                       -- IBAN / card no. (masked) — used to match imports
  opening_date     TEXT NOT NULL,
  opening_balance  INTEGER NOT NULL DEFAULT 0, -- minor units at opening_date
  include_in_net_worth INTEGER NOT NULL DEFAULT 1,
  owner_user_id    INTEGER REFERENCES user(id),-- NULL = joint
  sort_order       INTEGER NOT NULL DEFAULT 0,
  archived_at      TEXT
) STRICT;

CREATE TABLE account_reconciliation (          -- "the bank says X on date D"
  id             INTEGER PRIMARY KEY,
  account_id     INTEGER NOT NULL REFERENCES account(id),
  date           TEXT NOT NULL,
  stated_balance INTEGER NOT NULL,
  computed_balance INTEGER NOT NULL,           -- snapshot at time of reconciling
  source         TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual','statement','anchor')),
  adjustment_txn_id INTEGER REFERENCES txn(id) -- created when they differ
) STRICT;

CREATE TABLE account_identifier (             -- how imports recognise own accounts
  id         INTEGER PRIMARY KEY,
  account_id INTEGER NOT NULL REFERENCES account(id),
  kind       TEXT NOT NULL CHECK (kind IN ('iban','account_no','card_last4','other')),
  value      TEXT NOT NULL,                     -- 'NL05ABNA0886956927', '886956927', '4926'
  UNIQUE (kind, value)
) STRICT;
```
Rules:
- **Single currency:** an account holds exactly one currency. A multi-currency bank account is split into several accounts.
- **Derived balance:** balance(d) = `opening_balance + Σ txn_leg.amount` for legs with `txn.date ≤ d`. Legs dated before `opening_date` are rejected.
- **Investment accounts:** an `investment` account's leg balance is its **cash** part. Holdings are valued separately (§11).
- **Reconciliation:** reconciling replaces the sheet's `Balancing` rows. When stated ≠ computed, an `adjustment` txn is created for the difference.

## 6. Categories

```sql
CREATE TABLE category (
  id            INTEGER PRIMARY KEY,
  parent_id     INTEGER REFERENCES category(id), -- NULL = top level; max depth 2
  kind          TEXT NOT NULL CHECK (kind IN ('expense','income')),
  name          TEXT NOT NULL,                   -- user data, e.g. 'Eetwaar', 'VVE'
  name_i18n     TEXT,                            -- optional JSON {"ru":"Продукты","en":"Groceries"}
  default_cost_type TEXT CHECK (default_cost_type IN ('fixed','variable','one_time')),
  description   TEXT,                            -- hint for AI ("AH, Jumbo, Lidl = groceries")
  sort_order    INTEGER NOT NULL DEFAULT 0,
  archived_at   TEXT,
  UNIQUE (parent_id, name)
) STRICT;
```
Rules:
- **Depth and kind:** at most two levels. A subcategory has the same `kind` as its parent.
- **Effective cost type:** the order of precedence is `txn_split.cost_type` → subcategory default → category default → `variable`. It applies to expenses only.
- **Where lines post:** a split may post to a top-level category or to a subcategory. Reports roll subcategories up to their parent.
- **AI hints:** `description` is sent to the AI as guidance for that category.
- **Seed data:** the `Config` sheet list (30 expense, 10 income). Subcategories are seeded from the `Month` sheet (Apt → VVE, Verz, Stroom, Woning belasting, Verisure, Waterschap; Kind → Guitar, Naschool, School, …; Auto → AutoTax, AutoVerz, Fuel, Park, Onderhoud; …).
- **Legacy categories:** `Convert`, `Invest`, `Debt return`, `AptKopen`/`AutoKopen` are **not** seeded as expense categories. They become transfer, investment, debt payment and asset purchase respectively (see [Import.md](Import.md) §5.6).

## 7. Transactions (core ledger)

A transaction is a header with **legs** (money moving in or out of accounts) and **splits** (what the money was for).

```sql
CREATE TABLE txn (
  id            INTEGER PRIMARY KEY,
  date          TEXT NOT NULL,
  kind          TEXT NOT NULL CHECK (kind IN
                  ('expense','income','transfer','debt_payment','debt_drawdown',
                   'investment','asset_purchase','earmark','adjustment','mixed')),
  description   TEXT NOT NULL DEFAULT '',        -- 'AH', 'Buenos aires'
  counterparty  TEXT,                            -- merchant / payee as in bank data
  notes         TEXT,
  fx_diff_ref   INTEGER NOT NULL DEFAULT 0,      -- conversion cost in EUR (transfers only)
  source        TEXT NOT NULL CHECK (source IN ('manual','import')),
  import_row_id INTEGER REFERENCES import_row(id)
) STRICT;
CREATE INDEX ix_txn_date ON txn(date);

CREATE TABLE txn_leg (                           -- money side
  id          INTEGER PRIMARY KEY,
  txn_id      INTEGER NOT NULL REFERENCES txn(id) ON DELETE CASCADE,
  account_id  INTEGER NOT NULL REFERENCES account(id),
  amount      INTEGER NOT NULL,                  -- signed, account currency, ≠ 0
  amount_ref  INTEGER NOT NULL,                  -- EUR at market rate of txn.date
  ref_estimated INTEGER NOT NULL DEFAULT 0,      -- 1 = rate was missing, recompute later
  inferred    INTEGER NOT NULL DEFAULT 0         -- 1 = counterpart leg created from the other side of a transfer, awaiting its own statement row (Import.md §1.1)
) STRICT;
CREATE INDEX ix_leg_account ON txn_leg(account_id);

CREATE TABLE txn_split (                         -- purpose side
  id          INTEGER PRIMARY KEY,
  txn_id      INTEGER NOT NULL REFERENCES txn(id) ON DELETE CASCADE,
  amount      INTEGER NOT NULL,                  -- signed, same currency as the txn legs
  currency    TEXT NOT NULL REFERENCES currency(code),
  amount_ref  INTEGER NOT NULL,
  ref_estimated INTEGER NOT NULL DEFAULT 0,
  -- exactly one target:
  category_id INTEGER REFERENCES category(id),
  debt_id     INTEGER REFERENCES debt(id),       -- principal repayment (+) / drawdown (−)
  earmark_id  INTEGER REFERENCES earmark(id),
  asset_id    INTEGER REFERENCES asset(id),      -- capitalised purchase
  cost_type   TEXT CHECK (cost_type IN ('fixed','variable','one_time')), -- override
  project_id  INTEGER REFERENCES project(id),
  note        TEXT,
  CHECK ((category_id IS NOT NULL) + (debt_id IS NOT NULL)
       + (earmark_id IS NOT NULL) + (asset_id IS NOT NULL) = 1)
) STRICT;
CREATE INDEX ix_split_category ON txn_split(category_id);
CREATE INDEX ix_split_project  ON txn_split(project_id);

CREATE VIRTUAL TABLE txn_fts USING fts5(description, counterparty, notes,
  content='txn', content_rowid='id', tokenize='trigram');  -- search + AI few-shot lookup
```

### 7.1 Invariants (enforced by the service layer)
| Kind | Legs | Splits | Balance rule |
|---|---|---|---|
| expense / income | 1 | ≥ 1 category splits | Σ splits = leg.amount |
| transfer | 2, different accounts | none | Same currency: leg1 = −leg2. Different currency: conversion, `fx_diff_ref = Σ leg.amount_ref` |
| debt_payment | 1 (−) | 1 debt split (principal) + 0..n category splits (interest, fees) | Σ splits = leg.amount |
| debt_drawdown | 0..1 (+) | 1 debt split (−), optionally 1 asset split | Σ = 0 over legs + splits |
| investment | 1 (cash leg of investment account) | none; `investment_trade` rows reference the txn | leg = −(units×price) − fees |
| asset_purchase | 1 (−) | asset split (+ optional category split for costs) | Σ splits = leg.amount |
| earmark | 0 | earmark split(s) | virtual, no account movement |
| adjustment | 1 | none | reconciliation difference |
| mixed | 1 | any mix of the above | Σ splits = leg.amount |

- **Splits:** they let one bank row cover several categories (e.g. one supermarket receipt split into Eetwaar and Huishouden).
- **EUR values:** `amount_ref` is computed on write from `fx_rate`. When a missing rate arrives later, a background job recomputes rows flagged `ref_estimated` (see open questions).
- **Income vs expense:** a split's category `kind` decides which it is. A refund (e.g. `Return`) is a positive amount on an expense category or on a dedicated income category (see open questions).

### 7.2 Reporting views (SQL views, read-only)

```sql
-- Every income/expense line with resolved hierarchy and cost type
CREATE VIEW v_ie_line AS
SELECT s.id, t.date, substr(t.date,1,7) AS month, t.kind AS txn_kind,
       COALESCE(c.parent_id, c.id) AS category_id,   -- top-level
       CASE WHEN c.parent_id IS NULL THEN NULL ELSE c.id END AS subcategory_id,
       c.kind AS ie_kind,
       COALESCE(s.cost_type, c.default_cost_type, p.default_cost_type, 'variable') AS cost_type,
       s.amount, s.currency, s.amount_ref, s.project_id, t.description
FROM txn_split s
JOIN txn t      ON t.id = s.txn_id
JOIN category c ON c.id = s.category_id
LEFT JOIN category p ON p.id = c.parent_id;

-- Account movements for balance series
CREATE VIEW v_account_movement AS
SELECT l.account_id, t.date, l.amount, l.amount_ref, t.kind
FROM txn_leg l JOIN txn t ON t.id = l.txn_id;
```
Aggregates (per month, per category) are computed on the fly. At about 3k transactions a year, SQLite answers in milliseconds, so v1 needs no materialised tables.

## 8. Projects

```sql
CREATE TABLE project (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,           -- 'Badkamer', 'Keuken', 'France 2022'
  kind        TEXT NOT NULL DEFAULT 'other' CHECK (kind IN ('renovation','trip','event','other')),
  start_date  TEXT, end_date TEXT,
  budget_amount INTEGER, budget_currency TEXT REFERENCES currency(code),
  notes       TEXT,
  archived_at TEXT
) STRICT;
```
- **Scope:** a project is an extra dimension on splits and doesn't replace the category. A trip can hold Accomodation, Restaraunt, Auto/Fuel and so on.
- **Totals:** project totals are Σ splits by `project_id`, per currency and in EUR.

## 9. Debts ("returns" = repaying them)

```sql
CREATE TABLE debt (
  id              INTEGER PRIMARY KEY,
  name            TEXT NOT NULL UNIQUE,        -- 'Hypotheek', 'AutoKredit', 'Родителям', 'Vita'
  lender          TEXT,
  currency        TEXT NOT NULL REFERENCES currency(code),
  type            TEXT NOT NULL CHECK (type IN ('mortgage','loan','personal','other')),
  repayment_type  TEXT NOT NULL CHECK (repayment_type IN
                    ('annuity','linear','interest_only','free')),  -- 'free' = parents loan
  principal_original INTEGER NOT NULL,
  start_date      TEXT NOT NULL,
  term_months     INTEGER,                     -- NULL for 'free'
  payment_day     INTEGER,                     -- day of month, for expected-payment checks
  interest_category_id INTEGER REFERENCES category(id), -- where interest splits go
  linked_asset_id INTEGER REFERENCES asset(id),-- Hypotheek → Fideliolaan 32
  parent_debt_id  INTEGER REFERENCES debt(id), -- loan parts (leningdelen) of one mortgage
  closed_at       TEXT,
  archived_at     TEXT
) STRICT;

CREATE TABLE debt_rate_period (
  id        INTEGER PRIMARY KEY,
  debt_id   INTEGER NOT NULL REFERENCES debt(id),
  from_date TEXT NOT NULL,
  annual_rate TEXT NOT NULL,                   -- '0.0385'
  UNIQUE (debt_id, from_date)
) STRICT;

CREATE TABLE debt_balance_snapshot (           -- correction / statement from lender
  id       INTEGER PRIMARY KEY,
  debt_id  INTEGER NOT NULL REFERENCES debt(id),
  date     TEXT NOT NULL,
  balance  INTEGER NOT NULL,                   -- outstanding principal, positive
  note     TEXT,
  UNIQUE (debt_id, date)
) STRICT;
```
Rules:
- **Outstanding principal** at date *d* is the latest snapshot ≤ *d* (or `principal_original` at `start_date`), minus principal splits after it, plus drawdowns after it.
- **Payment split:** a debt payment is split by the service into interest (category split to `interest_category_id`, an expense) and principal (debt split, wealth-neutral). The split is suggested from the rate period and schedule, and the user can edit it.
- **Expected schedule:** computed on the fly from rate periods (annuity or linear), not stored. It feeds "expected vs actual" and the payoff forecast.
- **Loan parts:** a multi-part loan is a parent `debt` (grouping only: name, lender, linked asset) with child debts, one per part, each with its own principal, rate periods and repayment type. The **Hypotheek has two parts**: a main part and a small €17,500 part with a different rate. The single monthly bank payment becomes one `debt_payment` txn with a principal split and an interest split **per part**. Reports show the parent as the sum of its parts, with a drill-down.

## 10. Earmarks (kids' money)

```sql
CREATE TABLE earmark (
  id        INTEGER PRIMARY KEY,
  name      TEXT NOT NULL UNIQUE,              -- 'Alisa', 'Max'
  currency  TEXT NOT NULL REFERENCES currency(code),
  target_amount INTEGER,
  archived_at TEXT
) STRICT;
```
- **Movements:** earmark changes are `txn` rows of kind `earmark` with earmark splits and no legs: allocate (+) or release (−). When money is actually spent for the child, the expense txn carries a second split that releases the earmark.
- **Balance:** earmark balance = Σ its splits.
- **Available funds** = Σ account balances − Σ earmark balances.

## 11. Assets & investments

```sql
CREATE TABLE asset (
  id            INTEGER PRIMARY KEY,
  name          TEXT NOT NULL UNIQUE,          -- 'Fideliolaan 32', 'Ленинский 82-55', 'BMW X5', 'Outlander'
  type          TEXT NOT NULL CHECK (type IN ('real_estate','vehicle','other')),
  currency      TEXT NOT NULL REFERENCES currency(code),
  acquired_date TEXT, acquired_value INTEGER,
  disposed_date TEXT, disposed_value INTEGER,
  include_in_net_worth INTEGER NOT NULL DEFAULT 1,
  archived_at   TEXT
) STRICT;

CREATE TABLE asset_valuation (
  id        INTEGER PRIMARY KEY,
  asset_id  INTEGER NOT NULL REFERENCES asset(id),
  date      TEXT NOT NULL,
  value     INTEGER NOT NULL,
  source    TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual','woz','estimate')),
  UNIQUE (asset_id, date)
) STRICT;

CREATE TABLE security (
  id        INTEGER PRIMARY KEY,
  symbol    TEXT NOT NULL,                     -- ticker used by price provider
  isin      TEXT UNIQUE,
  name      TEXT NOT NULL,
  currency  TEXT NOT NULL REFERENCES currency(code),
  price_source TEXT NOT NULL DEFAULT 'manual'
) STRICT;

CREATE TABLE security_price (
  security_id INTEGER NOT NULL REFERENCES security(id),
  date        TEXT NOT NULL,
  price       TEXT NOT NULL,
  PRIMARY KEY (security_id, date)
) STRICT;

CREATE TABLE investment_trade (
  id          INTEGER PRIMARY KEY,
  txn_id      INTEGER NOT NULL REFERENCES txn(id) ON DELETE CASCADE,
  account_id  INTEGER NOT NULL REFERENCES account(id),   -- type = investment
  security_id INTEGER NOT NULL REFERENCES security(id),
  action      TEXT NOT NULL CHECK (action IN ('buy','sell','dividend_reinvest','split')),
  units       TEXT NOT NULL,                  -- signed decimal
  price       TEXT NOT NULL,
  fees        INTEGER NOT NULL DEFAULT 0
) STRICT;
```
Rules:
- **Asset value** at *d* is the latest valuation ≤ *d*.
- **Holdings** at *d* = Σ units per (account, security). Market value = units × latest price ≤ *d*. Investment account value = cash (legs) + market value.
- **Cash dividends:** they are `income` txns into the investment account (category `Dividend`).
- **Investment gain** for the NW bridge = Δ market value − net contributions.

## 12. Budget

```sql
CREATE TABLE budget_template_line (            -- the "Month" sheet
  id          INTEGER PRIMARY KEY,
  category_id INTEGER NOT NULL REFERENCES category(id),  -- category or subcategory
  label       TEXT,                            -- free label, e.g. 'Platfroma C'
  amount      INTEGER NOT NULL,                -- positive = planned spend/income
  currency    TEXT NOT NULL REFERENCES currency(code),
  valid_from  TEXT NOT NULL,                   -- 'YYYY-MM'
  valid_to    TEXT                             -- NULL = open-ended
) STRICT;

CREATE TABLE budget_line (                     -- materialised per month, editable
  id          INTEGER PRIMARY KEY,
  month       TEXT NOT NULL,
  category_id INTEGER NOT NULL REFERENCES category(id),
  amount      INTEGER NOT NULL,
  currency    TEXT NOT NULL REFERENCES currency(code),
  template_line_id INTEGER REFERENCES budget_template_line(id),
  note        TEXT,
  UNIQUE (month, category_id, currency, template_line_id)
) STRICT;
```
- **Generating a month:** creates `budget_line` rows from template lines valid in that month. The lines can then be edited, and one-off plan lines added.
- **Plan vs actual:** compared per top-level category (lines on subcategories roll up) and per currency. EUR totals use the month-end rate.

## 13. Import & AI

```sql
CREATE TABLE import_batch (
  id          INTEGER PRIMARY KEY,
  source      TEXT NOT NULL CHECK (source IN
                ('abn_mt940','abn_xls','bunq_csv','bunq_mt940','bunq_api',
                 'ics_pdf','gsheet','generic_csv')),
  mode        TEXT CHECK (mode IN ('match','sheet_only')),  -- gsheet only, see Import.md §5.3
  account_id  INTEGER REFERENCES account(id),  -- NULL for gsheet (mapped per row)
  file_name   TEXT,
  file_sha256 TEXT,                            -- blocks re-uploading the same file
  status      TEXT NOT NULL CHECK (status IN ('parsing','reviewing','committed','discarded','failed')),
  stats       TEXT,                            -- JSON: rows, duplicates, committed, skipped
  error       TEXT
) STRICT;

CREATE TABLE import_row (
  id            INTEGER PRIMARY KEY,
  batch_id      INTEGER NOT NULL REFERENCES import_batch(id) ON DELETE CASCADE,
  row_no        INTEGER NOT NULL,
  raw           TEXT NOT NULL,                 -- original row as JSON
  date          TEXT NOT NULL,
  amount        INTEGER NOT NULL,
  currency      TEXT NOT NULL,
  account_id    INTEGER REFERENCES account(id),
  counterparty  TEXT,
  description   TEXT,
  external_id   TEXT,                          -- bank transaction id if any
  dedupe_key    TEXT NOT NULL,                 -- sha256(account|date|amount|norm(desc)|nth)
  status        TEXT NOT NULL CHECK (status IN
                  ('new','duplicate','suggested','accepted','skipped','committed')),
  proposed      TEXT,                          -- JSON: user-edited draft of txn (kind, splits…)
  stated_balance INTEGER,                      -- balance after this row, if the source has it
  matched_row_id INTEGER REFERENCES import_row(id), -- sheet row ↔ bank row (match mode)
  match_score   TEXT,
  generated     INTEGER NOT NULL DEFAULT 0,    -- synthetic leg (e.g. card repayment without PDF)
  txn_id        INTEGER REFERENCES txn(id)     -- set when committed
) STRICT;
CREATE UNIQUE INDEX ux_import_external ON import_row(account_id, external_id)
  WHERE external_id IS NOT NULL AND status = 'committed';

CREATE TABLE import_rule (                      -- account/exception rules for the sheet (Import.md §5.5)
  id        INTEGER PRIMARY KEY,
  source    TEXT NOT NULL,                      -- 'gsheet' (others later)
  priority  INTEGER NOT NULL,
  match     TEXT NOT NULL,                      -- JSON {date_from,date_to,category,desc_regex,currency}
  action    TEXT NOT NULL,                      -- JSON {account_id,kind,counter_account_id,...}
  note      TEXT,
  is_active INTEGER NOT NULL DEFAULT 1
) STRICT;

CREATE TABLE ai_suggestion (
  id            INTEGER PRIMARY KEY,
  import_row_id INTEGER NOT NULL REFERENCES import_row(id) ON DELETE CASCADE,
  model         TEXT NOT NULL,
  kind          TEXT NOT NULL,                 -- expense/income/transfer/debt_payment…
  category_id   INTEGER REFERENCES category(id),
  cost_type     TEXT,
  project_id    INTEGER REFERENCES project(id),
  transfer_account_id INTEGER REFERENCES account(id),
  confidence    TEXT NOT NULL,                 -- '0.0'–'1.0'
  rationale     TEXT,
  created_at    TEXT NOT NULL
) STRICT;

CREATE TABLE ai_call_log (                     -- cost/usage audit
  id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, model TEXT NOT NULL,
  batch_id INTEGER REFERENCES import_batch(id),
  input_tokens INTEGER, output_tokens INTEGER, duration_ms INTEGER, error TEXT
) STRICT;
```
Staging keeps the ledger clean: imported data reaches `txn` **only** after a user confirms it (D14). Uploaded files are not kept after parsing. `raw` holds what is needed. Formats, matching and the historical migration are specified in [Import.md](Import.md).

## 14. Audit

```sql
CREATE TABLE audit_log (
  id         INTEGER PRIMARY KEY,
  at         TEXT NOT NULL,
  user_id    INTEGER REFERENCES user(id),
  entity     TEXT NOT NULL,                    -- 'txn','account',…
  entity_id  INTEGER NOT NULL,
  action     TEXT NOT NULL CHECK (action IN ('create','update','delete')),
  diff       TEXT                              -- JSON before/after
) STRICT;
```

## 15. Derived figures (definitions)

| Figure | Definition at date *d* (EUR) |
|---|---|
| Funds | Σ balance_ref of accounts with `include_in_net_worth`, excluding investment holdings |
| Available funds | Funds − Σ earmark balances |
| Investments | Σ holdings market value + investment account cash |
| Assets | Σ latest valuation of active assets |
| Debts | Σ outstanding principal of open debts |
| **Net worth** | Funds + Investments + Assets − Debts |
| Month income / costs | Σ `v_ie_line.amount_ref` by `ie_kind` for the month |
| Month cash-flow | Income − costs − debt principal − net transfers into investments |

`balance_ref` values a native balance at the rate of *d*, not as a sum of historic `amount_ref` values. The difference between the two is the FX revaluation.

## 16. Backups & retention
- **Hourly:** `sqlite3 .backup` (online, consistent) to a local snapshot.
- **Nightly:** the snapshot is encrypted (age/gpg) and uploaded off-site (S3-compatible). 30 daily and 12 monthly copies are kept.
- **Tested restore:** a restore script is included and exercised in CI against the latest backup.

## 17. Open questions — data
1. **Refunds (`Return`):** keep them as an income category as today, or book them as negative expense in the original category, so Kleding shows net spend after returns?
2. **Interest on savings (`Bonus` + "rente"):** move it to its own income subcategory `Interest`?
3. **Missing FX rate** (e.g. entry for today before the daily fetch): use the latest known rate and mark `amount_ref` as estimated for later recompute, or block saving?
4. **USD:** are there any USD accounts or assets today, or is USD historical only?
