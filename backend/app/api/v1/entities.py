import json
from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi import APIRouter
from sqlalchemy import func, select, update

from app.api.deps import DB, CurrentUser
from app.api.schemas import (
    AccountIn,
    AccountOut,
    AccountPatch,
    AssetIn,
    AssetOut,
    CategoryIn,
    CategoryOut,
    CategoryPatch,
    DebtIn,
    DebtOut,
    DebtPatch,
    EarmarkIn,
    EarmarkOut,
    MergeIn,
    PriceIn,
    ProjectIn,
    ProjectOut,
    ReconcileIn,
    SecurityIn,
    SecurityOut,
    SnapshotIn,
    SplitSuggestIn,
    ValuationIn,
    ValuationOut,
)
from app.db.models import (
    Account,
    AccountIdentifier,
    AccountReconciliation,
    Asset,
    AssetValuation,
    BudgetLine,
    BudgetTemplateLine,
    Category,
    Debt,
    DebtBalanceSnapshot,
    DebtRatePeriod,
    Earmark,
    InvestmentTrade,
    Project,
    Security,
    SecurityPrice,
    Txn,
    TxnLeg,
    TxnSplit,
)
from app.services import debts as debt_svc
from app.services import ledger, positions, reports
from app.services.common import DomainError, audit, get_or_404
from app.services.fx import RateBook

router = APIRouter()
now = lambda: datetime.now(UTC)  # noqa: E731


# ---------------------------------------------------------------- accounts

def _account_out(db, acc: Account, on: date, book: RateBook, bals: dict[int, int]) -> AccountOut:  # type: ignore[no-untyped-def]
    out = AccountOut.model_validate(acc)
    out.balance = bals.get(acc.id, acc.opening_balance)
    out.balance_ref = book.to_ref(out.balance, acc.currency, on).amount
    out.last_reconciled = db.execute(
        select(func.max(AccountReconciliation.date)).where(AccountReconciliation.account_id == acc.id,
                                                           AccountReconciliation.source != "anchor")
    ).scalar_one()
    return out


@router.get("/accounts", response_model=list[AccountOut], tags=["accounts"])
def list_accounts(user: CurrentUser, db: DB, on: date | None = None, include_archived: bool = False) -> list[AccountOut]:
    on = on or date.today()
    book = RateBook(db)
    bals = positions.account_balances(db, on)
    q = select(Account).order_by(Account.sort_order, Account.name)
    if not include_archived:
        q = q.where(Account.archived_at.is_(None))
    return [_account_out(db, a, on, book, bals) for a in db.scalars(q)]


@router.post("/accounts", response_model=AccountOut, status_code=201, tags=["accounts"])
def create_account(body: AccountIn, user: CurrentUser, db: DB) -> AccountOut:
    data = body.model_dump(exclude={"identifiers"})
    data["include_in_net_worth"] = int(body.include_in_net_worth)
    acc = Account(**data, created_by=user.id, updated_by=user.id)
    acc.identifiers = [AccountIdentifier(kind=i.kind, value=i.value.replace(" ", "").upper()) for i in body.identifiers]
    db.add(acc)
    db.flush()
    audit(db, user.id, "account", acc.id, "create", after=data)
    return _account_out(db, acc, date.today(), RateBook(db), positions.account_balances(db, date.today()))


@router.patch("/accounts/{account_id}", response_model=AccountOut, tags=["accounts"])
def patch_account(account_id: int, body: AccountPatch, user: CurrentUser, db: DB) -> AccountOut:
    acc = get_or_404(db, Account, account_id)
    for k in ("name", "institution", "opening_date", "opening_balance", "sort_order"):
        if getattr(body, k) is not None:
            setattr(acc, k, getattr(body, k))
    if body.include_in_net_worth is not None:
        acc.include_in_net_worth = int(body.include_in_net_worth)
    if body.archived is not None:
        acc.archived_at = now() if body.archived else None
    if body.identifiers is not None:
        acc.identifiers = [AccountIdentifier(kind=i.kind, value=i.value.replace(" ", "").upper()) for i in body.identifiers]
    if body.opening_date is not None:
        earliest = db.execute(select(func.min(Txn.date)).join(TxnLeg).where(TxnLeg.account_id == acc.id)).scalar_one()
        if earliest and earliest < acc.opening_date:
            raise DomainError("before_opening", f"Transactions exist from {earliest}; opening date must be on or before it")
    acc.updated_by = user.id
    db.flush()
    audit(db, user.id, "account", acc.id, "update", after=body.model_dump(exclude_none=True))
    return _account_out(db, acc, date.today(), RateBook(db), positions.account_balances(db, date.today()))


