"""Reports — Pro-gated analytics: annual summary, category breakdown, trends."""

from decimal import Decimal
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.database import get_db
from app.models import Transaction, Category, TransactionType
from app.schemas import AnnualReport, MonthlySummary, CategoryBreakdown
from app.security import require_pro   # Pro gate

router = APIRouter()


@router.get("/annual/{year}", response_model=AnnualReport)
async def annual_report(
    year: int,
    current_user=Depends(require_pro),
    db: AsyncSession = Depends(get_db),
):
    """Full year breakdown: monthly summaries + category totals. Pro only."""
    summaries = []
    total_income   = Decimal("0")
    total_expenses = Decimal("0")

    for month in range(1, 13):
        filters = [
            Transaction.user_id == current_user.id,
            func.extract("month", Transaction.transaction_date) == month,
            func.extract("year",  Transaction.transaction_date) == year,
        ]
        inc_q  = await db.execute(select(func.coalesce(func.sum(Transaction.amount), 0)).where(and_(*filters, Transaction.type == TransactionType.INCOME)))
        exp_q  = await db.execute(select(func.coalesce(func.sum(Transaction.amount), 0)).where(and_(*filters, Transaction.type == TransactionType.EXPENSE)))
        inc    = Decimal(str(inc_q.scalar_one()))
        exp    = Decimal(str(exp_q.scalar_one()))
        net    = inc - exp

        # Top category for month
        top_cat_q = await db.execute(
            select(Category.name, func.sum(Transaction.amount).label("total"))
            .join(Transaction, Transaction.category_id == Category.id)
            .where(and_(*filters, Transaction.type == TransactionType.EXPENSE))
            .group_by(Category.name)
            .order_by(func.sum(Transaction.amount).desc())
            .limit(1)
        )
        top = top_cat_q.first()

        summaries.append(MonthlySummary(
            month=month, year=year,
            total_income=inc, total_expenses=exp, net=net,
            savings_rate=round(float(net / inc * 100), 1) if inc else 0.0,
            top_category=top[0] if top else None,
            top_category_amount=Decimal(str(top[1])) if top else None,
        ))
        total_income   += inc
        total_expenses += exp

    # Category breakdown for the year
    cat_q = await db.execute(
        select(
            Category.id, Category.name, Category.color,
            func.sum(Transaction.amount).label("total"),
            func.count(Transaction.id).label("cnt"),
        )
        .join(Transaction, Transaction.category_id == Category.id)
        .where(
            Transaction.user_id == current_user.id,
            func.extract("year", Transaction.transaction_date) == year,
            Transaction.type == TransactionType.EXPENSE,
        )
        .group_by(Category.id, Category.name, Category.color)
        .order_by(func.sum(Transaction.amount).desc())
    )
    rows = cat_q.all()
    cat_breakdowns = []
    for row in rows:
        pct = round(float(row.total / total_expenses * 100), 1) if total_expenses else 0.0
        cat_breakdowns.append(CategoryBreakdown(
            category_id=row.id,
            category_name=row.name,
            color=row.color,
            total=Decimal(str(row.total)),
            transaction_count=row.cnt,
            percent_of_total=pct,
        ))

    avg_monthly = total_expenses / 12 if total_expenses else Decimal("0")

    return AnnualReport(
        year=year,
        monthly_summaries=summaries,
        total_income=total_income,
        total_expenses=total_expenses,
        total_net=total_income - total_expenses,
        average_monthly_spend=avg_monthly,
        category_breakdown=cat_breakdowns,
    )


@router.get("/spending-trend", response_model=list[dict])
async def spending_trend(
    months: int = Query(12, ge=3, le=24),
    current_user=Depends(require_pro),
    db: AsyncSession = Depends(get_db),
):
    """Last N months of expense totals for trend charts."""
    from datetime import date
    today  = date.today()
    result = []
    for i in range(months - 1, -1, -1):
        m = (today.month - i - 1) % 12 + 1
        y = today.year - ((today.month - i - 1) // 12 + (1 if (today.month - i - 1) < 0 else 0))
        q = await db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.user_id == current_user.id,
                Transaction.type    == TransactionType.EXPENSE,
                func.extract("month", Transaction.transaction_date) == m,
                func.extract("year",  Transaction.transaction_date) == y,
            )
        )
        result.append({"month": m, "year": y, "total": float(q.scalar_one())})
    return result
