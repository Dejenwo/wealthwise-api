from __future__ import annotations
from datetime import datetime, date
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, EmailStr, Field, field_validator

class OKResponse(BaseModel):
    message: str = "ok"

class RegisterRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    currency: str = Field(default="USD", max_length=3)

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: str
    plan: str

class RefreshRequest(BaseModel):
    refresh_token: str

class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    currency: str
    timezone: str
    plan: str
    is_verified: bool
    onboarding_done: bool
    created_at: datetime
    model_config = {"from_attributes": True}

class UpdateUserRequest(BaseModel):
    full_name: Optional[str] = None
    currency: Optional[str] = None
    timezone: Optional[str] = None

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class CategoryCreate(BaseModel):
    name: str
    icon: str = "ti-circle"
    color: str = "#185FA5"
    is_income: bool = False
    sort_order: int = 0

class CategoryResponse(BaseModel):
    id: int
    name: str
    icon: str
    color: str
    is_income: bool
    sort_order: int
    model_config = {"from_attributes": True}

class BudgetItemCreate(BaseModel):
    category_id: int
    allocated: Decimal

class BudgetItemResponse(BaseModel):
    id: int
    category_id: int
    category: CategoryResponse
    allocated: Decimal
    spent: Decimal = Decimal("0")
    remaining: Decimal = Decimal("0")
    percent_used: float = 0.0
    model_config = {"from_attributes": True}

class BudgetCreate(BaseModel):
    month: int = Field(ge=1, le=12)
    year: int = Field(ge=2020, le=2100)
    monthly_income: Decimal
    savings_goal: Decimal
    notes: Optional[str] = None
    items: list[BudgetItemCreate] = []

class BudgetResponse(BaseModel):
    id: int
    month: int
    year: int
    monthly_income: Decimal
    savings_goal: Decimal
    notes: Optional[str] = None
    total_allocated: Decimal = Decimal("0")
    total_spent: Decimal = Decimal("0")
    total_remaining: Decimal = Decimal("0")
    items: list[BudgetItemResponse] = []
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}

class TransactionCreate(BaseModel):
    description: str
    amount: Decimal
    type: str
    category_id: Optional[int] = None
    transaction_date: date
    notes: Optional[str] = None
    merchant: Optional[str] = None
    is_recurring: bool = False
    recurring_frequency: Optional[str] = None

class TransactionUpdate(BaseModel):
    description: Optional[str] = None
    amount: Optional[Decimal] = None
    category_id: Optional[int] = None
    transaction_date: Optional[date] = None
    notes: Optional[str] = None
    merchant: Optional[str] = None
    is_recurring: Optional[bool] = None

class TransactionResponse(BaseModel):
    id: int
    description: str
    amount: Decimal
    type: str
    category_id: Optional[int] = None
    category: Optional[CategoryResponse] = None
    transaction_date: date
    notes: Optional[str] = None
    merchant: Optional[str] = None
    is_recurring: bool
    recurring_frequency: Optional[str] = None
    created_at: datetime
    model_config = {"from_attributes": True}

class TransactionListResponse(BaseModel):
    items: list[TransactionResponse]
    total: int
    page: int
    page_size: int
    total_pages: int

class GoalCreate(BaseModel):
    name: str
    description: Optional[str] = None
    target_amount: Decimal
    current_amount: Decimal = Decimal("0")
    target_date: Optional[date] = None
    color: str = "#185FA5"
    icon: str = "ti-target"

class GoalUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    target_amount: Optional[Decimal] = None
    current_amount: Optional[Decimal] = None
    target_date: Optional[date] = None
    status: Optional[str] = None
    color: Optional[str] = None

class GoalContribution(BaseModel):
    amount: Decimal
    notes: Optional[str] = None

class GoalResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    target_amount: Decimal
    current_amount: Decimal
    target_date: Optional[date] = None
    status: str
    color: str
    icon: str
    percent_complete: float = 0.0
    monthly_needed: Optional[Decimal] = None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}

class AIInsightRequest(BaseModel):
    question: Optional[str] = None

class AIInsightResponse(BaseModel):
    insight: str
    tokens_used: int
    cached: bool = False
class MonthlySummary(BaseModel):
    month: int
    year: int
    total_income: Decimal
    total_expenses: Decimal
    net: Decimal
    savings_rate: float
    top_category: Optional[str] = None
    top_category_amount: Optional[Decimal] = None

class CategoryBreakdown(BaseModel):
    category_id: int
    category_name: str
    color: str
    total: Decimal
    transaction_count: int
    percent_of_total: float

class AnnualReport(BaseModel):
    year: int
    monthly_summaries: list[MonthlySummary]
    total_income: Decimal
    total_expenses: Decimal
    total_net: Decimal
    average_monthly_spend: Decimal
    category_breakdown: list[CategoryBreakdown]