"""AI categoriser (Backend.md §6). Suggests kind/category/cost type/project for import rows; never commits.

Uses the Anthropic SDK with structured outputs (`messages.parse` + Pydantic) and caches the stable system
prompt (instructions + category tree + projects). Learning happens through context: each request carries
the user's most similar confirmed transactions as examples."""

import json
import logging
import time
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import (
    Account,
    AiCallLog,
    AiSuggestion,
    Category,
    ImportBatch,
    ImportRow,
    Project,
    Txn,
    TxnSplit,
)
from app.domain.money import from_minor
from app.services.common import DomainError, get_setting

log = logging.getLogger(__name__)
CHUNK = 40


class RowSuggestion(BaseModel):
    i: int = Field(description="Index of the input row")
    kind: Literal["expense", "income", "transfer"]
    category_id: int | None = Field(description="Most specific matching category id (subcategory if one fits)")
    cost_type: Literal["fixed", "variable", "one_time"] | None = Field(description="Only for expenses")
    project_id: int | None
    confidence: float = Field(description="0.0-1.0")
    rationale: str = Field(description="At most 12 words")


class Suggestions(BaseModel):
    items: list[RowSuggestion]


INSTRUCTIONS = """You categorise household bank transactions for a family living in the Netherlands \
(previously Russia). Amounts are signed: negative = money out, positive = money in.

For every input row return one item with the same index `i`:
- kind: expense (money out for goods/services), income (salary, fees, refunds, interest), or transfer \
(money moving between the family's own accounts; only when clearly so).
- category_id: pick from the category tree below. Prefer a subcategory id when one fits; otherwise the \
top-level id. Expense rows need an expense category, income rows an income category. Refunds of purchases \
use the expense category of the purchase (positive amount). Use null only if nothing fits.
- cost_type (expenses only): fixed = recurring contractual (rent/mortgage, insurance, subscriptions, \
utilities, school fees); variable = everyday spending that varies (groceries, restaurants, fuel); \
one_time = unusual one-off purchases (furniture, renovation, travel bookings, large items).
- project_id: only when the row clearly belongs to an active project (by date range and description).
- confidence: your honest probability that the category is what the user would pick.
The examples show how this user categorised similar transactions before; follow their habits over \
generic logic. Descriptions may be Dutch, Russian or English."""


def _tree_text(session: Session) -> str:
    cats = list(session.scalars(select(Category).where(Category.archived_at.is_(None)).order_by(Category.kind, Category.name)))
    lines = []
    for kind in ("expense", "income"):
        lines.append(f"## {kind} categories")
        for c in [c for c in cats if c.kind == kind and c.parent_id is None]:
            hint = f" — {c.description}" if c.description else ""
            ct = f" [default {c.default_cost_type}]" if c.default_cost_type else ""
            lines.append(f"- {c.id}: {c.name}{ct}{hint}")
            for s in [s for s in cats if s.parent_id == c.id]:
                hint = f" — {s.description}" if s.description else ""
                ct = f" [default {s.default_cost_type}]" if s.default_cost_type else ""
                lines.append(f"  - {s.id}: {c.name} › {s.name}{ct}{hint}")
    projects = list(session.scalars(select(Project).where(Project.archived_at.is_(None)).order_by(Project.name)))
    lines.append("## active projects")
    lines += [f"- {p.id}: {p.name} ({p.start_date or '?'} – {p.end_date or 'open'})" for p in projects] or ["(none)"]
    return "\n".join(lines)


def system_prompt(session: Session) -> str:
    return INSTRUCTIONS + "\n\n" + _tree_text(session)


def _examples(session: Session, row: ImportRow, limit: int = 6) -> list[str]:
    """Confirmed transactions with a similar counterparty/description (simple token LIKE search)."""
    text = f"{row.counterparty or ''} {row.description or ''}".lower()
    tokens = [t for t in "".join(ch if ch.isalnum() else " " for ch in text).split() if len(t) >= 3][:4]
    if not tokens:
        return []
    conds = [func.lower(Txn.description).contains(t) for t in tokens] + [
        func.lower(func.coalesce(Txn.counterparty, "")).contains(t) for t in tokens
    ]
    q = (
        select(Txn.description, Txn.counterparty, TxnSplit.amount, TxnSplit.currency, Category.id, Category.name,
               TxnSplit.cost_type)
        .join(TxnSplit, TxnSplit.txn_id == Txn.id)
        .join(Category, Category.id == TxnSplit.category_id)
        .where(or_(*conds))
        .order_by(Txn.date.desc())
        .limit(limit)
    )
    return [
        f"{cp or ''} | {desc} | {from_minor(amount, ccy)} {ccy} → category {cid} ({cname}){' ' + ct if ct else ''}"
        for desc, cp, amount, ccy, cid, cname, ct in session.execute(q)
    ]


