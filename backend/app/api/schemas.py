"""API schemas. Money is always an integer in minor units plus a currency code (exact in JSON and JS)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- auth & users

class LoginIn(BaseModel):
    email: str
    password: str
    totp: str | None = None
    client: Literal["web", "android"] = "web"


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: str | None = None  # only returned to the android client; web uses the httpOnly cookie


class UserOut(ORM):
    id: int
    email: str
    display_name: str
    locale: str
    role: str
    is_active: int
    totp_enabled: bool = False


class UserIn(BaseModel):
    email: str
    display_name: str
    password: str
    role: Literal["admin", "member"] = "member"
    locale: Literal["en", "ru"] = "en"


class UserPatch(BaseModel):
    display_name: str | None = None
    locale: Literal["en", "ru"] | None = None
    role: Literal["admin", "member"] | None = None
    is_active: bool | None = None
    password: str | None = None


class MePatch(BaseModel):
    display_name: str | None = None
    locale: Literal["en", "ru"] | None = None
    current_password: str | None = None
    new_password: str | None = None


class TotpBeginOut(BaseModel):
    secret: str
    uri: str


class TotpConfirmIn(BaseModel):
    secret: str
    code: str


# ---------------------------------------------------------------- reference data

class IdentifierIO(ORM):
    kind: Literal["iban", "account_no", "card_last4", "other"]
    value: str


class AccountIn(BaseModel):
    name: str
    type: Literal["current", "savings", "cash", "credit_card", "investment"]
    currency: str
    institution: str | None = None
    opening_date: date
    opening_balance: int = 0
    include_in_net_worth: bool = True
    owner_user_id: int | None = None
    sort_order: int = 0
    identifiers: list[IdentifierIO] = Field(default_factory=list)


class AccountPatch(BaseModel):
    name: str | None = None
    institution: str | None = None
    opening_date: date | None = None
    opening_balance: int | None = None
    include_in_net_worth: bool | None = None
    sort_order: int | None = None
    archived: bool | None = None
    identifiers: list[IdentifierIO] | None = None


class AccountOut(ORM):
    id: int
    name: str
    type: str
    currency: str
    institution: str | None
    opening_date: date
    opening_balance: int
    include_in_net_worth: int
    sort_order: int
    archived_at: datetime | None
    identifiers: list[IdentifierIO]
    balance: int | None = None
    balance_ref: int | None = None
    last_reconciled: date | None = None


class ReconcileIn(BaseModel):
    date: date
    stated_balance: int
    create_adjustment: bool = True
    note: str | None = None


class CategoryIn(BaseModel):
    parent_id: int | None = None
    kind: Literal["expense", "income"]
    name: str
    name_i18n: dict[str, str] | None = None
    default_cost_type: Literal["fixed", "variable", "one_time"] | None = None
    description: str | None = None
    sort_order: int = 0


class CategoryPatch(BaseModel):
    parent_id: int | None = None
    name: str | None = None
    name_i18n: dict[str, str] | None = None
    default_cost_type: Literal["fixed", "variable", "one_time"] | None = None
    description: str | None = None
    sort_order: int | None = None
    archived: bool | None = None
    set_parent: bool = False  # parent_id is applied only when true (allows moving to top level)


class CategoryOut(ORM):
    id: int
    parent_id: int | None
    kind: str
    name: str
    name_i18n: str | None
    default_cost_type: str | None
    description: str | None
    sort_order: int
    archived_at: datetime | None


class MergeIn(BaseModel):
    source_id: int
    target_id: int


class ProjectIn(BaseModel):
    name: str
    kind: Literal["renovation", "trip", "event", "other"] = "other"
    start_date: date | None = None
    end_date: date | None = None
    budget_amount: int | None = None
    budget_currency: str | None = None
    notes: str | None = None


class ProjectOut(ORM):
    id: int
    name: str
    kind: str
    start_date: date | None
    end_date: date | None
    budget_amount: int | None
    budget_currency: str | None
    notes: str | None
    archived_at: datetime | None


class EarmarkIn(BaseModel):
    name: str
    currency: str = "EUR"
    target_amount: int | None = None


class EarmarkOut(ORM):
    id: int
    name: str
    currency: str
    target_amount: int | None
    archived_at: datetime | None
    balance: int = 0


class AssetIn(BaseModel):
    name: str
    type: Literal["real_estate", "vehicle", "other"]
    currency: str
    acquired_date: date | None = None
    acquired_value: int | None = None
    disposed_date: date | None = None
    disposed_value: int | None = None
    include_in_net_worth: bool = True


class AssetOut(ORM):
    id: int
    name: str
    type: str
    currency: str
    acquired_date: date | None
    acquired_value: int | None
    disposed_date: date | None
    disposed_value: int | None
    include_in_net_worth: int
    archived_at: datetime | None
    value: int | None = None
    valued_on: date | None = None


class ValuationIn(BaseModel):
    date: date
    value: int
    source: Literal["manual", "woz", "estimate"] = "manual"


class ValuationOut(ORM):
    id: int
    date: date
    value: int
    source: str


class SecurityIn(BaseModel):
    symbol: str
    isin: str | None = None
    name: str
    currency: str
    price_source: str = "manual"


class SecurityOut(ORM):
    id: int
    symbol: str
    isin: str | None
    name: str
    currency: str
    price_source: str


class PriceIn(BaseModel):
    date: date
    price: Decimal


class RatePeriodIO(ORM):
    from_date: date
    annual_rate: Decimal


class DebtIn(BaseModel):
    name: str
    lender: str | None = None
    currency: str = "EUR"
    type: Literal["mortgage", "loan", "personal", "other"]
    repayment_type: Literal["annuity", "linear", "interest_only", "free", "group"]
    principal_original: int = 0
    start_date: date
    term_months: int | None = None
    payment_day: int | None = None
    interest_category_id: int | None = None
    linked_asset_id: int | None = None
    parent_debt_id: int | None = None
    lender_identifier: str | None = None
    rate_periods: list[RatePeriodIO] = Field(default_factory=list)


class DebtPatch(BaseModel):
    name: str | None = None
    lender: str | None = None
    principal_original: int | None = None
    start_date: date | None = None
    term_months: int | None = None
    payment_day: int | None = None
    interest_category_id: int | None = None
    linked_asset_id: int | None = None
    lender_identifier: str | None = None
    repayment_type: Literal["annuity", "linear", "interest_only", "free", "group"] | None = None
    closed_at: date | None = None
    rate_periods: list[RatePeriodIO] | None = None


class DebtOut(ORM):
    id: int
    name: str
    lender: str | None
    currency: str
    type: str
    repayment_type: str
    principal_original: int
    start_date: date
    term_months: int | None
    payment_day: int | None
    interest_category_id: int | None
    linked_asset_id: int | None
    parent_debt_id: int | None
    lender_identifier: str | None
    closed_at: date | None
    rate_periods: list[RatePeriodIO]
    outstanding: int | None = None


class SnapshotIn(BaseModel):
    date: date
    balance: int
    note: str | None = None


class SplitSuggestIn(BaseModel):
    debt_id: int
    date: date
    amount: int  # positive payment amount


# ---------------------------------------------------------------- transactions

class LegIO(BaseModel):
    account_id: int
    amount: int
    inferred: bool = False


class SplitIO(BaseModel):
    amount: int
    category_id: int | None = None
    debt_id: int | None = None
    earmark_id: int | None = None
    asset_id: int | None = None
    cost_type: Literal["fixed", "variable", "one_time"] | None = None
    project_id: int | None = None
    note: str | None = None


class TradeIO(BaseModel):
    account_id: int
    security_id: int
    action: Literal["buy", "sell", "dividend_reinvest", "split", "opening"]
    units: Decimal
    price: Decimal
    fees: int = 0


class TxnIn(BaseModel):
    date: date
    kind: Literal["expense", "income", "transfer", "debt_payment", "debt_drawdown", "investment",
                  "asset_purchase", "earmark", "adjustment", "mixed"]
    description: str = ""
    counterparty: str | None = None
    notes: str | None = None
    legs: list[LegIO] = Field(default_factory=list)
    splits: list[SplitIO] = Field(default_factory=list)
    trades: list[TradeIO] = Field(default_factory=list)


class LegOut(ORM):
    id: int
    account_id: int
    amount: int
    amount_ref: int
    ref_estimated: int
    inferred: int


class SplitOut(ORM):
    id: int
    amount: int
    currency: str
    amount_ref: int
    category_id: int | None
    debt_id: int | None
    earmark_id: int | None
    asset_id: int | None
    cost_type: str | None
    project_id: int | None
    note: str | None


class TradeOut(ORM):
    id: int
    account_id: int
    security_id: int
    action: str
    units: Decimal
    price: Decimal
    fees: int


class TxnOut(ORM):
    id: int
    date: date
    kind: str
    description: str
    counterparty: str | None
    notes: str | None
    fx_diff_ref: int
    source: str
    updated_at: datetime
    legs: list[LegOut]
    splits: list[SplitOut]
    trades: list[TradeOut]


class TxnPage(BaseModel):
    items: list[TxnOut]
    next_cursor: str | None
    totals: dict[str, int]
    totals_ref: int


class BulkTxnIn(BaseModel):
    txn_ids: list[int]
    category_id: int | None = None
    cost_type: Literal["fixed", "variable", "one_time"] | None = None
    project_id: int | None = None
    clear_project: bool = False


# ---------------------------------------------------------------- budget

class TemplateLineIn(BaseModel):
    category_id: int
    label: str | None = None
    amount: int
    currency: str = "EUR"
    valid_from: str = Field(pattern=r"^\d{4}-\d{2}$")
    valid_to: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")


class TemplateLineOut(ORM):
    id: int
    category_id: int
    label: str | None
    amount: int
    currency: str
    valid_from: str
    valid_to: str | None


class BudgetLineIn(BaseModel):
    category_id: int
    amount: int
    currency: str = "EUR"
    note: str | None = None


class BudgetLinePatch(BaseModel):
    amount: int | None = None
    note: str | None = None


class BudgetLineOut(ORM):
    id: int
    month: str
    category_id: int
    amount: int
    currency: str
    template_line_id: int | None
    note: str | None


# ---------------------------------------------------------------- imports

class ImportBatchOut(ORM):
    id: int
    source: str
    account_id: int | None
    mode: str | None
    file_name: str | None
    status: str
    stats: str | None
    error: str | None
    created_at: datetime
    created_by: int | None


class RowPatch(BaseModel):
    proposed: dict | None = None
    status: Literal["new", "accepted", "skipped", "duplicate", "suggested"] | None = None


class BulkRowsIn(BaseModel):
    row_ids: list[int] | None = None
    filter: dict | None = None
    status: Literal["accepted", "skipped", "new"] | None = None
    patch: dict | None = None


class CommitIn(BaseModel):
    row_ids: list[int] | None = None


class SuggestIn(BaseModel):
    row_ids: list[int] | None = None


class ImportRuleIO(ORM):
    id: int | None = None
    source: str = "gsheet"
    priority: int
    match: str
    action: str
    note: str | None = None
    is_active: int = 1
