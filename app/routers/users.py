"""Users router — profile management."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import Category
from app.schemas import UserResponse, UpdateUserRequest, ChangePasswordRequest, CategoryCreate, CategoryResponse, OKResponse
from app.security import get_current_user, verify_password, hash_password

router = APIRouter()


@router.get("/me", response_model=UserResponse)
async def get_profile(current_user=Depends(get_current_user)):
    return UserResponse.model_validate(current_user)


@router.patch("/me", response_model=UserResponse)
async def update_profile(
    body: UpdateUserRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(current_user, k, v)
    await db.flush()
    await db.refresh(current_user)
    return UserResponse.model_validate(current_user)


@router.post("/me/change-password", response_model=OKResponse)
async def change_password(
    body: ChangePasswordRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    current_user.hashed_password = hash_password(body.new_password)
    return OKResponse(message="Password updated successfully")


@router.delete("/me", response_model=OKResponse)
async def delete_account(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    current_user.is_active = False
    return OKResponse(message="Account deactivated")


# ── Categories (sub-resource of user) ────────────────────────────────────────

@router.get("/me/categories", response_model=list[CategoryResponse])
async def list_categories(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Category)
        .where(Category.user_id == current_user.id)
        .order_by(Category.sort_order)
    )
    return [CategoryResponse.model_validate(c) for c in result.scalars().all()]


@router.post("/me/categories", response_model=CategoryResponse, status_code=201)
async def create_category(
    body: CategoryCreate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cat = Category(user_id=current_user.id, **body.model_dump())
    db.add(cat)
    await db.flush()
    await db.refresh(cat)
    return CategoryResponse.model_validate(cat)


@router.delete("/me/categories/{cat_id}", response_model=OKResponse)
async def delete_category(
    cat_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cat = await db.get(Category, cat_id)
    if not cat or cat.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Category not found")
    await db.delete(cat)
    return OKResponse(message=f"Category {cat_id} deleted")
