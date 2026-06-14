"""
WealthWise API — Personal Finance Tracker
FastAPI backend with JWT auth, PostgreSQL, and full CRUD for all features.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

from app.database import engine, Base
from app.routers import auth, users, budgets, transactions, goals, reports, ai_advisor, stripe as stripe_router
from app.middleware.rate_limit import RateLimitMiddleware
from app.routers import plaid as plaid_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all tables on startup (use Alembic in production)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(
    title="WealthWise API",
    description="Smart personal finance tracker with AI-powered insights",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "https://wealthwise.app",
        "https://www.wealthwise.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Rate limiting ─────────────────────────────────────────────────────────────
app.add_middleware(RateLimitMiddleware, requests_per_minute=60)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth.router,         prefix="/api/v1/auth",         tags=["Auth"])
app.include_router(users.router,        prefix="/api/v1/users",        tags=["Users"])
app.include_router(budgets.router,      prefix="/api/v1/budgets",      tags=["Budgets"])
app.include_router(transactions.router, prefix="/api/v1/transactions", tags=["Transactions"])
app.include_router(goals.router,        prefix="/api/v1/goals",        tags=["Goals"])
app.include_router(reports.router,      prefix="/api/v1/reports",      tags=["Reports"])
app.include_router(ai_advisor.router,   prefix="/api/v1/ai",           tags=["AI Advisor"])
app.include_router(stripe_router.router, prefix="/api/v1/stripe",      tags=["Stripe"])
app.include_router(plaid_router.router, prefix="/api/v1/plaid", tags=["Plaid"])

@app.get("/", tags=["Health"])
async def root():
    return {"status": "ok", "service": "WealthWise API", "version": "1.0.0"}


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "healthy"}
