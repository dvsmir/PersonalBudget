# Frontend — Web (v1) and Android (v2)

Part of the [Spec](Spec.md). Talks only to the REST API in [Backend.md](Backend.md). It holds no business logic: every figure shown is computed by the backend.

## 1. Principles
- **Thin client:** totals, balances, FX and splits all come from the API. The client formats and displays them. This keeps web and Android consistent.
- **Currency toggle everywhere:** *EUR* (reference) or *native* (€ and ₽ side by side, like the sheet). The choice is remembered per user.
- **Mobile-first responsive:** quick manual entry and the dashboard must work well on a phone browser until the Android app exists.
- **Bilingual:** EN and RU UI, switchable per user. Category, account and project names are shown as the user wrote them (Dutch names stay Dutch). Optional `name_i18n` is used if present.
- **Fast entry:** adding a transaction takes ≤ 5 taps or keystrokes for the common case.

## 2. Tech stack

| Concern | Choice |
|---|---|
| Build | Vite + React 18+ + TypeScript (strict) |
| Routing | React Router |
| Server state | TanStack Query (caching, invalidation after mutations) |
| API client | Generated from OpenAPI (`openapi-typescript` + `openapi-fetch`) |
| UI kit | Mantine (tables, forms, date pickers, dark mode, good mobile support) |
| Tables | TanStack Table (virtualised for long transaction lists) |
| Charts | Apache ECharts (`echarts-for-react`): stacked bars, donuts, line/area, treemap |
| Forms | react-hook-form + zod |
| i18n | i18next + react-i18next. `Intl.NumberFormat` / `Intl.DateTimeFormat` for money and dates |
| Money | Decimal strings from the API. Formatting only, no arithmetic on floats |
| Tests | Vitest + Testing Library. Playwright for key flows (login, add txn, import review) |

## 3. Navigation & pages

```
┌ Dashboard  (home)
├ Year
├ Transactions
│   └ + Add (also a floating button on every page)
├ Import
│   └ Batch review
├ Budget
├ Wealth
│   ├ Accounts
│   ├ Debts
│   ├ Assets & investments
│   └ Earmarks
├ Projects
└ Settings  (categories, users, currencies/FX, AI, profile, language)
```

### 3.1 Dashboard (home) — current month by default, with a month picker
Top to bottom:
1. **Month header:** income, costs, balance (income − costs) and cash-flow, with Δ vs the previous month and vs the average of the last 12 months. Currency toggle.
2. **Costs by category:** horizontal bar or donut, top-level categories. Clicking one drills into subcategories, and a second click opens the transaction list filtered to it.
3. **Costs by type:** fixed / variable / one-time as a stacked bar with amounts and %.
4. **Income by category:** small bar list.
5. **Budget plan vs actual:** a progress bar per category (plan, actual, remaining). Over budget is highlighted. Unplanned categories are listed below.
6. **Account balances:** grouped by currency, with an EUR total. Available funds = funds − earmarks. The last reconciliation date is shown per account.
7. **Net worth:** the current value plus a 12/24/all-months line chart (funds, investments, assets, debts, net worth), and a small net-worth-bridge waterfall for the month (income − expenses, FX, asset revaluation, investment gains).
8. **Alerts:** items awaiting import review, expected debt payment missing, estimated FX rates.

### 3.2 Year overview
Mirrors the sheet's "Dashboard YYYY", with a year picker:
- **Month table:** month rows × Income / Costs / Balance / Funds at month-end. Native mode shows € and ₽ columns; EUR mode shows a single column.
- **Category table:** income and cost categories × sum and avg/month (sortable), with expandable subcategories.
- **Category × month heatmap:** costs, spotting seasonal spend.
- **Charts:** monthly income vs costs bars, and cumulative balance.
- **Compare years:** the same category across years. Not a dashboard widget in v1, but reachable from the category trend view.

### 3.3 Transactions
- **List:** virtualised table with columns date, description/counterparty, category › subcategory, cost type, project, account, amount (native) and EUR amount. Splits are shown as expandable rows.
- **Filters:** date range, account, category (tree multi-select), project, kind, cost type, text search, amount range. Filters are kept in the URL so views can be shared or bookmarked.
- **Bulk edit:** select rows, then set category / subcategory / cost type / project.
- **Totals bar** for the current filter (per currency + EUR).
- **Row click** opens an edit drawer with the full editor (§3.4).

### 3.4 Add / edit transaction
One form with a **kind switcher**:

| Kind | Fields |
|---|---|
| Expense / Income | Date (default today), amount, account (default last used; currency follows the account), category → subcategory (searchable, recent first), cost type (pre-filled from default, override), project, description, notes. "Split" button adds lines that must sum to the total |
| Transfer | From account, to account, amount out. **If the currencies differ**, amount in and the implied rate are shown next to the market rate for the date |
| Debt payment | Debt, account, amount. Interest/principal split pre-filled via `suggest-debt-split`, editable |
| Investment | Account, security, buy/sell, units, price, fees |
| Earmark | Earmark (Alisa/Max), allocate/release, amount |