@router.get("/accounts/{account_id}/balance-series", tags=["accounts"])
def balance_series(account_id: int, user: CurrentUser, db: DB, start: date, end: date) -> list[dict]:
    acc = get_or_404(db, Account, account_id)
    book = RateBook(db)
    out = []
    for d in reports.month_ends(start, end):
        bal = ledger.account_balance(db, acc.id, d) if d >= acc.opening_date else 0
        out.append({"date": d, "balance": bal, "balance_ref": book.to_ref(bal, acc.currency, d).amount})
    return out


@router.post("/accounts/{account_id}/reconcile", tags=["accounts"])
def reconcile(account_id: int, body: ReconcileIn, user: CurrentUser, db: DB) -> dict:
    acc = get_or_404(db, Account, account_id)
    computed = ledger.account_balance(db, acc.id, body.date)
    rec = AccountReconciliation(account_id=acc.id, date=body.date, stated_balance=body.stated_balance,
                                computed_balance=computed, source="manual", note=body.note, created_by=user.id)
    diff = body.stated_balance - computed
    if diff and body.create_adjustment:
        txn = ledger.create_txn(db, ledger.TxnDraft(
            date=body.date, kind="adjustment", description=f"Reconciliation {acc.name}",
            legs=[ledger.LegIn(account_id=acc.id, amount=diff)]), user.id)
        rec.adjustment_txn_id = txn.id
    db.add(rec)
    return {"computed_balance": computed, "stated_balance": body.stated_balance, "difference": diff,
            "adjustment_txn_id": rec.adjustment_txn_id}


@router.get("/accounts/{account_id}/reconciliation", tags=["accounts"])
def reconciliation(account_id: int, user: CurrentUser, db: DB) -> list[dict]:
    get_or_404(db, Account, account_id)
    return reports.reconciliation_report(db, account_id)


# ---------------------------------------------------------------- categories

@router.get("/categories", response_model=list[CategoryOut], tags=["categories"])
def list_categories(user: CurrentUser, db: DB, include_archived: bool = False) -> list[Category]:
    q = select(Category).order_by(Category.kind, Category.sort_order, Category.name)
    if not include_archived:
        q = q.where(Category.archived_at.is_(None))
    return list(db.scalars(q))


def _check_parent(db, parent_id: int | None, kind: str) -> None:  # type: ignore[no-untyped-def]
    if parent_id is None:
        return
    parent = get_or_404(db, Category, parent_id)
    if parent.parent_id is not None:
        raise DomainError("depth", "Categories have at most two levels")
    if parent.kind != kind:
        raise DomainError("kind", "A subcategory must have the same kind as its parent")


@router.post("/categories", response_model=CategoryOut, status_code=201, tags=["categories"])
def create_category(body: CategoryIn, user: CurrentUser, db: DB) -> Category:
    _check_parent(db, body.parent_id, body.kind)
    data = body.model_dump()
    data["name_i18n"] = json.dumps(body.name_i18n, ensure_ascii=False) if body.name_i18n else None
    cat = Category(**data, created_by=user.id, updated_by=user.id)
    db.add(cat)
    db.flush()
    return cat


@router.patch("/categories/{category_id}", response_model=CategoryOut, tags=["categories"])
def patch_category(category_id: int, body: CategoryPatch, user: CurrentUser, db: DB) -> Category:
    cat = get_or_404(db, Category, category_id)
    if body.set_parent:
        if body.parent_id is not None and cat.children:
            raise DomainError("depth", "A category with subcategories cannot become a subcategory")
        _check_parent(db, body.parent_id, cat.kind)
        cat.parent_id = body.parent_id
    for k in ("name", "default_cost_type", "description", "sort_order"):
        if getattr(body, k) is not None:
            setattr(cat, k, getattr(body, k))
    if body.name_i18n is not None:
        cat.name_i18n = json.dumps(body.name_i18n, ensure_ascii=False)
    if body.archived is not None:
        cat.archived_at = now() if body.archived else None
    cat.updated_by = user.id
    return cat


