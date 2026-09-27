# Import — sources, pipeline and historical migration

Part of the [Spec](Spec.md). Storage tables are in [Data.md](Data.md) §13. The AI categoriser is in [Backend.md](Backend.md) §6. Samples are in [`../samples/`](../samples/).

**Principle:** every transaction, including history migrated from the Google Sheet, lives under the **real account** it belongs to. Historical data is not treated differently once imported. There are no legacy or virtual accounts.

---

## 1. Own accounts & identifiers

The importer recognises own accounts by identifier. This is what detects transfers.

| Account | Type | Currency | Identifier(s) seen in samples | Status |
|---|---|---|---|---|
| ABN (current) | current | EUR | IBAN `NL05ABNA0886956927`, short no. `886956927` | Confirmed (ABN export) |
| ABN Invest | investment | EUR | `109047850` | Confirmed (Invest export) |
| Credit card (ABN / ICS) | credit_card | EUR | Card `…4926`. ICS IBAN `NL75ABNA0844997056` is the payee of repayments | Confirmed (PDF) |
| Sparen ABN (joint, "D.V. Smirnov and/or E. Smirnova") | savings | EUR | `NL61ABNA0119875748` | Confirmed |
| Sparen Bunq | savings | EUR | `NL42BUNQ2094599752` | Confirmed |
| Cash | cash | EUR | none | Confirmed. ATM withdrawals in, cash spending out |
| Rubles | current | RUB | none | Manual + sheet |

Each account can carry several identifiers (IBAN, short account number, card last-4). They are stored in `account_identifier` (§8).

**Ignored:** `NL77BUNQ2084045134` is an old account and is not tracked. It appears as counterparty on Sparen Bunq (small top-ups in 2023–2024). Those rows are booked as an `adjustment` "From old Bunq account": wealth coming in from an untracked own account, **not income**. The sheet's "Bunq" line (always €0) refers to it and is ignored as well.

### 1.1 Savings accounts: transfer-heavy by nature
Almost every movement on the three savings accounts is a transfer to or from another own account. The rules below keep them correct without manual work:
- **Auto-pairing:** a row whose counterparty is an own account becomes a `transfer`. It is classified before AI and **pre-accepted** in review (shown collapsed, bulk-confirmable). No category is ever asked for.
- **Both legs, one transfer:** a transfer ABN → Sparen ABN appears in *both* statements. Whichever file is imported first creates the transfer, with the other side as an **inferred leg** (`txn_leg.inferred = 1`). When the other statement arrives, its row is matched by account, amount and date ±3 days: it *confirms* the inferred leg instead of creating a second transfer. Unconfirmed inferred legs are listed in the reconciliation report.
- **Interest** arrives on the savings account that earns it: ABN rente → Sparen ABN, Bunq rente → Sparen Bunq. It is booked as income `Interest` there.
- **Anything else** on a savings account (rare) goes through normal AI and review.

## 2. Common pipeline

```
upload ─► detect format ─► parse ─► resolve account (identifier in file, else chosen in UI)
      ─► dedupe ─► classify (own-account transfer / card repayment / ATM / debt / investment)
      ─► AI suggestion for the rest ─► REVIEW ─► commit (one DB transaction) ─► balance check
```
- **Nothing reaches the ledger without review** (D14). Bulk-accept exists for large batches.
- **Balance check after commit:** when the source carries balances (MT940 `:62F:`, ABN XLS `Eindsaldo`, ICS "Nieuw openstaand saldo"), the derived account balance must equal the stated one. The balance is stored as an `account_reconciliation` checkpoint. A mismatch blocks nothing but shows a red flag with the difference and date.
- **Idempotent:** re-uploading a file (same SHA-256) is rejected. Overlapping periods are safe because rows are deduped (§6).

## 3. Sources

### 3.1 ABN AMRO: current account and Invest

**Formats.** ABN offers MT940 and XLS (and TXT). No CSV.

