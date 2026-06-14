"""
WealthWise database models.
All tables live here — import them all in database.py so Alembic can see them.
"""

import uuid
from datetime import datetime, date
from decimal import Decimal
from enum import Enum as PyEnum

from sqlalchemy import (
    String, Boolean, DateTime, Date, Numeric, Integer, Text,
    ForeignKey, Enum, UniqueConstraint, Index, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, selectin_polymorphic

from app.database import Base


# ── Enums ─────────────────────────────────────────────────────────────────────

class PlanTier(str, PyEnum):
    FREE = "free"
    PRO  = "pro"

class TransactionType(str, PyEnum):
    INCOME  = "income"
    EXPENSE = "expense"

class GoalStatus(str, PyEnum):
    ACTIVE    = "active"
    COMPLETED = "completed"
    PAUSED    = "paused"

class RecurringFrequency(str, PyEnum):
    DAILY   = "daily"
    WEEKLY  = "weekly"
    MONTHLY = "monthly"
    YEARLY  = "yearly"


# ── User ──────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    email: Mapped[str]    = mapped_column(String(255), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    timezone: Mapped[str] = mapped_column(String(50), default="America/New_York")
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Subscription
    plan: Mapped[PlanTier] = mapped_column(
        Enum(PlanTier), default=PlanTier.FREE, nullable=False
    )
    stripe_customer_id: Mapped[str | None]     = mapped_column(String(100), nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    plaid_access_token: Mapped[str | None] = mapped_column(String(500), nullable=True)
    plaid_institution: Mapped[str | None]  = mapped_column(String(255), nullable=True)
    pro_expires_at: Mapped[datetime | None]    = mapped_column(DateTime(timezone=True), nullable=True)

    # Flags
    is_active: Mapped[bool]    = mapped_column(Boolean, default=True)
    is_verified: Mapped[bool]  = mapped_column(Boolean, default=False)
    onboarding_done: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    budgets: Mapped[list["Budget"]]           = relationship(back_populates="user", cascade="all, delete-orphan")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    goals: Mapped[list["Goal"]]               = relationship(back_populates="user", cascade="all, delete-orphan")
    categories: Mapped[list["Category"]]      = relationship(back_populates="user", cascade="all, delete-orphan")
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(back_populates="user", cascade="all, delete-orphan")


# ── Refresh Token ─────────────────────────────────────────────────────────────

class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token: Mapped[str]   = mapped_column(String(500), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool]        = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")


# ── Category ──────────────────────────────────────────────────────────────────

class Category(Base):
    """
    User-customizable spending categories.
    Seeded with defaults on registration.
    """
    __tablename__ = "categories"

    id: Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str]    = mapped_column(String(100), nullable=False)
    icon: Mapped[str]    = mapped_column(String(50), default="ti-circle")
    color: Mapped[str]   = mapped_column(String(7), default="#185FA5")   # hex
    is_income: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_category_user_name"),
        Index("ix_category_user", "user_id"),
    )

    user: Mapped["User"]               = relationship(back_populates="categories")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="category")
    budget_items: Mapped[list["BudgetItem"]]  = relationship(back_populates="category")


# ── Budget ────────────────────────────────────────────────────────────────────

class Budget(Base):
    """One budget record per user per month."""
    __tablename__ = "budgets"

    id: Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    month: Mapped[int]   = mapped_column(Integer, nullable=False)   # 1–12
    year: Mapped[int]    = mapped_column(Integer, nullable=False)
    monthly_income: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    savings_goal: Mapped[Decimal]   = mapped_column(Numeric(12, 2), default=0)
    notes: Mapped[str | None]       = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime]    = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime]    = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "month", "year", name="uq_budget_user_month"),
        Index("ix_budget_user_year", "user_id", "year"),
    )

    user: Mapped["User"]              = relationship(back_populates="budgets")
    items: Mapped[list["BudgetItem"]] = relationship(back_populates="budget", cascade="all, delete-orphan")


class BudgetItem(Base):
    """Per-category budget allocation within a Budget."""
    __tablename__ = "budget_items"

    id: Mapped[int]         = mapped_column(Integer, primary_key=True, autoincrement=True)
    budget_id: Mapped[int]  = mapped_column(ForeignKey("budgets.id", ondelete="CASCADE"), nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"), nullable=False)
    allocated: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    budget: Mapped["Budget"]     = relationship(back_populates="items")
    category: Mapped["Category"] = relationship(back_populates="budget_items")


# ── Transaction ───────────────────────────────────────────────────────────────

class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int]          = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str]     = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)

    description: Mapped[str]  = mapped_column(String(255), nullable=False)
    amount: Mapped[Decimal]   = mapped_column(Numeric(12, 2), nullable=False)   # always positive
    type: Mapped[TransactionType] = mapped_column(Enum(TransactionType), nullable=False)
    transaction_date: Mapped[date]  = mapped_column(Date, nullable=False, index=True)
    notes: Mapped[str | None]       = mapped_column(Text, nullable=True)
    merchant: Mapped[str | None]    = mapped_column(String(255), nullable=True)

    # Recurring support
    is_recurring: Mapped[bool]                         = mapped_column(Boolean, default=False)
    recurring_frequency: Mapped[RecurringFrequency | None] = mapped_column(
        Enum(RecurringFrequency), nullable=True
    )

    # Bank sync (Plaid)
    plaid_transaction_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_txn_user_date", "user_id", "transaction_date"),
    )

    user: Mapped["User"]         = relationship(back_populates="transactions")
    category: Mapped["Category"] = relationship(back_populates="transactions")


# ── Goal ──────────────────────────────────────────────────────────────────────

class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    name: Mapped[str]             = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_amount: Mapped[Decimal]  = mapped_column(Numeric(12, 2), nullable=False)
    current_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[GoalStatus]       = mapped_column(Enum(GoalStatus), default=GoalStatus.ACTIVE)
    color: Mapped[str]               = mapped_column(String(7), default="#185FA5")
    icon: Mapped[str]                = mapped_column(String(50), default="ti-target")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship(back_populates="goals")
