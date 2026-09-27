"""ORM models. Mirrors Spec/00 - Initial/Data.md; all tables are SQLite STRICT."""

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.db.types import DecimalText, ISODate, UTCDateTime

STRICT = {"sqlite_strict": True}


def utcnow() -> datetime:
    return datetime.now(UTC)


def _enum(col: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    joined = ",".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{col} IN ({joined})", name=name)


class Audited:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("user.id"))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    updated_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("user.id"))


# ---------------------------------------------------------------- users & settings

LOCALES = ("en", "ru")
ROLES = ("admin", "member")


class User(Base):
    __tablename__ = "user"
    __table_args__ = (_enum("locale", LOCALES, "ck_user_locale"), _enum("role", ROLES, "ck_user_role"), STRICT)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(Text, unique=True)
    display_name: Mapped[str] = mapped_column(Text)
    password_hash: Mapped[str] = mapped_column(Text)
    totp_secret: Mapped[str | None] = mapped_column(Text)  # encrypted
    locale: Mapped[str] = mapped_column(Text, default="en")
    role: Mapped[str] = mapped_column(Text, default="member")
    is_active: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AuthSession(Base):
    __tablename__ = "auth_session"
    __table_args__ = (_enum("client", ("web", "android"), "ck_auth_session_client"), STRICT)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"))
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    client: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Setting(Base):
    __tablename__ = "setting"
    __table_args__ = (STRICT,)

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text)  # JSON


# ---------------------------------------------------------------- currencies & FX

class Currency(Base):
    __tablename__ = "currency"
    __table_args__ = (STRICT,)

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    symbol: Mapped[str] = mapped_column(Text)
    minor_units: Mapped[int] = mapped_column(Integer, default=2)


FX_SOURCES = ("ecb", "cbr", "manual")


class FxRate(Base):
    __tablename__ = "fx_rate"
    __table_args__ = (_enum("source", FX_SOURCES, "ck_fx_rate_source"), STRICT)

    date: Mapped[date] = mapped_column(ISODate, primary_key=True)
    base: Mapped[str] = mapped_column(Text, ForeignKey("currency.code"), primary_key=True)
    quote: Mapped[str] = mapped_column(Text, ForeignKey("currency.code"), primary_key=True)
    rate: Mapped[Decimal] = mapped_column(DecimalText)  # 1 base = rate quote
    source: Mapped[str] = mapped_column(Text)


# ---------------------------------------------------------------- accounts

ACCOUNT_TYPES = ("current", "savings", "cash", "credit_card", "investment")


class Account(Audited, Base):
    __tablename__ = "account"
    __table_args__ = (_enum("type", ACCOUNT_TYPES, "ck_account_type"), STRICT)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    type: Mapped[str] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(Text, ForeignKey("currency.code"))
    institution: Mapped[str | None] = mapped_column(Text)
    opening_date: Mapped[date] = mapped_column(ISODate)
    opening_balance: Mapped[int] = mapped_column(Integer, default=0)
    include_in_net_worth: Mapped[int] = mapped_column(Integer, default=1)
    owner_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("user.id"))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    identifiers: Mapped[list["AccountIdentifier"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )


IDENTIFIER_KINDS = ("iban", "account_no", "card_last4", "other")


class AccountIdentifier(Base):
    __tablename__ = "account_identifier"
    __table_args__ = (
        _enum("kind", IDENTIFIER_KINDS, "ck_account_identifier_kind"),
        UniqueConstraint("kind", "value"),
        STRICT,
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("account.id"))
    kind: Mapped[str] = mapped_column(Text)
    value: Mapped[str] = mapped_column(Text)

    account: Mapped[Account] = relationship(back_populates="identifiers")


RECON_SOURCES = ("manual", "statement", "anchor")


class AccountReconciliation(Base):
    __tablename__ = "account_reconciliation"
    __table_args__ = (_enum("source", RECON_SOURCES, "ck_account_reconciliation_source"), STRICT)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("account.id"))
    date: Mapped[date] = mapped_column(ISODate)
    stated_balance: Mapped[int] = mapped_column(Integer)
    computed_balance: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(Text, default="manual")
    note: Mapped[str | None] = mapped_column(Text)
    adjustment_txn_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("txn.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("user.id"))


# ---------------------------------------------------------------- categories & projects

COST_TYPES = ("fixed", "variable", "one_time")
IE_KINDS = ("expense", "income")


class Category(Audited, Base):
    __tablename__ = "category"
    __table_args__ = (
        _enum("kind", IE_KINDS, "ck_category_kind"),
        CheckConstraint(
            "default_cost_type IS NULL OR default_cost_type IN ('fixed','variable','one_time')",
            name="ck_category_cost_type",
        ),
        UniqueConstraint("parent_id", "name"),
        STRICT,
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("category.id"))
    kind: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    name_i18n: Mapped[str | None] = mapped_column(Text)  # JSON
    default_cost_type: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)  # hint for the AI
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    parent: Mapped["Category | None"] = relationship(remote_side="Category.id", back_populates="children")
    children: Mapped[list["Category"]] = relationship(back_populates="parent")