| | MT940 (**primary**) | XLS (secondary) |
|---|---|---|
| Structure | SWIFT standard: `:25:` account (IBAN), `:60F:` opening balance, `:61:` entry (value date, booking date, D/C, amount), `:86:` description, `:62F:` closing balance | `Sheet0`, one row per txn: `Rekeningnummer, Muntsoort, Transactiedatum (YYYYMMDD), Rentedatum, Beginsaldo, Eindsaldo, Transactiebedrag, Omschrijving` |
| Balance check | Per statement (opening/closing) | Per row (running balance) |
| Parser | `mt-940` library + our `:86:` parser | `xlrd` (the file is legacy BIFF `.xls`) |
| Multi-account | Yes, several accounts per file | One account per file |

Both formats carry the same description text, parsed into structured fields:

| Pattern (from sample) | Meaning | Parsed into |
|---|---|---|
| `/TRTP/SEPA OVERBOEKING/IBAN/…/NAME/…/REMI/…/EREF/…` | SEPA transfer | counterparty IBAN + name, remittance info, end-to-end ref |
| `/TRTP/SEPA Incasso algemeen doorlopend/CSID/…/NAME/…/MARF/…/REMI/…` | Direct debit (Verisure, Zorgverzekeraar, Belastingdienst, KinderRijk, Vattenfall, Waternet) | creditor name, mandate id (MARF). **Mandate id is a strong signal for recurring fixed costs** |
| `/TRTP/iDEAL/Wero/IBAN/…/NAME/…/REMI/…` | iDEAL online payment (Amazon, Meeting Up) | merchant name, order ref |
| `BEA, Google Pay  <merchant>,PAS502  NR:…, dd.mm.yy/hh:mm  <city>` | Card/phone payment in a shop | merchant, city, time, **card id (PAS502 / PAS492 → which person paid)** |
| `GEA, …` | ATM withdrawal | Proposed as a transfer to **Cash** |
| `ABN AMRO Bank N.V.  BasisPakket …` | Bank fees | Expense → Bank |

**Invest account** (sample `Invest.xls`, same layout; MT940 expected to work too). The description drives investment handling:

