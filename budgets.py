"""
Budgets — create/update monthly budget, fetch with live spending totals per category.
"""

from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Budget, BudgetItem, Transaction, TransactionType
from app.schemas import BudgetCreate, BudgetResponse, BudgetItemResponse, CategoryResponse, OKResponse
from app.security import get_current_user

router = APIRouter()


async def _enrich_budget(budget: Budget, db: AsyncSession) -> BudgetResponse:
    """Attach live 'spent' totals to each budget item from actual transactions."""
    items_out = []
    total_allocated = Decimal("0")
    total_spent     = Decimal("0")

    for item in budget.items:
        spent_q = await db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                and_(
                    Transaction.user_id    == budget.user_id,
                    Transaction.category_id == item.category_id,
                    Transaction.type       == TransactionType.EXPENSE,
                    func.extract("month", Transaction.transaction_date) == budget.month,
                    func.extract("year",  Transaction.transaction_date) == budget.year,
                )
            )
        )
        spent      = Decimal(str(spent_q.scalar_one()))
        remaining  = item.allocated - spent
        pct_used   = round(float(spent / item.allocated * 100), 1) if item.allocated else 0.0

        total_allocated += item.allocated
        total_spent     += spent

        items_out.append(BudgetItemResponse(
            id=item.id,
            category_id=item.category_id,
            category=CategoryResponse.model_validate(item.category),
            allocated=item.allocated,
            spent=spent,
            remaining=remaining,
            percent_used=pct_used,
        ))

    return BudgetResponse(
        id=budget.id,
        month=budget.month,
        year=budget.year,
        monthly_income=budget.monthly_income,
        savings_goal=budget.savings_goal,
        notes=budget.notes,
        total_allocated=total_allocated,
        total_spent=total_spent,
        total_remaining=total_allocated - total_spent,
        items=items_out,
        created_at=budget.created_at,
        updated_at=budget.updated_at,
    )


@router.get("", response_model=list[BudgetResponse])
async def list_budgets(
    year: int = Query(None),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(Budget).where(Budget.user_id == current_user.id)
    if year:
        q = q.where(Budget.year == year)
    q = q.order_by(Budget.year.desc(), Budget.month.desc())
    result  = await db.execute(q)
    budgets = result.scalars().all()
    return [await _enrich_budget(b, db) for b in budgets]


@router.get("/current", response_model=BudgetResponse)
async def get_current_budget(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Returns the most recently created budget for convenience."""
    result = await db.execute(
        select(Budget)
        .where(Budget.user_id == current_user.id)
        .order_by(Budget.year.desc(), Budget.month.desc())
        .limit(1)
    )
    budget = result.scalar_one_or_none()
    if not budget:
        raise HTTPException(status_code=404, detail="No budget found. Create one first.")
    return await _enrich_budget(budget, db)


@router.get("/{budget_id}", response_model=BudgetResponse)
async def get_budget(
    budget_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Budget).where(Budget.id == budget_id).options(selectinload(Budget.items).selectinload(BudgetItem.category)))
    budget = result.scalar_one_or_none()
    if not budget or budget.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Budget not found")
    return await _enrich_budget(budget, db)


@router.post("", response_model=BudgetResponse, status_code=201)
async def create_budget(
    body: BudgetCreate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Prevent duplicates for same month/year
    existing = await db.execute(
        select(Budget).where(
            Budget.user_id == current_user.id,
            Budget.month   == body.month,
            Budget.year    == body.year,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail=f"Budget for {body.month}/{body.year} already exists. Use PATCH to update."
        )

    budget = Budget(
        user_id=current_user.id,
        month=body.month,
        year=body.year,
        monthly_income=body.monthly_income,
        savings_goal=body.savings_goal,
        notes=body.notes,
    )
    db.add(budget)
    await db.flush()

    for item_data in body.items:
        db.add(BudgetItem(
            budget_id=budget.id,
            category_id=item_data.category_id,
            allocated=item_data.allocated,
        ))

    await db.flush()
    result2 = await db.execute(select(Budget).where(Budget.id == budget.id).options(selectinload(Budget.items).selectinload(BudgetItem.category)))
    budget = result2.scalar_one()
    return await _enrich_budget(budget, db)


@router.patch("/{budget_id}", response_model=BudgetResponse)
async def update_budget(
    budget_id: int,
    body: BudgetCreate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Budget).where(Budget.id == budget_id))
    budget = result.scalar_one_or_none()
    if not budget or budget.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Budget not found")

    budget.monthly_income = body.monthly_income
    budget.savings_goal   = body.savings_goal
    budget.notes          = body.notes

    # Replace all items
    for item in budget.items:
        await db.delete(item)
    await db.flush()

    for item_data in body.items:
        db.add(BudgetItem(
            budget_id=budget.id,
            category_id=item_data.category_id,
            allocated=item_data.allocated,
        ))

    await db.flush()
    result2 = await db.execute(select(Budget).where(Budget.id == budget.id).options(selectinload(Budget.items).selectinload(BudgetItem.category)))
    budget = result2.scalar_one()
    return await _enrich_budget(budget, db)


@router.delete("/{budget_id}", response_model=OKResponse)
async def delete_budget(
    budget_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Budget).where(Budget.id == budget_id))
    budget = result.scalar_one_or_none()
    if not budget or budget.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Budget not found")
    await db.delete(budget)
    return OKResponse(message=f"Budget {budget_id} deleted")