PROJECT_KINDS = ("renovation", "trip", "event", "other")


class Project(Audited, Base):
    __tablename__ = "project"
    __table_args__ = (_enum("kind", PROJECT_KINDS, "ck_project_kind"), STRICT)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    kind: Mapped[str] = mapped_column(Text, default="other")
    start_date: Mapped[date | None] = mapped_column(ISODate)
    end_date: Mapped[date | None] = mapped_column(ISODate)
    budget_amount: Mapped[int | None] = mapped_column(Integer)
    budget_currency: Mapped[str | None] = mapped_column(Text, ForeignKey("currency.code"))
    notes: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


# ---------------------------------------------------------------- debts, earmarks, assets

DEBT_TYPES = ("mortgage", "loan", "personal", "other")
REPAYMENT_TYPES = ("annuity", "linear", "interest_only", "free", "group")


class Debt(Audited, Base):
    __tablename__ = "debt"
    __table_args__ = (
        _enum("type", DEBT_TYPES, "ck_debt_type"),
        _enum("repayment_type", REPAYMENT_TYPES, "ck_debt_repayment_type"),
        STRICT,
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    lender: Mapped[str | None] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(Text, ForeignKey("currency.code"))
    type: Mapped[str] = mapped_column(Text)
    repayment_type: Mapped[str] = mapped_column(Text)  # 'group' = parent of loan parts
    principal_original: Mapped[int] = mapped_column(Integer, default=0)
    start_date: Mapped[date] = mapped_column(ISODate)
    term_months: Mapped[int | None] = mapped_column(Integer)
    payment_day: Mapped[int | None] = mapped_column(Integer)
    interest_category_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("category.id"))
    linked_asset_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("asset.id"))
    parent_debt_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("debt.id"))
    lender_identifier: Mapped[str | None] = mapped_column(Text)  # IBAN / name pattern for import matching
    closed_at: Mapped[date | None] = mapped_column(ISODate)
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    rate_periods: Mapped[list["DebtRatePeriod"]] = relationship(
        cascade="all, delete-orphan", order_by="DebtRatePeriod.from_date"
    )
    parts: Mapped[list["Debt"]] = relationship(back_populates="parent")
    parent: Mapped["Debt | None"] = relationship(remote_side="Debt.id", back_populates="parts")


class DebtRatePeriod(Base):
    __tablename__ = "debt_rate_period"
    __table_args__ = (UniqueConstraint("debt_id", "from_date"), STRICT)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    debt_id: Mapped[int] = mapped_column(Integer, ForeignKey("debt.id"))
    from_date: Mapped[date] = mapped_column(ISODate)
    annual_rate: Mapped[Decimal] = mapped_column(DecimalText)


