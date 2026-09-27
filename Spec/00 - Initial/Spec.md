# Budget — Technical Specification (overview)

Source: [Intent](Intent.md) and the current Google Sheet "Бюджет" (sheets 2019 → 2026, reviewed 2026-09-27).

This file holds the decisions and cross-cutting rules. Each layer is designed in its own document:

| Layer | Document |
|---|---|
| Data storage (SQLite) | [Data.md](Data.md) |
| Backend service (FastAPI) | [Backend.md](Backend.md) |
| Frontend (React web; Android later) | [Frontend.md](Frontend.md) |
| Import (sources, historical migration) | [Import.md](Import.md) |

---

## 1. What the current sheet tells us

| Observation in the sheet | Consequence for the app |
|---|---|
| Separate `€` and `₽` columns everywhere, never converted (USD in older years) | Multi-currency is core. Amounts stored in native currency and converted to EUR for totals |
| Transactions have no account; `Balancing` rows fix the totals | Every transaction belongs to an account, and balances are derived. Reconciliation creates an explicit adjustment |
| `Convert`, `Invest` and `Debt return` are booked as costs | These become **transfers** or **debt repayments**, not income or expense |
| Flat Dutch category list (`Config`), with the description used as a subcategory (Apt → VVE, Stroom) | Two-level categories: category → subcategory |
| `Month` sheet is a fixed monthly plan per category with line items | Monthly budget plan with a template, shown as plan vs actual |
| State block: Funds / Debts / Assets, all typed in by hand | Accounts (derived), debts (loan model), assets (valuation snapshots) and a net-worth history |
| Alisa / Max under Debts | **Earmarks**: money set aside for the kids, a liability inside our own funds |
| Hypotheek booked fully as a cost; mortgage schedule kept on a side sheet | Loan model. Each payment is split into interest (cost) and principal (reduces the debt) |
| Renovations and Vacations sheets | **Projects**: a transaction keeps its category and can also belong to a project |
| Income: JB Salaris, Psychoanalysis (EUR and RUB), Bonus/rente, Dividend, Return, Allowance, Apts Spb | Income categories, same two-level structure |
| "Credit - …" rows | A credit card account |
| One "Dashboard YYYY" per year | A single app with year/month selectors and multi-year data |

## 2. Decisions log

| # | Topic | Decision |
|---|---|---|
| D1 | Backend | Python 3.12+, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2 |
| D2 | Frontend | React + TypeScript + Vite. Android client in v2 against the same REST API |
| D3 | Hosting | Cloud VPS in Docker, behind a TLS reverse proxy (Caddy) |
| D4 | Users | One household, several logins (Dima, Jane). Every change records its author |
| D5 | Currency | Native amounts plus EUR as the reporting currency. Conversions never change wealth or inflate expenses (see §3) |
| D6 | Accounts | Every transaction has an account. Balances are derived from opening balance + transactions |
| D7 | Transfers | Own-account transfers, credit-card repayments and currency conversions are *transfers*, excluded from income and expense |
| D8 | Categories | Two levels (category → subcategory), separately for expense and income |
| D9 | Cost type | Fixed / variable / one-time. The subcategory has a default (falling back to the category), and a transaction can override it |
| D10 | Budget | Monthly plan vs actual per category or subcategory, generated from a template |
| D11 | Debts | Loan model (principal, rate periods, term, repayment type). Payments are split into interest and principal. "Returns" in the Intent = repayment of debts. The Hypotheek has two loan parts with different rates (one small, €17,500) |
| D12 | Assets | Manual dated valuations for real estate, cars and other assets. Investment holdings are priced automatically |
| D13 | Imports | ABN AMRO (current + Invest), Bunq (export and API), ABN/ICS credit card statement (PDF), Google Sheet (historical) and manual input. Details in [Import.md](Import.md) |
| D14 | AI | AI (Claude) suggests the category for **every** imported row, and a human always confirms. There is no rules engine |
| D15 | Projects | Optional project per transaction line (e.g. "Badkamer", "France 2022"), with totals and an optional budget |
| D16 | Language | Translated UI in EN + RU, chosen per user. Category names are user data (the Dutch names are kept) |
| D17 | Rubles | One "Rubles" account holds all RUB operations (VTB no longer used). Entered manually or imported from the sheet |
| D17a | History | Import from 21-11-2020 (move to NL) into the **real accounts**: mostly ABN, exceptions in Import.md. Bank statements from March 2025 are the ledger backbone, and the sheet is matched onto them. Earlier years are sheet-only, balanced with yearly anchors. No legacy/virtual accounts |
| D18 | Earmarks | Kids' money (Alisa, Max) is an earmark, a virtual allocation of household funds. It lowers **available funds** only, never net worth |
| D19 | Dashboard | Current month I/E by category and cost type, year overview, net worth with history, budget plan vs actual, account balances |

## 3. Cross-cutting rules

### 3.1 Money
- Amounts are stored as **signed integers in minor units** (cents, kopecks) together with an ISO 4217 currency code. No floats anywhere.
- Sign is seen from the account: negative means money leaves the account.
- EUR is the **reporting currency**, configurable but not expected to change. Each money line stores both `amount` (native) and `amount_ref` (EUR at the posting rate).

