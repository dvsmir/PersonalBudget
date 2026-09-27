import base64
from collections import defaultdict
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Header, Query
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import selectinload

from app.api.deps import DB, CurrentUser
from app.api.schemas import BulkTxnIn, TxnIn, TxnOut, TxnPage
from app.db.models import Category, Txn, TxnLeg, TxnSplit
from app.services import ledger
from app.services.common import DomainError, get_or_404

router = APIRouter(tags=["transactions"])
_idempotency: dict[str, int] = {}  # Idempotency-Key → txn id (in-memory; enough for one instance)


def _draft(body: TxnIn) -> ledger.TxnDraft:
    return ledger.TxnDraft(
        date=body.date, kind=body.kind, description=body.description, counterparty=body.counterparty, notes=body.notes,
        legs=[ledger.LegIn(**leg.model_dump()) for leg in body.legs],
        splits=[ledger.SplitIn(**s.model_dump()) for s in body.splits],
        trades=[ledger.TradeIn(**t.model_dump()) for t in body.trades],
    )


def _filtered(
    q, start: date | None, end: date | None, account_id: list[int] | None, category_id: list[int] | None,
    project_id: int | None, kind: list[str] | None, cost_type: str | None, text: str | None,
    min_amount: int | None, max_amount: int | None, source: str | None, uncategorised: bool,
):  # type: ignore[no-untyped-def]
    if start:
        q = q.where(Txn.date >= start)
    if end:
        q = q.where(Txn.date <= end)
    if account_id:
        q = q.where(exists().where(TxnLeg.txn_id == Txn.id, TxnLeg.account_id.in_(account_id)))
    if category_id:
        sub = select(Category.id).where(or_(Category.id.in_(category_id), Category.parent_id.in_(category_id)))
        q = q.where(exists().where(TxnSplit.txn_id == Txn.id, TxnSplit.category_id.in_(sub)))
    if project_id:
        q = q.where(exists().where(TxnSplit.txn_id == Txn.id, TxnSplit.project_id == project_id))
    if kind:
        q = q.where(Txn.kind.in_(kind))
    if cost_type:
        parent = select(Category.default_cost_type).where(Category.id == TxnSplit.category_id).scalar_subquery()
        q = q.where(exists().where(TxnSplit.txn_id == Txn.id, func.coalesce(TxnSplit.cost_type, parent, "variable") == cost_type))
    if text:
        like = f"%{text.lower()}%"
        q = q.where(or_(func.lower(Txn.description).like(like), func.lower(func.coalesce(Txn.counterparty, "")).like(like),
                        func.lower(func.coalesce(Txn.notes, "")).like(like)))
    if min_amount is not None or max_amount is not None:
        conds = []
        if min_amount is not None:
            conds.append(func.abs(TxnLeg.amount) >= min_amount)
        if max_amount is not None:
            conds.append(func.abs(TxnLeg.amount) <= max_amount)
        q = q.where(exists().where(TxnLeg.txn_id == Txn.id, and_(*conds)))
    if source:
        q = q.where(Txn.source == source)
    if uncategorised:
        q = q.where(exists().where(TxnSplit.txn_id == Txn.id, TxnSplit.category_id.is_(None), TxnSplit.debt_id.is_(None),
                                   TxnSplit.earmark_id.is_(None), TxnSplit.asset_id.is_(None)))
    return q