def _row_payload(session: Session, i: int, row: ImportRow, accounts: dict[int, Account]) -> dict:
    p = json.loads(row.proposed or "{}")
    acc = accounts.get(row.account_id) if row.account_id else None
    item = {
        "i": i,
        "date": row.date.isoformat(),
        "amount": from_minor(row.amount, row.currency),
        "currency": row.currency,
        "account_type": acc.type if acc else None,
        "counterparty": row.counterparty,
        "description": row.description,
        "similar_past": _examples(session, row),
    }
    if p.get("sheet_category"):
        item["user_sheet_category"] = p["sheet_category"]
    return item


Client = Callable[..., Suggestions]


def _call_claude(model: str, system: str, rows: list[dict]) -> tuple[Suggestions, dict]:
    import anthropic

    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key) if settings.anthropic_api_key else anthropic.Anthropic()
    response = client.messages.parse(
        model=model,
        max_tokens=16000,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": "Categorise these rows:\n" + json.dumps(rows, ensure_ascii=False)}],
        output_format=Suggestions,
    )
    if response.stop_reason == "refusal":
        raise DomainError("ai_refused", "The model declined this request")
    usage = response.usage
    meta = {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_read_tokens": getattr(usage, "cache_read_input_tokens", None),
    }
    return response.parsed_output, meta


def suggest(
    session: Session, batch: ImportBatch, row_ids: list[int] | None = None,
    call: Callable[[str, str, list[dict]], tuple[Suggestions, dict]] | None = None,
) -> dict:
    """Suggest categories for rows that still need one. `call` is injectable for tests."""
    settings = get_settings()
    call = call or _call_claude
    if call is _call_claude and not settings.anthropic_api_key:
        import os

        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise DomainError("ai_unavailable", "No Anthropic API key configured (BUDGET_ANTHROPIC_API_KEY)", status=503)
    model = get_setting(session, "ai_model") or settings.ai_model_default
    rows = [
        r for r in batch.rows
        if r.status in ("new", "suggested", "accepted") and (row_ids is None or r.id in row_ids)
        and (bool(json.loads(r.proposed or "{}").get("needs_category")) or row_ids is not None)
    ]
    if not rows:
        return {"suggested": 0, "calls": 0, "errors": []}
    system = system_prompt(session)
    valid = {c.id: c for c in session.scalars(select(Category).where(Category.archived_at.is_(None)))}
    projects = {p.id for p in session.scalars(select(Project).where(Project.archived_at.is_(None)))}
    accounts = {a.id: a for a in session.scalars(select(Account))}
    done, calls, errors = 0, 0, []
    for start in range(0, len(rows), CHUNK):
        chunk = rows[start: start + CHUNK]
        payload = [_row_payload(session, i, r, accounts) for i, r in enumerate(chunk)]
        t0 = time.monotonic()
        entry = AiCallLog(model=model, batch_id=batch.id)
        try:
            result, meta = call(model, system, payload)
            entry.input_tokens = meta.get("input_tokens")
            entry.output_tokens = meta.get("output_tokens")
            entry.cache_read_tokens = meta.get("cache_read_tokens")
        except DomainError as e:
            entry.error = e.message
            errors.append(e.message)
            continue
        except Exception as e:  # network / API errors: rows stay without suggestion (Backend.md §6.2)
            log.exception("AI call failed")
            entry.error = str(e)[:500]
            errors.append(str(e)[:200])
            continue
        finally:
            entry.duration_ms = int((time.monotonic() - t0) * 1000)
            session.add(entry)
            calls += 1
        for item in result.items:
            if not 0 <= item.i < len(chunk):
                continue
            row = chunk[item.i]
            cat = valid.get(item.category_id) if item.category_id else None
            want_kind = "expense" if row.amount < 0 else "income"
            if cat is not None and item.kind != "transfer" and cat.kind != want_kind and not (
                cat.kind == "expense" and row.amount > 0  # refund on an expense category
            ):
                cat = None
            project_id = item.project_id if item.project_id in projects else None
            cost_type = item.cost_type if (cat and cat.kind == "expense") else None
            if row.suggestion is not None:
                session.delete(row.suggestion)
                session.flush()
            row.suggestion = AiSuggestion(
                model=model, kind=item.kind, category_id=cat.id if cat else None, cost_type=cost_type,
                project_id=project_id, confidence=str(max(0.0, min(1.0, item.confidence))), rationale=item.rationale[:300],
            )
            p = json.loads(row.proposed or "{}")
            sheet_cat = p.get("sheet_category_id")
            agrees = cat is not None and sheet_cat is not None and sheet_cat in (cat.id, cat.parent_id)
            if sheet_cat is not None:
                p["ai_agrees_with_sheet"] = agrees
            if not p.get("edited"):
                # the user's own sheet category wins; the AI may only refine it to a subcategory
                use = cat if (sheet_cat is None or agrees) else valid.get(sheet_cat)
                for split in p.get("splits") or []:
                    if not any(split.get(k) for k in ("debt_id", "earmark_id", "asset_id")):
                        split["category_id"] = use.id if use else None
                        split["cost_type"] = cost_type if use is cat else split.get("cost_type")
                        split["project_id"] = project_id
                p["needs_category"] = use is None
                row.proposed = json.dumps(p, default=str)
            if row.status == "new":
                row.status = "suggested"
            done += 1
    return {"suggested": done, "calls": calls, "errors": errors}