| Pattern | Becomes |
|---|---|
| `DEPOSIT INV. FUND <name> FONDSCODE <code> PER dd/mm UNIT <units> @ EUR <price>` | `investment` txn: cash leg −amount, trade **buy** `<units>` of security `<code>` at `<price>`. Fully automatic |
| `DIVIDEND <name> <date> OVER ST <n> PAID WITH <ccy> <per-share> [TAX EUR <x>] CURRENCY RATE …` | `income` → Dividend (security linked, withholding tax kept in notes). `OVER ST <n>` is used to **cross-check holdings** |
| `ABNAMRO Investments  See your invoice for details` | Expense → Bank (investment fees) |
| Inflow from ABN current | Transfer (this replaces the sheet's `Invest` category) |

Positions bought before the first imported statement (Alphabet, Realty Income, BP, Shell, iShares, …) do not appear in the cash statement. **Opening positions** come from the ABN **portfolio export**:
1. Import the current portfolio (security, ISIN, units, cost) as positions **as of the export date**.
2. Walk the imported trades back to the start of the statement period (March 2025). Positions at that date = today's units − buys + sells since then. Those become the opening positions.
3. Check: dividend lines (`OVER ST <n>`) must agree with the derived units on their dates. A disagreement is flagged.

Before March 2025 the Invest account has no statements. There it holds the transfers from the sheet (`Invest` category) as contributions, plus **valuation snapshots** taken from the sheet's State blocks (e.g. "Invest €966", "€3,600", "€4,900"). The NW history stays continuous, and gains before 2025 are the snapshot difference minus contributions.

### 3.2 Bunq

**Formats:** CSV now; MT940 is also offered by Bunq and handled by the same parser.
- **CSV columns:** `Date, Interest Date, Amount, Account, Counterparty, Name, Description`.
- **Values:** dates are ISO, amounts use comma thousands (`15,000.00`). `Account` is our IBAN on every row, so one file may contain several Bunq accounts.
- **No transaction id**, so the dedupe key is used (§6).
- **Transfers:** in the sample almost every row is a transfer from or to ABN current, auto-detected via §1.1. Rows from `NL77BUNQ…` follow the *ignored* rule in §1.
- **API sync:** Bunq API sync is v1.x (Backend §5).

### 3.3 Credit card: ABN AMRO / ICS (PDF statement)

Only a monthly PDF is available, **from August 2024**. It is parsed with `pdfplumber` (text layer).

| Element | Handling |
|---|---|
| Header | Statement date, ICS customer no., previous balance, payments received, new spend, new balance, due date |
| Card sections | "Uw Card met als laatste vier cijfers 4926 / D. SMIRNOV". Several cards per statement are possible. Card last-4 → account (via `account_identifier`), and the holder is kept in notes |
| Rows | `Datum transactie`, `Datum boeking` (Dutch month abbreviations, **no year**: inferred from the statement date, with a Dec→Jan wrap), description, city, country, optional foreign amount, EUR amount, `Af` (debit) / `Bij` (credit) |
| `IDEAL BETALING, DANK U` | Repayment. It pairs with the ABN current row whose counterparty IBAN is `NL75ABNA0844997056` (ICS) → one `transfer` |
| Validation | previous − payments + spend = new balance. The statement closing balance becomes a reconciliation checkpoint |
| Foreign currency | Stored in notes (e.g. `USD 250.00`). The EUR amount is authoritative |
| Date used | **Transaction date** (not booking date) |

⚠ The sheet books card spending on the **repayment date** with a `Credit -` prefix. For example, sheet 25-09-2026 "Credit - Paneel 40.73" is the statement line "MOL*KUNSTSTOFPLATEN 40,73" from 22 Aug. The migration handles this (§5.4).

### 3.4 Manual entry and Rubles
Manual entries come from the web or phone form and have no review step. The **Rubles** account gets its history from the sheet (₽ column) and is maintained manually from then on.

### 3.5 Generic CSV
Column-mapping profile per source, kept as a fallback.

## 4. Classification rules (before AI)

Applied in order. A match fixes the txn **kind** and target, and the AI only fills what is still open.

1. **Own-account transfer:** counterparty identifier is one of our accounts → `transfer`, paired or confirmed as described in §1.1.
2. **Card repayment:** payee = ICS IBAN, or a card-statement `IDEAL BETALING` → transfer ABN → Credit card.
3. **ATM (`GEA`)** → transfer ABN → Cash.
4. **Debt payment:** counterparty matches a debt's lender (identifier or name) → `debt_payment`, split across loan parts with an interest/principal suggestion (Data §9).
5. **Investment patterns** in §3.1.
6. **Everything else** → AI suggestion (category, subcategory, cost type, project).

## 5. Historical migration from the Google Sheet

### 5.1 Goal and scope
Every sheet row lands in its real account. Account balances derived from the ledger match reality at checkpoints. Categories from the sheet are preserved.

**Scope: from 21-11-2020, the move to NL, until today.** Earlier years (2019, 2020 RUB pivots) are not imported.

| Period | EUR side | RUB side | Mode |
|---|---|---|---|
| 21-11-2020 → 31-12-2020 | `2020 - Amster` | not imported. The Rubles account opens on 01-01-2021 with ₽1,083,316 (the "Доступные средства" start value of `2021`) | sheet-only |
| 01-01-2021 → 31-07-2024 | `2021`, `Transactions 2022…2024` | same sheets (₽ columns) | sheet-only, with anchors |
| 01-08-2024 → 28-02-2025 | as above, **except the credit card**: ICS PDFs are the backbone and the sheet's `Credit -` rows are matched onto them | sheet (₽) | sheet-only + card match |
| 01-03-2025 → today | bank exports + `Transactions 2025…2026` | sheet (₽) + manual | **match** (EUR), sheet-only (RUB) |

- **Opening balance, not income:** `2020 - Amster` starts with "Euros meegebracht €8,811" (money brought along). It becomes the **opening balance of ABN current on 21-11-2020**, not income.
- **Statement availability:** ABN and Bunq statements go back to March 2025, ICS card statements to August 2024.

### 5.2 Sheet layouts

| Sheets | Layout | Parser | Imported |
|---|---|---|---|
| `2020 - Amster` | Dutch block layout: Maand, Datum, Kosten (Bedrag, Omschrijving, Categorie), Incomen (…), Balans. € only. Date only on the first row of each day (carried down) | `gsheet_block` | ✔ |
| `2021` | Same block layout with € and ₽ columns for costs and income | `gsheet_block` | ✔ |
| `Transactions 2022…2026` | date, € amount, ₽ amount, Categorie, Omschrijving (signed amounts) | `gsheet_std` | ✔ |
| `2022 old` | Older layout of the **same data** as `Transactions 2022` | — | ✘ skipped (duplicate) |
| `2019`, `2020` | Daily pivots, RUB, no descriptions (pre-NL) | — | ✘ out of scope |
| `Vacations`, `Renovations` | Per-project lists | — | used only to **tag projects** (§5.6) |
| `Dashboard YYYY`, `Баланс - old` | State blocks (funds, debts, assets per date) | — | used as **anchors / valuation snapshots** (§5.3 B) |

### 5.3 Two modes: *match* (from March 2025) and *sheet-only* (before)

Using sheet rows alone cannot reproduce real balances. The sheet never records own-account transfers (ABN ↔ savings, → Invest), card repayments or ATM withdrawals, and it contains `Balancing` fudge rows.

**A. Match mode (01-03-2025 → today).**
1. Import the bank exports **first**: ABN current, Sparen ABN, both Bunq accounts, Invest, and the ICS PDFs. They form the ledger backbone, with exact dates, amounts and balances. Savings transfers pair up automatically (§1.1).
2. Import the sheet in *match* mode. Each € sheet row is matched to a bank row with the same amount and date ±3 days (card rows: §5.4). Ties go to the closest date and then the best description similarity.
3. On a match, the bank row takes the sheet's **category and description**. The AI only proposes the subcategory, cost type and project.
4. An **unmatched bank row** is a transfer by the §4 rules, or goes to AI plus review.
5. An **unmatched sheet row** is usually cash spending, or a sheet error. It is routed by the **exception rules** (§5.5). Anything still unmatched lands in review as "sheet-only".

**B. Sheet-only mode (21-11-2020 → 28-02-2025).**
1. **Anchors from the sheet.** Each `Dashboard YYYY` State block holds the **year-end balance per account**. For example, `Dashboard 2025` Total €18,811.89 equals the starting Funds of 2026. These become `account_reconciliation` rows with `source='anchor'`:

   | Anchor date | Source | Level |
   |---|---|---|
   | 21-11-2020 | "Euros meegebracht" €8,811 | ABN current (opening) |
   | 31-12-2020 | `2020 - Amster` Beschikbare fondsen €3,254.26 | total → ABN current |
   | 31-12-2021 | `2021` / `Баланс - old` Доступные средства €32,391.30 | total → ABN current |
   | 31-12-2022 | `Dashboard 2022` State | **per account** (ABN, Cash, Invest ABN, Sparen ABN) |
   | 31-12-2023 | `Dashboard 2023` State | per account (+ Sparen Bunq, Rubles) |
   | 31-12-2024 | `Dashboard 2024` State | per account |
   | 28-02-2025 | opening balances of the first bank statements | per account (exact) |
   | 31-12-2025 | `Dashboard 2025` State | cross-check against the bank-derived balances |

   Tax-return (box 3) balances are **not needed**. For 2020–2021 only totals exist, so those anchors sit on ABN current. The 2022 per-account anchors redistribute that total from then on. The small "difference" line under each State block (e.g. −€674.07 in 2024) is exactly the gap the ABN residual below will show.
2. **Assign accounts:** every sheet row gets its account by the rules in §5.5 (defaults: € → ABN current, ₽ → Rubles).
3. **Other EUR accounts** (Sparen ABN, Sparen Bunq, Cash, Invest ABN cash) have almost no own rows in the sheet, only interest via R6. Per period between anchors, each account's change minus its own rows is booked as **one transfer between ABN current and that account** ("Savings movements 2023", "Cash movements 2023"…). These are marked `generated`, wealth-neutral, and never income or expense.
   - *Why this is correct for cash:* cash spending in the sheet is booked on ABN (the default). The generated ABN → Cash transfer only covers the net growth of the cash pot. Together, ABN and Cash come out exact at each anchor.
4. **ABN residual:** whatever gap remains on ABN current between its anchors is booked as **one `adjustment`** per period ("Unrecorded movements 2023"). It is excluded from income and expense and visible in the reconciliation report. It absorbs the sheet's `Balancing` rows and anything the sheet missed.
5. **Rubles:** opened 01-01-2021 with ₽1,083,316. The VTB lines of the State blocks are its year-end anchors, and gaps are handled the same way as the ABN residual.

### 5.4 Credit-card rows in the sheet
- **With ICS PDFs (from August 2024):** sheet rows starting with `Credit -` / `Credt -` are matched against statement lines by amount (card rows are dated on repayment day, so the window is: statement period + up to 35 days). The card line keeps its **transaction date** and takes the sheet's category.
- **Before August 2024 (no PDFs):** the rows go to the Credit card account on the sheet date. A synthetic transfer ABN → Credit card for the same total on the same date keeps the card balance at zero. It is marked `generated` for traceability.
- **Repayments between Aug 2024 and Feb 2025:** the statement's `IDEAL BETALING` line creates the transfer ABN → Credit card with an **inferred ABN leg**. There is no ABN statement to confirm it, which is expected before 01-03-2025, so it is not flagged.

### 5.5 Account assignment & exception rules (**to be filled in by you**)

Rules are evaluated top to bottom, and the first match wins. They apply to sheet rows in sheet-only mode, and to unmatched sheet rows in match mode. They are loaded from this table into `import_rule` (§8) and can be edited in the UI afterwards.

| # | Years / date range | Match: category | Match: description (regex, case-insensitive) | Currency | → Account | → Kind override | Note |
|---|---|---|---|---|---|---|---|
| R1 | all | any | `^cre?d(i)?t\s*-` | € | Credit card | — | See §5.4 |
| R2 | all | `Convert` | any | € / ₽ | ABN ↔ Rubles | transfer (conversion) | Pairs € and ₽ rows on the same date into one transfer |
| R3 | all | `Invest` | any | € | ABN → ABN Invest | transfer | |
| R4 | all | any | `^balancing$\|корректировка` | any | (same as default) | adjustment | |
| R5 | all | any | any | ₽ | Rubles | — | Default for RUB |
| R6a | all | `Bonus` | `abn\s*rente` | € | Sparen ABN | income → Interest | Confirmed |
| R6b | all | `Bonus` | `bunq\s*rente` | € | Sparen Bunq | income → Interest | Confirmed |
| R6c | all | `Bonus` | `^rente$` | € | *(review)* | income → Interest | Bank unknown: account proposed by AI, then reviewed |
| R7 | *optional* | *…* | *cash patterns* | € | Cash | — | Optional. Without it, cash is still exact at anchors (§5.3 B-3) |
| … | *your other exceptions* | | | | | | |
| R99 | all | any | any | € | ABN (current) | — | Default for EUR |

### 5.6 Category & project mapping
| Sheet | Becomes |
|---|---|
| Normal cost/income category | Same category. Omschrijving → description, AI proposes a subcategory |
| `Convert` | Transfer, a currency conversion (R2) |
| `Invest` | Transfer to ABN Invest (R3) |
| `Debt return` | Debt payment. Debt chosen by description ("Auto kredit" → AutoKredit, "Родителям" → parents), split suggested |
| `Hypotheek` | Debt payment across the **two Hypotheek loan parts**, with interest/principal suggested per part (Data §9) |
| `AptKopen`, `AutoKopen` | Asset purchase (or expense, chosen per batch) |
| `Bonus` + "rente" | Income → Interest |
| `Balancing`, `Корректировка` | Adjustment (R4) |
| Rows also listed in `Renovations` / `Vacations` | Project tag (Badkamer, Keuken, Мебель, trip name by date range). Proposed, confirmed in review |

### 5.7 Execution order (runbook)
1. **Set-up:** accounts + identifiers (§1), debts (incl. the 2 Hypotheek parts), assets, earmarks, categories (seeded from `Config`/`Month`).
2. **Anchors:** loaded automatically from the sheet (§5.3 B-1). Rubles opens 01-01-2021 at ₽1,083,316, and ABN current opens 21-11-2020 at €8,811.
3. **Bank exports**, oldest first per account: ICS PDFs (Aug 2024 →), then ABN current, Sparen ABN, Sparen Bunq (Mar 2025 →). Balance checks must be green, and inferred legs after 01-03-2025 confirmed.
4. **Investments:** the portfolio export, then the Invest statements. Opening positions at 01-03-2025 are derived; valuation snapshots before that come from the sheet State blocks.
5. **Sheet, match mode:** `Transactions 2026`, then `Transactions 2025` (from 01-03), plus card rows from Aug 2024. This gives the AI good, fully-attributed examples first.
6. **Sheet, sheet-only mode:** `Transactions 2025` (Jan–Feb), 2024, 2023, 2022, `2021`, `2020 - Amster`, newest first.
7. **Generated balancing:** transfers for savings, Cash and Invest cash, plus ABN and Rubles residual adjustments per period (§5.3 B).
8. **Review:** bulk-accept matched rows and paired transfers, review the rest.
9. **Reconciliation report:** a table per account per month showing derived balance vs checkpoints and unconfirmed inferred legs. A year is signed off when it's green, or its adjustments are understood.
10. **Earmarks:** Alisa/Max balances as of the start date (or from when you started setting money aside).

## 6. Dedupe

| Source | Key |
|---|---|
| ABN XLS | account + date + amount + **Eindsaldo** (running balance makes it unique) |
| ABN MT940 | account + booking date + amount + `:61:` reference + hash of `:86:` |
| Bunq CSV | account + date + amount + counterparty + description + *n*-th occurrence that day |
| ICS PDF | card + transaction date + amount + description + *n*-th occurrence |
| Sheet | year + sheet row number (source identity). Duplicates against the ledger are handled by *match mode*, not by the key |

Rows already committed are marked `duplicate` and collapsed in review.

## 7. AI during import
The AI is the same categoriser as in Backend §6. Import-specific inputs:
- The parsed counterparty, remittance info and MCC-like hints (merchant, city).
- The sheet category, when matched. The AI is then asked only for the subcategory, cost type and project.
- Large backfills (the sheet) run through the Message Batches API.

## 8. Data model
Import-specific tables are part of [Data.md](Data.md):
- `account_identifier` (§5)
- `txn_leg.inferred` (§7)
- `account_reconciliation.source` (§5)
- `import_batch`, `import_row` (with `stated_balance`, `matched_row_id`, `match_score`, `generated`) and `import_rule` (§13)

## 9. Decisions (from review)
| Topic | Decision |
|---|---|
| `NL61ABNA0119875748` | Sparen ABN (joint savings). Tracked |
| `NL42BUNQ2094599752` | Sparen Bunq. Tracked |
| `NL77BUNQ2084045134` | Old account. **Ignored**; its inflows are adjustments, not income |
| Savings handling | Transfer-first classification, pre-accepted pairs, inferred legs (§1.1) |
| Interest | Arrives on the savings account itself (R6a/R6b) |
| History start | 21-11-2020 (move to NL). €8,811 = ABN opening balance. RUB from 01-01-2021 |
| Statements | ABN/Bunq from March 2025 (match mode). ICS from August 2024 |
| Anchors | Year-end State blocks of the sheet. Tax returns not needed |
| Invest | Opening positions from the portfolio export, walked back to March 2025 |
| Cash | Tracked since 21-11-2020, kept exact at anchors via generated transfers |

## 10. Open questions — import
1. **2020–2021 per-account split:** only totals exist for those year-ends, so everything sits on ABN current until the 31-12-2022 anchor. Did Sparen ABN (or cash of any size) hold money in 2021? If so, a rough 31-12-2021 split makes the 2022 savings movements more realistic. Optional.
2. **Rule R7 (cash):** optional. Worth adding only if you want cash spending attributed to the Cash account row by row in the pre-2025 years.