@router.get("/txns", response_model=TxnPage)
def list_txns(
    user: CurrentUser, db: DB,
    start: date | None = None, end: date | None = None,
    account_id: Annotated[list[int] | None, Query()] = None,
    category_id: Annotated[list[int] | None, Query()] = None,
    project_id: int | None = None,
    kind: Annotated[list[str] | None, Query()] = None,
    cost_type: str | None = None, text: str | None = None,
    min_amount: int | None = None, max_amount: int | None = None, source: str | None = None,
    uncategorised: bool = False,
    cursor: str | None = None, limit: int = Query(default=100, le=500),
) -> TxnPage:
    args = (start, end, account_id, category_id, project_id, kind, cost_type, text, min_amount, max_amount, source, uncategorised)
    q = _filtered(select(Txn), *args).options(selectinload(Txn.legs), selectinload(Txn.splits), selectinload(Txn.trades))
    if cursor:
        c_date, c_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
        q = q.where(or_(Txn.date < date.fromisoformat(c_date), and_(Txn.date == date.fromisoformat(c_date), Txn.id < int(c_id))))
    items = list(db.scalars(q.order_by(Txn.date.desc(), Txn.id.desc()).limit(limit + 1)))
    next_cursor = None
    if len(items) > limit:
        items = items[:limit]
        last = items[-1]
        next_cursor = base64.urlsafe_b64encode(f"{last.date.isoformat()}|{last.id}".encode()).decode()
    # totals over the whole filter (not just the page): legs per currency, excluding internal transfers
    ids = _filtered(select(Txn.id), *args).where(Txn.kind != "transfer")
    totals: dict[str, int] = defaultdict(int)
    totals_ref = int(db.execute(select(func.coalesce(func.sum(TxnLeg.amount_ref), 0)).where(TxnLeg.txn_id.in_(ids))).scalar_one())
    for ccy, amount in db.execute(
        select(TxnSplit.currency, func.sum(TxnSplit.amount)).where(TxnSplit.txn_id.in_(ids), TxnSplit.earmark_id.is_(None))
        .group_by(TxnSplit.currency)
    ):
        totals[ccy] += int(amount)
    return TxnPage(items=[TxnOut.model_validate(t) for t in items], next_cursor=next_cursor, totals=dict(totals),
                   totals_ref=totals_ref)


@router.post("/txns", response_model=TxnOut, status_code=201)
def create_txn(body: TxnIn, user: CurrentUser, db: DB,
               idempotency_key: Annotated[str | None, Header()] = None) -> TxnOut:
    if idempotency_key and idempotency_key in _idempotency:
        return TxnOut.model_validate(get_or_404(db, Txn, _idempotency[idempotency_key]))
    txn = ledger.create_txn(db, _draft(body), user.id)
    db.flush()
    db.refresh(txn)
    if idempotency_key:
        _idempotency[idempotency_key] = txn.id
    return TxnOut.model_validate(txn)


@router.get("/txns/{txn_id}", response_model=TxnOut)
def get_txn(txn_id: int, user: CurrentUser, db: DB) -> TxnOut:
    return TxnOut.model_validate(get_or_404(db, Txn, txn_id))


@router.put("/txns/{txn_id}", response_model=TxnOut)
def update_txn(txn_id: int, body: TxnIn, user: CurrentUser, db: DB,
               if_match: Annotated[str | None, Header()] = None) -> TxnOut:
    txn = get_or_404(db, Txn, txn_id)
    if if_match and if_match.strip('"') != txn.updated_at.isoformat():
        raise DomainError("conflict", "This transaction was changed by someone else", status=409)
    txn = ledger.update_txn(db, txn_id, _draft(body), user.id)
    db.flush()
    db.refresh(txn)
    return TxnOut.model_validate(txn)


@router.delete("/txns/{txn_id}", status_code=204)
def delete_txn(txn_id: int, user: CurrentUser, db: DB) -> None:
    ledger.delete_txn(db, txn_id, user.id)


@router.post("/txns/bulk-update")
def bulk_update(body: BulkTxnIn, user: CurrentUser, db: DB) -> dict:
    changed = 0
    for txn_id in body.txn_ids:
        txn = get_or_404(db, Txn, txn_id)
        draft = ledger.draft_from_txn(txn)
        for s in draft.splits:
            if s.debt_id or s.earmark_id or s.asset_id:
                continue
            if body.category_id is not None:
                s.category_id = body.category_id
            if body.cost_type is not None:
                s.cost_type = body.cost_type
            if body.project_id is not None:
                s.project_id = body.project_id
            if body.clear_project:
                s.project_id = None
        ledger.update_txn(db, txn_id, draft, user.id)
        changed += 1
    return {"updated": changed}