class DebtBalanceSnapshot(Base):
    __tablename__ = "debt_balance_snapshot"
    __table_args__ = (UniqueConstraint("debt_id", "date"), STRICT)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    debt_id: Mapped[int] = mapped_column(Integer, ForeignKey("debt.id"))
    date: Mapped[date] = mapped_column(ISODate)
    balance: Mapped[int] = mapped_column(Integer)  # outstanding principal, positive
    note: Mapped[str | None] = mapped_column(Text)


class Earmark(Audited, Base):
    __tablename__ = "earmark"
    __table_args__ = (STRICT,)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    currency: Mapped[str] = mapped_column(Text, ForeignKey("currency.code"))
    target_amount: Mapped[int | None] = mapped_column(Integer)
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


ASSET_TYPES = ("real_estate", "vehicle", "other")


class Asset(Audited, Base):
    __tablename__ = "asset"
    __table_args__ = (_enum("type", ASSET_TYPES, "ck_asset_type"), STRICT)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    type: Mapped[str] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(Text, ForeignKey("currency.code"))
    acquired_date: Mapped[date | None] = mapped_column(ISODate)
    acquired_value: Mapped[int | None] = mapped_column(Integer)
    disposed_date: Mapped[date | None] = mapped_column(ISODate)
    disposed_value: Mapped[int | None] = mapped_column(Integer)
    include_in_net_worth: Mapped[int] = mapped_column(Integer, default=1)
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


VALUATION_SOURCES = ("manual", "woz", "estimate", "import")


class AssetValuation(Base):
    __tablename__ = "asset_valuation"
    __table_args__ = (
        _enum("source", VALUATION_SOURCES, "ck_asset_valuation_source"),
        UniqueConstraint("asset_id", "date"),
        STRICT,
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(Integer, ForeignKey("asset.id"))
    date: Mapped[date] = mapped_column(ISODate)
    value: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(Text, default="manual")


class Security(Base):
    __tablename__ = "security"
    __table_args__ = (STRICT,)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text)  # ticker or ABN fund code
    isin: Mapped[str | None] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(Text, ForeignKey("currency.code"))
    price_source: Mapped[str] = mapped_column(Text, default="manual")


class SecurityPrice(Base):
    __tablename__ = "security_price"
    __table_args__ = (STRICT,)

    security_id: Mapped[int] = mapped_column(Integer, ForeignKey("security.id"), primary_key=True)
    date: Mapped[date] = mapped_column(ISODate, primary_key=True)
    price: Mapped[Decimal] = mapped_column(DecimalText)


# ---------------------------------------------------------------- ledger

TXN_KINDS = (
    "expense", "income", "transfer", "debt_payment", "debt_drawdown",
    "investment", "asset_purchase", "earmark", "adjustment", "mixed",
)
TXN_SOURCES = ("manual", "import", "generated")


class Txn(Audited, Base):
    __tablename__ = "txn"
    __table_args__ = (
        _enum("kind", TXN_KINDS, "ck_txn_kind"),
        _enum("source", TXN_SOURCES, "ck_txn_source"),
        Index("ix_txn_date", "date"),
        STRICT,
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[date] = mapped_column(ISODate)
    kind: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    counterparty: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    fx_diff_ref: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(Text, default="manual")
    import_row_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("import_row.id", use_alter=True, name="fk_txn_import_row", ondelete="SET NULL")
    )

    legs: Mapped[list["TxnLeg"]] = relationship(
        back_populates="txn", cascade="all, delete-orphan", order_by="TxnLeg.id"
    )
    splits: Mapped[list["TxnSplit"]] = relationship(
        back_populates="txn", cascade="all, delete-orphan", order_by="TxnSplit.id"
    )
    trades: Mapped[list["InvestmentTrade"]] = relationship(
        back_populates="txn", cascade="all, delete-orphan"
    )


