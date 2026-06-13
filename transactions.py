"""
Transactions — full CRUD with pagination, filtering, search, and bulk import.
"""

import math
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, desc

from app.database import get_db
from app.models import Transaction, Category, TransactionType
from app.schemas import (
    TransactionCreate, TransactionUpdate,
    TransactionResponse, TransactionListResponse, OKResponse
)
from app.security import get_current_user

router = APIRouter()


def _owned_or_404(txn: Transaction | None, user_id: str) -> Transaction:
    if not txn or txn.user_id != user_id:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return txn


@router.get("", response_model=TransactionListResponse)
async def list_transactions(
    page: int           = Query(1, ge=1),
    page_size: int      = Query(25, ge=1, le=100),
    category_id: Optional[int]  = None,
    type: Optional[str]         = None,
    search: Optional[str]       = None,
    date_from: Optional[date]   = None,
    date_to: Optional[date]     = None,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    filters = [Transaction.user_id == current_user.id]

    if category_id:
        filters.append(Transaction.category_id == category_id)
    if type in ("income", "expense"):
        filters.append(Transaction.type == TransactionType(type))
    if search:
        filters.append(
            or_(
                Transaction.description.ilike(f"%{search}%"),
                Transaction.merchant.ilike(f"%{search}%"),
            )
        )
    if date_from:
        filters.append(Transaction.transaction_date >= date_from)
    if date_to:
        filters.append(Transaction.transaction_date <= date_to)

    total_q = await db.execute(
        select(func.count()).select_from(Transaction).where(and_(*filters))
    )
    total = total_q.scalar_one()

    q = (
        select(Transaction)
        .where(and_(*filters))
        .order_by(desc(Transaction.transaction_date), desc(Transaction.id))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(q)
    items  = result.scalars().all()

    return TransactionListResponse(
        items=[TransactionResponse.model_validate(t) for t in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=max(1, math.ceil(total / page_size)),
    )


@router.post("", response_model=TransactionResponse, status_code=201)
async def create_transaction(
    body: TransactionCreate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.category_id:
        cat = await db.get(Category, body.category_id)
        if not cat or cat.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Category not found")

    txn = Transaction(
        user_id=current_user.id,
        description=body.description,
        amount=body.amount,
        type=TransactionType(body.type),
        category_id=body.category_id,
        transaction_date=body.transaction_date,
        notes=body.notes,
        merchant=body.merchant,
        is_recurring=body.is_recurring,
        recurring_frequency=body.recurring_frequency,
    )
    db.add(txn)
    await db.flush()
    await db.refresh(txn)
    return TransactionResponse.model_validate(txn)


@router.get("/{txn_id}", response_model=TransactionResponse)
async def get_transaction(
    txn_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Transaction).where(Transaction.id == txn_id))
    txn = _owned_or_404(result.scalar_one_or_none(), current_user.id)
    return TransactionResponse.model_validate(txn)


@router.patch("/{txn_id}", response_model=TransactionResponse)
async def update_transaction(
    txn_id: int,
    body: TransactionUpdate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Transaction).where(Transaction.id == txn_id))
    txn = _owned_or_404(result.scalar_one_or_none(), current_user.id)

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(txn, field, value)

    await db.flush()
    await db.refresh(txn)
    return TransactionResponse.model_validate(txn)


@router.delete("/{txn_id}", response_model=OKResponse)
async def delete_transaction(
    txn_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Transaction).where(Transaction.id == txn_id))
    txn = _owned_or_404(result.scalar_one_or_none(), current_user.id)
    await db.delete(txn)
    return OKResponse(message=f"Transaction {txn_id} deleted")


@router.get("/summary/monthly", response_model=dict)
async def monthly_summary(
    month: int = Query(..., ge=1, le=12),
    year:  int = Query(..., ge=2020),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Quick income vs expense totals for a given month — used by the dashboard."""
    filters = [
        Transaction.user_id == current_user.id,
        func.extract("month", Transaction.transaction_date) == month,
        func.extract("year",  Transaction.transaction_date) == year,
    ]

    income_q = await db.execute(
        select(func.coalesce(func.sum(Transaction.amount), 0))
        .where(and_(*filters, Transaction.type == TransactionType.INCOME))
    )
    expense_q = await db.execute(
        select(func.coalesce(func.sum(Transaction.amount), 0))
        .where(and_(*filters, Transaction.type == TransactionType.EXPENSE))
    )

    total_income  = income_q.scalar_one()
    total_expense = expense_q.scalar_one()

    return {
        "month": month,
        "year": year,
        "total_income": float(total_income),
        "total_expenses": float(total_expense),
        "net": float(total_income - total_expense),
        "savings_rate": round(
            float((total_income - total_expense) / total_income * 100), 1
        ) if total_income else 0.0,
    }
