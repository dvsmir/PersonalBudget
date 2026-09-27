/** Shapes of the report endpoints (services/reports.py). Amounts are minor units. */

export type Totals = Record<string, number>

export type CatNode = {
  category_id: number
  name: string
  totals: Totals
  avg_per_month?: Totals
  subcategories?: { category_id: number; name: string; totals: Totals }[]
}

export type MonthReport = {
  month: string
  currency_mode: 'reference' | 'native'
  income: CatNode[]
  expense: CatNode[]
  by_cost_type: Record<'fixed' | 'variable' | 'one_time', Totals>
  totals: { income: Totals; expense: Totals }
  summary_ref: {
    income: number; expenses: number; balance: number; cash_flow: number
    debt_principal_repaid: number; to_investments: number; adjustments: number; conversion_cost: number
  }
  compare_ref: { prev_income: number; prev_expenses: number; avg12_income: number; avg12_expenses: number }
}

export type YearReport = {
  year: number
  months: { month: string; income: Totals; expenses: Totals; balance: Totals; funds_end_ref: number | null }[]
  income: CatNode[]
  expense: CatNode[]
  totals: { income: Totals; expense: Totals }
  heatmap_ref: { category_id: number; name: string; months: number[] }[]
}

export type Snapshot = {
  date: string; funds: number; available_funds: number; earmarks: number; investments: number
  assets: number; debts: number; net_worth: number
}

export type Bridge = { start: string; end: string; net_worth_start: number; net_worth_end: number; components: Record<string, number> }

export type Balances = {
  date: string
  accounts: { account_id: number; name: string; type: string; currency: string; balance: number; balance_ref: number }[]
  per_currency: Totals
  snapshot: Snapshot
}

export type BudgetStatus = {
  month: string
  rows: { category_id: number; name: string; kind: string; currency: string; planned: number; actual: number; remaining: number; pct_used: number | null; planned_line: boolean }[]
}

export type DebtOverview = {
  debt_id: number; name: string; currency: string; outstanding: number; original: number
  ytd: { principal_repaid: number; interest_paid: number }; payoff_date: string | null
  parts: { debt_id: number; name: string; outstanding: number; rate: string }[]
}

export type ImportRowView = {
  id: number; row_no: number; date: string; amount: number; currency: string; account_id: number | null
  counterparty: string | null; counterparty_iban: string | null; description: string | null; status: string
  stated_balance: number | null; txn_id: number | null; generated: boolean
  proposed: {
    kind?: string; rule?: string | null; description?: string; needs_category?: boolean; mode?: string
    legs?: { account_id: number; amount: number; inferred: boolean }[]
    splits?: { amount: number; category_id: number | null; cost_type: string | null; project_id: number | null; debt_id?: number; note?: string }[]
    update_txn_id?: number; sheet_category?: string; sheet?: string; note?: string; unmatched_in_bank_period?: boolean
    skip_reason?: string; skip?: string; ai_agrees_with_sheet?: boolean
  }
  suggestion: { kind: string; category_id: number | null; cost_type: string | null; project_id: number | null; confidence: number; rationale: string | null; model: string } | null
}