@router.post("/categories/merge", tags=["categories"])
def merge_categories(body: MergeIn, user: CurrentUser, db: DB) -> dict:
    src, dst = get_or_404(db, Category, body.source_id), get_or_404(db, Category, body.target_id)
    if src.kind != dst.kind:
        raise DomainError("kind", "Can only merge categories of the same kind")
    if src.children:
        raise DomainError("children", "Move or merge the subcategories first")
    moved = db.execute(update(TxnSplit).where(TxnSplit.category_id == src.id).values(category_id=dst.id)).rowcount
    db.execute(update(BudgetLine).where(BudgetLine.category_id == src.id).values(category_id=dst.id))
    db.execute(update(BudgetTemplateLine).where(BudgetTemplateLine.category_id == src.id).values(category_id=dst.id))
    src.archived_at = now()
    audit(db, user.id, "category", src.id, "update", after={"merged_into": dst.id, "splits_moved": moved})
    return {"splits_moved": moved}


# ---------------------------------------------------------------- projects

@router.get("/projects", response_model=list[ProjectOut], tags=["projects"])
def list_projects(user: CurrentUser, db: DB) -> list[Project]:
    return list(db.scalars(select(Project).order_by(Project.archived_at.is_not(None), Project.start_date.desc())))


@router.post("/projects", response_model=ProjectOut, status_code=201, tags=["projects"])
def create_project(body: ProjectIn, user: CurrentUser, db: DB) -> Project:
    p = Project(**body.model_dump(), created_by=user.id, updated_by=user.id)
    db.add(p)
    db.flush()
    return p


@router.patch("/projects/{project_id}", response_model=ProjectOut, tags=["projects"])
def patch_project(project_id: int, body: dict, user: CurrentUser, db: DB) -> Project:
    p = get_or_404(db, Project, project_id)
    data = ProjectIn(**{**ProjectOut.model_validate(p).model_dump(), **body}).model_dump()
    for k, v in data.items():
        setattr(p, k, v)
    if "archived" in body:
        p.archived_at = now() if body["archived"] else None
    return p


@router.get("/projects/{project_id}/summary", tags=["projects"])
def project_summary(project_id: int, user: CurrentUser, db: DB) -> dict:
    return reports.project_summary(db, get_or_404(db, Project, project_id))


# ---------------------------------------------------------------- earmarks

@router.get("/earmarks", response_model=list[EarmarkOut], tags=["earmarks"])
def list_earmarks(user: CurrentUser, db: DB) -> list[EarmarkOut]:
    bals = positions.earmark_balances(db, date.today())
    out = []
    for e in db.scalars(select(Earmark).where(Earmark.archived_at.is_(None)).order_by(Earmark.name)):
        o = EarmarkOut.model_validate(e)
        o.balance = bals.get(e.id, 0)
        out.append(o)
    return out


@router.post("/earmarks", response_model=EarmarkOut, status_code=201, tags=["earmarks"])
def create_earmark(body: EarmarkIn, user: CurrentUser, db: DB) -> EarmarkOut:
    e = Earmark(**body.model_dump(), created_by=user.id, updated_by=user.id)
    db.add(e)
    db.flush()
    return EarmarkOut.model_validate(e)


@router.get("/earmarks/{earmark_id}/movements", tags=["earmarks"])
def earmark_movements(earmark_id: int, user: CurrentUser, db: DB) -> list[dict]:
    rows = db.execute(select(Txn.id, Txn.date, Txn.description, TxnSplit.amount, TxnSplit.note).join(TxnSplit)
                      .where(TxnSplit.earmark_id == earmark_id).order_by(Txn.date.desc()))
    return [{"txn_id": r[0], "date": r[1], "description": r[2], "amount": r[3], "note": r[4]} for r in rows]


# ---------------------------------------------------------------- assets & investments

@router.get("/assets", response_model=list[AssetOut], tags=["assets"])
def list_assets(user: CurrentUser, db: DB) -> list[AssetOut]:
    values = {v["asset"].id: v for v in positions.asset_values(db, date.today())}
    out = []
    for a in db.scalars(select(Asset).where(Asset.archived_at.is_(None)).order_by(Asset.name)):
        o = AssetOut.model_validate(a)
        if a.id in values:
            o.value, o.valued_on = values[a.id]["value"], values[a.id]["valued_on"]
        out.append(o)
    return out