### 3.2 Currency conversion invariants
The goal is that converting money **neither changes wealth nor shows up as spending**. It is enforced like this:

1. A conversion is a `transfer` with two legs in different currencies, e.g. ABN −€1,000 and Rubles +₽95,000. Neither leg has a category, so income and expense are untouched.
2. The **executed rate** is implied by the two legs (95.00). The market rate for that day comes from the FX table (e.g. 97.00).
3. The EUR value of each leg is computed at the market rate: −€1,000.00 and +€979.38. The small gap (−€20.62) is stored on the transaction as `fx_diff_ref` and reported as **conversion cost** in the net-worth bridge, not in expense categories. An optional setting books it into an expense category instead.
4. RUB spending (and any non-EUR line) is valued in EUR at **that day's market rate** (decided). It counts as an expense **once**, when spent, never at conversion.
5. Rate movements change the EUR value of RUB balances over time. They are reported as **FX revaluation** in the net-worth bridge, not as income or expense.

Net-worth bridge for any period:

```
NW(start) + income − expenses
          + FX revaluation + conversion cost
          + asset revaluation + investment gains
          = NW(end)
```
Transfers, debt principal repayments and earmark movements are **wealth-neutral**. They move value between buckets but don't change net worth.

### 3.3 Classification of every money movement

| Kind | Example | Counts as I/E? | Effect |
|---|---|---|---|
| Expense | Albert Heijn | Expense | Account ↓ |
| Income | JB Salaris | Income | Account ↑ |
| Transfer | ABN → Sparen Bunq, EUR → RUB, repaying the credit card | No | Between accounts |
| Debt payment | Hypotheek €1,632 | Interest part = expense, principal part = no | Account ↓, debt ↓ |
| Debt drawdown | New auto credit | No | Account ↑ (or asset ↑), debt ↑ |
| Investment buy/sell | Buy ETF in Invest ABN | No (fees = expense) | Cash ↔ holdings |
| Asset purchase (capitalised) | Buy a car | No (optional) | Account ↓, asset ↑ |
| Adjustment | Reconciliation difference | Shown separately | Account ± |

### 3.4 Dates and time
- Transaction dates are local calendar dates (`YYYY-MM-DD`), with no time zone.
- Audit timestamps are UTC ISO-8601.
- Months are `YYYY-MM`. The reporting period is the calendar month.

### 3.5 Security & privacy
- Financial data sits on a public VPS: HTTPS only, hashed passwords (argon2id), optional TOTP 2FA, rate-limited login, httpOnly cookies for the web and bearer tokens for Android.
- Nightly encrypted off-site backups of the SQLite database (see Backend).
- AI calls send the transaction description, amount, date and category list, never account numbers or IBANs. See Backend §AI.

## 4. Scope and phasing

| Phase | Content |
|---|---|
| v1.0 | Data model, auth, accounts, manual entry, categories, transfers/conversions, ABN + credit card + Bunq CSV import, Google Sheet import, AI review queue, dashboards (month, year, balances, net worth), budget, debts, assets, earmarks, projects, EN/RU |
| v1.x | Bunq API sync, automatic investment prices, recurring-transaction suggestions |
| v2 | Android app (same API). Offline entry with sync if needed |

## 5. Resolved questions

| Question | Answer |
|---|---|
| Where does historical sheet data live? | Under the real accounts (mostly ABN). Exceptions and balance anchors are in [Import.md](Import.md) |
| Do earmarks reduce net worth? | No, only available funds |
| How is RUB spending valued in EUR? | At the market rate of the transaction date |
| Is the Hypotheek one loan? | No, two loan parts with different rates; one of them is €17,500 |

Layer-specific open questions are listed at the end of each layer document.

## 6. Implementation notes (v1 build, 2026-09-27)

Where the first build differs from, or extends, the layer documents:

| Area | Note |
|---|---|
| Money in the API | Amounts are **integers in minor units** plus a currency code (not decimal strings). They are exact in JSON and JS and simpler for the Android client |
| FX source for RUB | cbr.ru is unreachable from EU hosts. The fetcher tries CBR first and falls back to the `cbr-xml-daily.ru` mirror of the official CBR rates. Providers fail independently |
| Schema additions | `import_row.counterparty_iban`, `import_row.matched_txn_id`, `import_batch.ai_batch_id`; `debt.lender_identifier` and repayment type `group` (parent of loan parts); trade action `opening`; txn source `generated` (migration balancing); valuation source `import`; `ai_call_log.cache_read_tokens`; `account_reconciliation.note` |
| AI | Synchronous chunks of 40 rows through `messages.parse` (structured output) with a cached system prompt. The Message Batches API path for the sheet backfill is not built yet. No refusal fallback: a refused chunk leaves its rows for manual review |
| Imports not built yet | Generic CSV with column mapping, bunq API sync, automatic investment prices (manual prices supported) |
| Frontend | Charts are ECharts with the validated dataviz palette. There is no offline mode. The 2FA set-up shows the otpauth URI and secret (no QR code yet) |
| Deployment | Docker files written and the compose config validated, but the images have not been built yet (Docker Desktop was not running) |
