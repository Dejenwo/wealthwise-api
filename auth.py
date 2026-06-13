"""
Auth endpoints: register, login, refresh token, logout, password reset.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import User, RefreshToken, Category
from app.schemas import (
    RegisterRequest, LoginRequest, TokenResponse,
    RefreshRequest, OKResponse
)
from app.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token,
    decode_token, get_current_user,
    REFRESH_EXPIRE
)

router = APIRouter()

# Default categories seeded for every new user
DEFAULT_CATEGORIES = [
    {"name": "Rent / Mortgage", "icon": "ti-home-2",           "color": "#185FA5"},
    {"name": "Groceries",        "icon": "ti-shopping-cart",    "color": "#3B6D11"},
    {"name": "Transport",        "icon": "ti-car",              "color": "#5F5E5A"},
    {"name": "Utilities",        "icon": "ti-bolt",             "color": "#854F0B"},
    {"name": "Dining Out",       "icon": "ti-tool-kitchen-2",   "color": "#A32D2D"},
    {"name": "Entertainment",    "icon": "ti-device-tv",        "color": "#533AB7"},
    {"name": "Healthcare",       "icon": "ti-heart-rate-monitor","color": "#0F6E56"},
    {"name": "Clothing",         "icon": "ti-shirt",            "color": "#993556"},
    {"name": "Subscriptions",    "icon": "ti-refresh",          "color": "#5F5E5A"},
    {"name": "Miscellaneous",    "icon": "ti-dots-circle-horizontal", "color": "#6B4226"},
    {"name": "Salary",           "icon": "ti-building-bank",    "color": "#3B6D11", "is_income": True},
    {"name": "Freelance",        "icon": "ti-briefcase",        "color": "#185FA5", "is_income": True},
    {"name": "Investments",      "icon": "ti-trending-up",      "color": "#533AB7", "is_income": True},
]


async def _seed_categories(user_id: str, db: AsyncSession):
    """Create default categories for a new user."""
    for i, cat in enumerate(DEFAULT_CATEGORIES):
        db.add(Category(
            user_id=user_id,
            name=cat["name"],
            icon=cat["icon"],
            color=cat["color"],
            is_income=cat.get("is_income", False),
            sort_order=i,
        ))
    await db.flush()


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(
    body: RegisterRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    # Check duplicate email
    existing = await db.execute(select(User).where(User.email == body.email.lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email=body.email.lower(),
        full_name=body.full_name,
        hashed_password=hash_password(body.password),
        currency=body.currency.upper(),
    )
    db.add(user)
    await db.flush()   # get user.id before seeding

    await _seed_categories(user.id, db)

    access  = create_access_token({"sub": user.id})
    refresh = create_refresh_token({"sub": user.id})

    db.add(RefreshToken(
        user_id=user.id,
        token=refresh,
        expires_at=datetime.now(timezone.utc) + timedelta(days=REFRESH_EXPIRE),
    ))

    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        user_id=user.id,
        plan=user.plan.value,
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email.lower()))
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    access  = create_access_token({"sub": user.id})
    refresh = create_refresh_token({"sub": user.id})

    db.add(RefreshToken(
        user_id=user.id,
        token=refresh,
        expires_at=datetime.now(timezone.utc) + timedelta(days=REFRESH_EXPIRE),
    ))

    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        user_id=user.id,
        plan=user.plan.value,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    payload = decode_token(body.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")

    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token == body.refresh_token,
            RefreshToken.revoked == False,
        )
    )
    stored = result.scalar_one_or_none()
    if not stored or stored.expires_at.replace(tzinfo=None) < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Refresh token expired or revoked")

    # Rotate: revoke old, issue new
    stored.revoked = True

    user_result = await db.execute(select(User).where(User.id == stored.user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    new_access  = create_access_token({"sub": user.id})
    new_refresh = create_refresh_token({"sub": user.id})

    db.add(RefreshToken(
        user_id=user.id,
        token=new_refresh,
        expires_at=datetime.now(timezone.utc) + timedelta(days=REFRESH_EXPIRE),
    ))

    return TokenResponse(
        access_token=new_access,
        refresh_token=new_refresh,
        user_id=user.id,
        plan=user.plan.value,
    )


@router.post("/logout", response_model=OKResponse)
async def logout(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token == body.refresh_token)
    )
    token = result.scalar_one_or_none()
    if token:
        token.revoked = True
    return OKResponse(message="Logged out successfully")


@router.get("/me", response_model=dict)
async def me(current_user=Depends(get_current_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "plan": current_user.plan.value,
        "currency": current_user.currency,
    }