class TxnLeg(Base):
    __tablename__ = "txn_leg"
    __table_args__ = (
        CheckConstraint("amount <> 0", name="ck_txn_leg_nonzero"),
        Index("ix_leg_account", "account_id"),
        STRICT,
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    txn_id: Mapped[int] = mapped_column(Integer, ForeignKey("txn.id", ondelete="CASCADE"))
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("account.id"))
    amount: Mapped[int] = mapped_column(Integer)
    amount_ref: Mapped[int] = mapped_column(Integer)
    ref_estimated: Mapped[int] = mapped_column(Integer, default=0)
    inferred: Mapped[int] = mapped_column(Integer, default=0)

    txn: Mapped[Txn] = relationship(back_populates="legs")


class TxnSplit(Base):
    __tablename__ = "txn_split"
    __table_args__ = (
        CheckConstraint(
            "(category_id IS NOT NULL) + (debt_id IS NOT NULL) + (earmark_id IS NOT NULL)"
            " + (asset_id IS NOT NULL) = 1",
            name="ck_txn_split_one_target",
        ),
        CheckConstraint(
            "cost_type IS NULL OR cost_type IN ('fixed','variable','one_time')", name="ck_txn_split_cost_type"
        ),
        Index("ix_split_category", "category_id"),
        Index("ix_split_project", "project_id"),
        STRICT,
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    txn_id: Mapped[int] = mapped_column(Integer, ForeignKey("txn.id", ondelete="CASCADE"))
    amount: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(Text, ForeignKey("currency.code"))
    amount_ref: Mapped[int] = mapped_column(Integer)
    ref_estimated: Mapped[int] = mapped_column(Integer, default=0)
    category_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("category.id"))
    debt_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("debt.id"))
    earmark_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("earmark.id"))
    asset_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("asset.id"))
    cost_type: Mapped[str | None] = mapped_column(Text)
    project_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("project.id"))
    note: Mapped[str | None] = mapped_column(Text)

    txn: Mapped[Txn] = relationship(back_populates="splits")


TRADE_ACTIONS = ("buy", "sell", "dividend_reinvest", "split", "opening")


class InvestmentTrade(Base):
    __tablename__ = "investment_trade"
    __table_args__ = (_enum("action", TRADE_ACTIONS, "ck_investment_trade_action"), STRICT)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    txn_id: Mapped[int] = mapped_column(Integer, ForeignKey("txn.id", ondelete="CASCADE"))
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("account.id"))
    security_id: Mapped[int] = mapped_column(Integer, ForeignKey("security.id"))
    action: Mapped[str] = mapped_column(Text)
    units: Mapped[Decimal] = mapped_column(DecimalText)  # signed
    price: Mapped[Decimal] = mapped_column(DecimalText)
    fees: Mapped[int] = mapped_column(Integer, default=0)

    txn: Mapped[Txn] = relationship(back_populates="trades")


# ---------------------------------------------------------------- budget

class BudgetTemplateLine(Audited, Base):
    __tablename__ = "budget_template_line"
    __table_args__ = (STRICT,)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category_id: Mapped[int] = mapped_column(Integer, ForeignKey("category.id"))
    label: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[int] = mapped_column(Integer)  # positive = planned spend/income
    currency: Mapped[str] = mapped_column(Text, ForeignKey("currency.code"))
    valid_from: Mapped[str] = mapped_column(Text)  # 'YYYY-MM'
    valid_to: Mapped[str | None] = mapped_column(Text)