@router.post("/assets", response_model=AssetOut, status_code=201, tags=["assets"])
def create_asset(body: AssetIn, user: CurrentUser, db: DB) -> AssetOut:
    data = body.model_dump()
    data["include_in_net_worth"] = int(body.include_in_net_worth)
    a = Asset(**data, created_by=user.id, updated_by=user.id)
    db.add(a)
    db.flush()
    return AssetOut.model_validate(a)


@router.patch("/assets/{asset_id}", response_model=AssetOut, tags=["assets"])
def patch_asset(asset_id: int, body: dict, user: CurrentUser, db: DB) -> AssetOut:
    a = get_or_404(db, Asset, asset_id)
    for k in ("name", "acquired_date", "acquired_value", "disposed_date", "disposed_value"):
        if k in body:
            setattr(a, k, date.fromisoformat(body[k]) if k.endswith("date") and body[k] else body[k])
    if "include_in_net_worth" in body:
        a.include_in_net_worth = int(bool(body["include_in_net_worth"]))
    if "archived" in body:
        a.archived_at = now() if body["archived"] else None
    return AssetOut.model_validate(a)


@router.get("/assets/{asset_id}/valuations", response_model=list[ValuationOut], tags=["assets"])
def valuations(asset_id: int, user: CurrentUser, db: DB) -> list[AssetValuation]:
    return list(db.scalars(select(AssetValuation).where(AssetValuation.asset_id == asset_id).order_by(AssetValuation.date)))


@router.post("/assets/{asset_id}/valuations", response_model=ValuationOut, status_code=201, tags=["assets"])
def add_valuation(asset_id: int, body: ValuationIn, user: CurrentUser, db: DB) -> AssetValuation:
    get_or_404(db, Asset, asset_id)
    v = db.execute(select(AssetValuation).where(AssetValuation.asset_id == asset_id, AssetValuation.date == body.date)).scalar_one_or_none()
    if v is None:
        v = AssetValuation(asset_id=asset_id, **body.model_dump())
        db.add(v)
    else:
        v.value, v.source = body.value, body.source
    db.flush()
    return v


@router.get("/securities", response_model=list[SecurityOut], tags=["investments"])
def list_securities(user: CurrentUser, db: DB) -> list[Security]:
    return list(db.scalars(select(Security).order_by(Security.name)))


@router.post("/securities", response_model=SecurityOut, status_code=201, tags=["investments"])
def create_security(body: SecurityIn, user: CurrentUser, db: DB) -> Security:
    s = Security(**body.model_dump())
    db.add(s)
    db.flush()
    return s


@router.patch("/securities/{security_id}", response_model=SecurityOut, tags=["investments"])
def patch_security(security_id: int, body: dict, user: CurrentUser, db: DB) -> Security:
    s = get_or_404(db, Security, security_id)
    for k in ("symbol", "isin", "name", "price_source"):
        if k in body:
            setattr(s, k, body[k])
    return s


@router.post("/securities/{security_id}/prices", status_code=201, tags=["investments"])
def add_price(security_id: int, body: PriceIn, user: CurrentUser, db: DB) -> dict:
    get_or_404(db, Security, security_id)
    p = db.get(SecurityPrice, (security_id, body.date))
    if p is None:
        db.add(SecurityPrice(security_id=security_id, date=body.date, price=body.price))
    else:
        p.price = body.price
    return {"security_id": security_id, "date": body.date, "price": str(body.price)}


@router.get("/investments/holdings", tags=["investments"])
def holdings(user: CurrentUser, db: DB, on: date | None = None) -> list[dict]:
    on = on or date.today()
    book = RateBook(db)
    out = []
    for h in positions.holdings(db, on):
        trades = db.execute(
            select(InvestmentTrade.units, InvestmentTrade.price, InvestmentTrade.fees).join(Txn)
            .where(InvestmentTrade.account_id == h["account_id"], InvestmentTrade.security_id == h["security_id"],
                   Txn.date <= on)
        ).all()
        invested = sum(Decimal(u) * Decimal(p) * 100 + f for u, p, f in trades)
        out.append({**h, "units": str(h["units"]), "price": str(h["price"]),
                    "value_ref": book.to_ref(h["value"], h["currency"], on).amount, "invested": int(invested)})
    return out


