"""Goals router — CRUD + contribution tracking."""
from decimal import Decimal
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import Goal, GoalStatus
from app.schemas import GoalCreate, GoalUpdate, GoalContribution, GoalResponse, OKResponse
from app.security import get_current_user

router = APIRouter()


def _enrich(goal: Goal) -> GoalResponse:
    pct = round(float(goal.current_amount / goal.target_amount * 100), 1) if goal.target_amount else 0.0
    remaining = goal.target_amount - goal.current_amount
    monthly = None
    if goal.target_date and remaining > 0:
        from datetime import date
        today  = date.today()
        months = max(1, (goal.target_date.year - today.year) * 12 + (goal.target_date.month - today.month))
        monthly = round(remaining / months, 2)

    return GoalResponse(
        id=goal.id,
        name=goal.name,
        description=goal.description,
        target_amount=goal.target_amount,
        current_amount=goal.current_amount,
        target_date=goal.target_date,
        status=goal.status.value,
        color=goal.color,
        icon=goal.icon,
        percent_complete=pct,
        monthly_needed=monthly,
        created_at=goal.created_at,
        updated_at=goal.updated_at,
    )


@router.get("", response_model=list[GoalResponse])
async def list_goals(
    status: Optional[str] = None,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(Goal).where(Goal.user_id == current_user.id)
    if status:
        q = q.where(Goal.status == GoalStatus(status))
    result = await db.execute(q)
    return [_enrich(g) for g in result.scalars().all()]


@router.post("", response_model=GoalResponse, status_code=201)
async def create_goal(
    body: GoalCreate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    goal = Goal(user_id=current_user.id, **body.model_dump())
    db.add(goal)
    await db.flush()
    await db.refresh(goal)
    return _enrich(goal)


@router.patch("/{goal_id}", response_model=GoalResponse)
async def update_goal(
    goal_id: int,
    body: GoalUpdate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Goal).where(Goal.id == goal_id))
    goal = result.scalar_one_or_none()
    if not goal or goal.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Goal not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(goal, k, GoalStatus(v) if k == "status" else v)
    await db.flush()
    await db.refresh(goal)
    return _enrich(goal)


@router.post("/{goal_id}/contribute", response_model=GoalResponse)
async def contribute_to_goal(
    goal_id: int,
    body: GoalContribution,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add money toward a savings goal."""
    result = await db.execute(select(Goal).where(Goal.id == goal_id))
    goal = result.scalar_one_or_none()
    if not goal or goal.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Goal not found")
    goal.current_amount += body.amount
    if goal.current_amount >= goal.target_amount:
        goal.status = GoalStatus.COMPLETED
    await db.flush()
    await db.refresh(goal)
    return _enrich(goal)


@router.delete("/{goal_id}", response_model=OKResponse)
async def delete_goal(
    goal_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Goal).where(Goal.id == goal_id))
    goal = result.scalar_one_or_none()
    if not goal or goal.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Goal not found")
    await db.delete(goal)
    return OKResponse(message=f"Goal {goal_id} deleted")