Also:
- **Phone layout:** big amount keypad, category chips for the 8 most used categories, and "save & add another".
- **Keyboard (desktop):** `n` opens a new transaction, `Enter` saves.

### 3.5 Import
1. **Upload:** drop a file. The source is auto-detected (override possible) and the account is detected or chosen. A generic CSV opens a column-mapping step whose mapping can be saved as a profile.
2. **Batch review:** the core screen.
   - The table of rows shows the parsed data, a status chip (new / duplicate / transfer detected / debt payment) and the **AI suggestion** (category, cost type, project, confidence dot, rationale on hover).
   - Rows can be edited inline, the same as the transaction editor, with split support.
   - Per row: *Accept*, *Skip*, or *Mark duplicate*. In bulk: accept all selected, accept all with high confidence, or accept all matching a filter (needed for the Google Sheet backfill).
   - Duplicates are collapsed by default. Detected transfers show both legs paired.
   - The **Commit** button shows a summary (n expenses, n income, n transfers, totals per account) before confirming.
3. **History:** a list of batches with source, date, row counts and who imported them. Discard is available for batches that were never committed.

### 3.6 Budget
- **Month grid:** categories (expandable to subcategories) × plan / actual / remaining, with inline edit of plan amounts. Totals are split into fixed, variable and one-time.
- **Template editor:** the "Month" sheet equivalent. Line items per category with amount, currency and valid-from/to, plus "apply to future months".
- **Year view:** plan vs actual per month, per category.

### 3.7 Wealth
- **Accounts:** a card per account with balance, a sparkline and the last reconciliation. The detail view shows the balance chart, transactions, the **Reconcile** action (enter the bank balance; it shows the difference and creates an adjustment) and edit/archive.
- **Debts:** a card per debt with outstanding balance, repaid this year, a progress bar (repaid / original), the next expected payment and the payoff date. The detail view shows the schedule (expected vs actual), rate periods, snapshots, the linked asset and equity (asset value − debt).
- **Assets & investments:** the asset list with the latest value and the date of that valuation, plus a "Add valuation" quick action and a value history chart. Investment holdings are shown per account (units, price, value, gain).
- **Earmarks:** Alisa and Max balances, their movements, and allocate/release actions.

### 3.8 Projects
The list shows each project with total spent vs budget and its dates. The detail view gives a breakdown by category, a timeline and the transaction list. A project can also be assigned from the Transactions bulk edit.

### 3.9 Settings
- **Categories:** tree editor (drag to reorder or reparent within the 2 levels), default cost type, AI hint text, archive, merge.
- **Users:** admin only. Invite, reset password, role.
- **Profile:** language, password, TOTP 2FA setup (QR code), default currency mode.
- **Currencies & FX:** list of rates and manual override for a date.
- **AI:** model, monthly usage/cost, a test on a sample.
- **Data:** export CSV/JSON, backup status.

## 4. Cross-cutting UI behaviour

| Topic | Behaviour |
|---|---|
| Money formatting | Per locale: `€1.234,56` (nl/en style chosen by user) and `1 234 ₽`. RUB shown without decimals. Negative costs are shown as positive numbers in cost contexts and coloured |
| Dates | Displayed as `dd-MM-yyyy` (as in the sheet) or per locale. The week starts Monday |
| Loading / errors | Skeletons for dashboards. Problem-JSON errors mapped to translated messages. Retry on network errors |
| Concurrency | On `409`, reload the entity and show "changed by Jane — review and save again" |
| Theme | Light/dark following the system, with a manual toggle |
| Accessibility | Keyboard navigable, chart data also available as a table toggle, colour not the only signal (over-budget also shows an icon) |
| Security | Access token kept in memory only, refresh via httpOnly cookie. Auto-logout after inactivity (configurable, default 30 min). No financial data in `localStorage` |
| Offline | Not in v1 (the web app needs a connection) |

## 5. Android (v2) — design constraints set now
- **Stack:** Kotlin + Jetpack Compose. The API client is generated from the same OpenAPI schema.
- **v2 scope:** dashboard (month), quick add, transaction list, import review, balances. Heavy admin (categories, budget template) stays web-only.
- **Auth:** login with `client=android`, refresh token in the Keystore, biometric unlock.
- **Possible later:** an offline queue for quick-add, which would need idempotency keys on `POST /txns`. The API accepts an `Idempotency-Key` header from v1 so this is ready.

## 6. Open questions — frontend
1. **Number format:** do you prefer `€1,234.56` (as in the sheet) or Dutch style `€ 1.234,56`? Should it follow the UI language or be a separate setting?
2. **Dashboard sign convention:** show costs as negative (like the sheet, `-€8,313.72`) or as positive amounts in cost widgets?
3. **Quick-add defaults:** should a phone entry default to the *Cash* account or to the last used one?
4. **Year overview parity:** anything in the current "Dashboard YYYY" you rely on that isn't covered above? One example is the right-hand column that repeats category totals as positive numbers, probably for a chart.