class BudgetLine(Audited, Base):
    __tablename__ = "budget_line"
    __table_args__ = (UniqueConstraint("month", "category_id", "currency", "template_line_id"), STRICT)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    month: Mapped[str] = mapped_column(Text)
    category_id: Mapped[int] = mapped_column(Integer, ForeignKey("category.id"))
    amount: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(Text, ForeignKey("currency.code"))
    template_line_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("budget_template_line.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(Text)


# ---------------------------------------------------------------- import & AI

IMPORT_SOURCES = (
    "abn_mt940", "abn_xls", "bunq_csv", "bunq_mt940", "bunq_api", "ics_pdf", "gsheet", "generic_csv",
)
BATCH_STATUSES = ("parsing", "reviewing", "committed", "discarded", "failed")
ROW_STATUSES = ("new", "duplicate", "suggested", "accepted", "skipped", "committed")


class ImportBatch(Base):
    __tablename__ = "import_batch"
    __table_args__ = (
        _enum("source", IMPORT_SOURCES, "ck_import_batch_source"),
        _enum("status", BATCH_STATUSES, "ck_import_batch_status"),
        CheckConstraint("mode IS NULL OR mode IN ('match','sheet_only')", name="ck_import_batch_mode"),
        STRICT,
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(Text)
    account_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("account.id"))
    mode: Mapped[str | None] = mapped_column(Text)
    file_name: Mapped[str | None] = mapped_column(Text)
    file_sha256: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="parsing")
    stats: Mapped[str | None] = mapped_column(Text)  # JSON
    error: Mapped[str | None] = mapped_column(Text)
    ai_batch_id: Mapped[str | None] = mapped_column(Text)  # Anthropic Message Batch id, if used
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("user.id"))

    rows: Mapped[list["ImportRow"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan", order_by="ImportRow.row_no"
    )


class ImportRow(Base):
    __tablename__ = "import_row"
    __table_args__ = (
        _enum("status", ROW_STATUSES, "ck_import_row_status"),
        Index("ix_import_row_dedupe", "dedupe_key"),
        Index(
            "ux_import_external",
            "account_id",
            "external_id",
            unique=True,
            sqlite_where=text("external_id IS NOT NULL AND status = 'committed'"),
        ),
        STRICT,
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(Integer, ForeignKey("import_batch.id", ondelete="CASCADE"))
    row_no: Mapped[int] = mapped_column(Integer)
    raw: Mapped[str] = mapped_column(Text)  # JSON
    date: Mapped[date] = mapped_column(ISODate)
    amount: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(Text)
    account_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("account.id"))
    counterparty: Mapped[str | None] = mapped_column(Text)
    counterparty_iban: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(Text)
    stated_balance: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, default="new")
    proposed: Mapped[str | None] = mapped_column(Text)  # JSON draft txn
    matched_row_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("import_row.id"))
    matched_txn_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("txn.id", ondelete="SET NULL"))
    match_score: Mapped[str | None] = mapped_column(Text)
    generated: Mapped[int] = mapped_column(Integer, default=0)
    txn_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("txn.id", ondelete="SET NULL"))

    batch: Mapped[ImportBatch] = relationship(back_populates="rows")
    suggestion: Mapped["AiSuggestion | None"] = relationship(
        back_populates="row", cascade="all, delete-orphan", uselist=False
    )


class ImportRule(Base):
    __tablename__ = "import_rule"
    __table_args__ = (STRICT,)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer)
    match: Mapped[str] = mapped_column(Text)  # JSON
    action: Mapped[str] = mapped_column(Text)  # JSON
    note: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[int] = mapped_column(Integer, default=1)


class AiSuggestion(Base):
    __tablename__ = "ai_suggestion"
    __table_args__ = (STRICT,)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    import_row_id: Mapped[int] = mapped_column(Integer, ForeignKey("import_row.id", ondelete="CASCADE"), unique=True)
    model: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    category_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("category.id"))
    cost_type: Mapped[str | None] = mapped_column(Text)
    project_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("project.id"))
    transfer_account_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("account.id"))
    confidence: Mapped[Decimal] = mapped_column(DecimalText)
    rationale: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    row: Mapped[ImportRow] = relationship(back_populates="suggestion")


class AiCallLog(Base):
    __tablename__ = "ai_call_log"
    __table_args__ = (STRICT,)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    model: Mapped[str] = mapped_column(Text)
    batch_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("import_batch.id", ondelete="SET NULL"))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)


# ---------------------------------------------------------------- audit

class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (_enum("action", ("create", "update", "delete"), "ck_audit_log_action"), STRICT)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("user.id"))
    entity: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(Text)
    diff: Mapped[str | None] = mapped_column(Text)  # JSON
