"""Budget template (the sheet's 'Month' tab) and per-month plan lines."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import BudgetLine, BudgetTemplateLine


def template_lines_for(session: Session, month: str) -> list[BudgetTemplateLine]:
    return [
        t
        for t in session.scalars(select(BudgetTemplateLine))
        if t.valid_from <= month and (t.valid_to is None or t.valid_to >= month)
    ]


def generate_month(session: Session, month: str, user_id: int | None = None) -> int:
    """Create budget lines from the template for `month`. Existing lines are left untouched."""
    existing = {
        line.template_line_id
        for line in session.scalars(select(BudgetLine).where(BudgetLine.month == month))
        if line.template_line_id
    }
    created = 0
    for t in template_lines_for(session, month):
        if t.id in existing:
            continue
        session.add(
            BudgetLine(
                month=month,
                category_id=t.category_id,
                amount=t.amount,
                currency=t.currency,
                template_line_id=t.id,
                note=t.label,
                created_by=user_id,
                updated_by=user_id,
            )
        )
        created += 1
    return created