# ---------------------------------------------------------------- debts

def _debt_out(db, d: Debt, on: date) -> DebtOut:  # type: ignore[no-untyped-def]
    o = DebtOut.model_validate(d)
    o.outstanding = debt_svc.outstanding(db, d, on)
    return o


@router.get("/debts", response_model=list[DebtOut], tags=["debts"])
def list_debts(user: CurrentUser, db: DB) -> list[DebtOut]:
    return [_debt_out(db, d, date.today()) for d in db.scalars(select(Debt).where(Debt.archived_at.is_(None)).order_by(Debt.id))]


@router.post("/debts", response_model=DebtOut, status_code=201, tags=["debts"])
def create_debt(body: DebtIn, user: CurrentUser, db: DB) -> DebtOut:
    d = Debt(**body.model_dump(exclude={"rate_periods"}), created_by=user.id, updated_by=user.id)
    d.rate_periods = [DebtRatePeriod(**r.model_dump()) for r in body.rate_periods]
    db.add(d)
    db.flush()
    return _debt_out(db, d, date.today())


@router.patch("/debts/{debt_id}", response_model=DebtOut, tags=["debts"])
def patch_debt(debt_id: int, body: DebtPatch, user: CurrentUser, db: DB) -> DebtOut:
    d = get_or_404(db, Debt, debt_id)
    for k, v in body.model_dump(exclude_unset=True, exclude={"rate_periods"}).items():
        setattr(d, k, v)
    if body.rate_periods is not None:
        d.rate_periods = [DebtRatePeriod(**r.model_dump()) for r in body.rate_periods]
    db.flush()
    db.refresh(d)
    return _debt_out(db, d, date.today())


@router.get("/debts/{debt_id}/schedule", tags=["debts"])
def debt_schedule(debt_id: int, user: CurrentUser, db: DB) -> list[dict]:
    d = get_or_404(db, Debt, debt_id)
    parts = d.parts if d.repayment_type == "group" else [d]
    rows: dict[date, dict] = {}
    for part in parts:
        for r in debt_svc.schedule(db, part):
            acc = rows.setdefault(r.date, {"date": r.date, "payment": 0, "interest": 0, "principal": 0, "balance_after": 0})
            for k in ("payment", "interest", "principal", "balance_after"):
                acc[k] += getattr(r, k)
    # actual payments per month
    ids = [p.id for p in parts]
    actual = dict(db.execute(select(func.substr(Txn.date, 1, 7), func.sum(TxnSplit.amount)).join(TxnSplit)
                             .where(TxnSplit.debt_id.in_(ids), TxnSplit.amount < 0).group_by(func.substr(Txn.date, 1, 7))).all())
    ordered = sorted(rows.values(), key=lambda x: x["date"])
    return [{**r, "actual_principal": -int(actual.get(r["date"].strftime("%Y-%m"), 0))} for r in ordered]


@router.get("/debts/{debt_id}/snapshots", tags=["debts"])
def debt_snapshots(debt_id: int, user: CurrentUser, db: DB) -> list[dict]:
    return [{"id": s.id, "date": s.date, "balance": s.balance, "note": s.note} for s in
            db.scalars(select(DebtBalanceSnapshot).where(DebtBalanceSnapshot.debt_id == debt_id).order_by(DebtBalanceSnapshot.date))]


@router.post("/debts/{debt_id}/snapshots", status_code=201, tags=["debts"])
def add_snapshot(debt_id: int, body: SnapshotIn, user: CurrentUser, db: DB) -> dict:
    d = get_or_404(db, Debt, debt_id)
    if d.repayment_type == "group":
        raise DomainError("debt_group", "Add snapshots on the loan parts")
    s = DebtBalanceSnapshot(debt_id=debt_id, **body.model_dump())
    db.add(s)
    db.flush()
    return {"id": s.id}


@router.post("/debts/suggest-split", tags=["debts"])
def suggest_split(body: SplitSuggestIn, user: CurrentUser, db: DB) -> list[dict]:
    return debt_svc.suggest_payment_splits(db, body.debt_id, body.date, body.amount)

