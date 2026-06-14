"""
AI Advisor — Claude-powered financial insights.
Pro-gated. Builds context from the user's real data, then calls Claude.
"""

import os
import json
import hashlib
from decimal import Decimal
from datetime import date, datetime

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.database import get_db
from app.models import Transaction, Budget, Goal, Category, TransactionType
from app.schemas import AIInsightRequest, AIInsightResponse
from app.security import require_pro

router = APIRouter()

# Simple in-process cache: hash(user_id + context) → response
_cache: dict[str, str] = {}

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")


async def _build_financial_context(user_id: str, db: AsyncSession) -> dict:
    """Pull real user data to inject into the Claude prompt."""
    today = date.today()
    m, y  = today.month, today.year

    # Monthly income & expenses
    inc_q = await db.execute(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.user_id == user_id,
            Transaction.type    == TransactionType.INCOME,
            func.extract("month", Transaction.transaction_date) == m,
            func.extract("year",  Transaction.transaction_date) == y,
        )
    )
    exp_q = await db.execute(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.user_id == user_id,
            Transaction.type    == TransactionType.EXPENSE,
            func.extract("month", Transaction.transaction_date) == m,
            func.extract("year",  Transaction.transaction_date) == y,
        )
    )
    income   = float(inc_q.scalar_one())
    expenses = float(exp_q.scalar_one())

    # Category breakdown this month
    cat_q = await db.execute(
        select(Category.name, func.sum(Transaction.amount).label("total"))
        .join(Transaction, Transaction.category_id == Category.id)
        .where(
            Transaction.user_id == user_id,
            Transaction.type    == TransactionType.EXPENSE,
            func.extract("month", Transaction.transaction_date) == m,
            func.extract("year",  Transaction.transaction_date) == y,
        )
        .group_by(Category.name)
        .order_by(func.sum(Transaction.amount).desc())
    )
    categories = [{"name": r[0], "spent": float(r[1])} for r in cat_q.all()]

    # Active goals
    goal_q = await db.execute(
        select(Goal).where(Goal.user_id == user_id, Goal.status == "active")
    )
    goals = [
        {
            "name": g.name,
            "target": float(g.target_amount),
            "saved": float(g.current_amount),
            "pct": round(float(g.current_amount / g.target_amount * 100), 1) if g.target_amount else 0,
        }
        for g in goal_q.scalars().all()
    ]

    return {
        "month": today.strftime("%B %Y"),
        "income": income,
        "expenses": expenses,
        "net": income - expenses,
        "savings_rate": round((income - expenses) / income * 100, 1) if income else 0,
        "top_categories": categories[:6],
        "goals": goals,
    }


def _build_system_prompt() -> str:
    return """You are WealthWise AI, a friendly and expert personal finance advisor.
You have access to the user's real spending data for the current month.
Your job is to give concise, specific, actionable financial advice.

Rules:
- Always cite specific dollar amounts from the user's data.
- Be encouraging but honest about overspending.
- Suggest concrete next steps, not generic tips.
- Keep responses under 250 words unless asked to elaborate.
- Format with short paragraphs or a numbered list — no markdown headers.
- Never give tax or legal advice; recommend a professional for those."""


def _build_user_prompt(ctx: dict, question: str | None) -> str:
    cats_text = "\n".join(
        f"  - {c['name']}: ${c['spent']:,.0f}" for c in ctx["top_categories"]
    )
    goals_text = "\n".join(
        f"  - {g['name']}: {g['pct']}% complete (${g['saved']:,.0f} / ${g['target']:,.0f})"
        for g in ctx["goals"]
    ) or "  None set yet."

    context_block = f"""
Here is my financial snapshot for {ctx['month']}:

Income:    ${ctx['income']:,.0f}
Expenses:  ${ctx['expenses']:,.0f}
Net:       ${ctx['net']:+,.0f}
Savings rate: {ctx['savings_rate']}%

Top spending categories:
{cats_text}

Savings goals:
{goals_text}
"""
    if question:
        return context_block + f"\nMy question: {question}"
    else:
        return context_block + "\nPlease give me 3 personalized, actionable insights to improve my finances this month."


@router.post("/insight", response_model=AIInsightResponse)
async def get_ai_insight(
    body: AIInsightRequest,
    current_user=Depends(require_pro),
    db: AsyncSession = Depends(get_db),
):
    if not ANTHROPIC_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="AI advisor is not configured. Set ANTHROPIC_API_KEY."
        )

    ctx = await _build_financial_context(current_user.id, db)

    # Cache key: hash of user context + question
    cache_key = hashlib.md5(
        json.dumps({**ctx, "q": body.question}, sort_keys=True).encode()
    ).hexdigest()

    if cache_key in _cache:
        return AIInsightResponse(insight=_cache[cache_key], tokens_used=0, cached=True)

    client  = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        system=_build_system_prompt(),
        messages=[{"role": "user", "content": _build_user_prompt(ctx, body.question)}],
    )

    insight = message.content[0].text
    _cache[cache_key] = insight   # cache for this server session

    return AIInsightResponse(
        insight=insight,
        tokens_used=message.usage.input_tokens + message.usage.output_tokens,
        cached=False,
    )


@router.post("/chat", response_model=AIInsightResponse)
async def ai_chat(
    body: AIInsightRequest,
    current_user=Depends(require_pro),
    db: AsyncSession = Depends(get_db),
):
    """Freeform question to the AI advisor, grounded in the user's data."""
    if not body.question or not body.question.strip():
        raise HTTPException(status_code=422, detail="question is required for /chat")
    return await get_ai_insight(body, current_user, db)
