import csv
import io
import json
from datetime import date

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.api.schemas import BudgetLineIn, BudgetLineOut, BudgetLinePatch, TemplateLineIn, TemplateLineOut
from app.db.models import Account, BudgetLine, BudgetTemplateLine, Category, Txn
from app.domain.money import from_minor
from app.services import reports
from app.services.budget import generate_month
from app.services.common import get_or_404

router = APIRouter()


# ---------------------------------------------------------------- budget

@router.get("/budget/template", response_model=list[TemplateLineOut], tags=["budget"])
def template(user: CurrentUser, db: DB) -> list[BudgetTemplateLine]:
    return list(db.scalars(select(BudgetTemplateLine).order_by(BudgetTemplateLine.category_id)))


@router.post("/budget/template", response_model=TemplateLineOut, status_code=201, tags=["budget"])
def add_template(body: TemplateLineIn, user: CurrentUser, db: DB) -> BudgetTemplateLine:
    t = BudgetTemplateLine(**body.model_dump(), created_by=user.id, updated_by=user.id)
    db.add(t)
    db.flush()
    return t


@router.put("/budget/template/{line_id}", response_model=TemplateLineOut, tags=["budget"])
def put_template(line_id: int, body: TemplateLineIn, user: CurrentUser, db: DB) -> BudgetTemplateLine:
    t = get_or_404(db, BudgetTemplateLine, line_id)
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    return t


@router.delete("/budget/template/{line_id}", status_code=204, tags=["budget"])
def delete_template(line_id: int, user: CurrentUser, db: DB) -> None:
    db.delete(get_or_404(db, BudgetTemplateLine, line_id))


@router.post("/budget/{month}/generate", tags=["budget"])
def generate(month: str, user: CurrentUser, db: DB) -> dict:
    return {"created": generate_month(db, month, user.id)}


@router.get("/budget/{month}", response_model=list[BudgetLineOut], tags=["budget"])
def month_lines(month: str, user: CurrentUser, db: DB) -> list[BudgetLine]:
    return list(db.scalars(select(BudgetLine).where(BudgetLine.month == month)))


@router.post("/budget/{month}/lines", response_model=BudgetLineOut, status_code=201, tags=["budget"])
def add_line(month: str, body: BudgetLineIn, user: CurrentUser, db: DB) -> BudgetLine:
    line = BudgetLine(month=month, **body.model_dump(), created_by=user.id, updated_by=user.id)
    db.add(line)
    db.flush()
    return line


@router.patch("/budget/lines/{line_id}", response_model=BudgetLineOut, tags=["budget"])
def patch_line(line_id: int, body: BudgetLinePatch, user: CurrentUser, db: DB) -> BudgetLine:
    line = get_or_404(db, BudgetLine, line_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(line, k, v)
    return line


@router.delete("/budget/lines/{line_id}", status_code=204, tags=["budget"])
def delete_line(line_id: int, user: CurrentUser, db: DB) -> None:
    db.delete(get_or_404(db, BudgetLine, line_id))


# ---------------------------------------------------------------- reports

@router.get("/reports/month/{month}", tags=["reports"])
def month(month: str, user: CurrentUser, db: DB, native: bool = False) -> dict:
    return reports.month_summary(db, month, native)


@router.get("/reports/year/{year}", tags=["reports"])
def year(year: int, user: CurrentUser, db: DB, native: bool = False) -> dict:
    return reports.year_overview(db, year, native)


@router.get("/reports/net-worth", tags=["reports"])
def net_worth(user: CurrentUser, db: DB, start: date, end: date | None = None) -> list[dict]:
    return reports.net_worth_series(db, start, end or date.today())


@router.get("/reports/net-worth-bridge", tags=["reports"])
def bridge(user: CurrentUser, db: DB, start: date, end: date) -> dict:
    return reports.net_worth_bridge(db, start, end)


@router.get("/reports/balances", tags=["reports"])
def balances(user: CurrentUser, db: DB, on: date | None = None) -> dict:
    return reports.balances(db, on or date.today())


@router.get("/reports/budget/{month}", tags=["reports"])
def budget(month: str, user: CurrentUser, db: DB) -> dict:
    return reports.budget_status(db, month)


@router.get("/reports/category-trend", tags=["reports"])
def category_trend(category_id: int, start: date, end: date, user: CurrentUser, db: DB) -> list[dict]:
    return reports.category_trend(db, category_id, start, end)


@router.get("/reports/debts", tags=["reports"])
def debts(user: CurrentUser, db: DB, on: date | None = None) -> list[dict]:
    return reports.debt_overview(db, on or date.today())


# ---------------------------------------------------------------- export

@router.get("/export/txns.csv", tags=["export"])
def export_csv(user: CurrentUser, db: DB) -> StreamingResponse:
    accounts = {a.id: a for a in db.scalars(select(Account))}
    cats = {c.id: c for c in db.scalars(select(Category))}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["txn_id", "date", "kind", "account", "amount", "currency", "category", "subcategory", "cost_type",
                "project_id", "description", "counterparty"])
    for t in db.scalars(select(Txn).order_by(Txn.date, Txn.id)):
        account = accounts[t.legs[0].account_id] if t.legs else None
        for s in t.splits or [None]:
            cat = cats.get(s.category_id) if s and s.category_id else None
            top, sub = (cats[cat.parent_id], cat) if cat and cat.parent_id else (cat, None)
            amount = s.amount if s else sum(leg.amount for leg in t.legs)
            ccy = s.currency if s else (account.currency if account else "")
            w.writerow([t.id, t.date, t.kind, account.name if account else "", from_minor(amount, ccy or "EUR"), ccy,
                        top.name if top else "", sub.name if sub else "", s.cost_type if s else "",
                        s.project_id if s else "", t.description, t.counterparty or ""])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=transactions.csv"})


@router.get("/export/full.json", tags=["export"])
def export_json(user: CurrentUser, db: DB) -> StreamingResponse:
    from app.db import Base

    data = {}
    for table in Base.metadata.sorted_tables:
        if table.name in ("user", "auth_session"):
            continue
        data[table.name] = [dict(r._mapping) for r in db.execute(table.select())]
    return StreamingResponse(iter([json.dumps(data, default=str, ensure_ascii=False)]), media_type="application/json",
                             headers={"Content-Disposition": "attachment; filename=budget-export.json"})
