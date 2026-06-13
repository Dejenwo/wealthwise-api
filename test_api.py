"""
WealthWise API test suite.
Run: pytest tests/ -v
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.main import app
from app.database import Base, get_db

# ── In-memory SQLite for tests ─────────────────────────────────────────────────
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DB_URL)
TestSession  = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


async def override_get_db():
    async with TestSession() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


app.dependency_overrides[get_db] = override_get_db


@pytest_asyncio.fixture(autouse=True, scope="function")
async def setup_db():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# ── Helpers ───────────────────────────────────────────────────────────────────

async def register_and_login(client: AsyncClient) -> dict:
    await client.post("/api/v1/auth/register", json={
        "email": "test@wealthwise.app",
        "full_name": "Test User",
        "password": "Secure123",
        "currency": "USD",
    })
    resp = await client.post("/api/v1/auth/login", json={
        "email": "test@wealthwise.app",
        "password": "Secure123",
    })
    return resp.json()


# ── Auth Tests ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_success(client):
    resp = await client.post("/api/v1/auth/register", json={
        "email": "new@example.com",
        "full_name": "New User",
        "password": "Password1",
        "currency": "USD",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert "access_token" in data
    assert data["plan"] == "free"


@pytest.mark.asyncio
async def test_register_duplicate_email(client):
    payload = {"email": "dup@example.com", "full_name": "XX", "password": "Password1", "currency": "USD"}
    await client.post("/api/v1/auth/register", json=payload)
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    await client.post("/api/v1/auth/register", json={
        "email": "u@example.com", "full_name": "U", "password": "Password1", "currency": "USD"
    })
    resp = await client.post("/api/v1/auth/login", json={"email": "u@example.com", "password": "wrong"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token(client):
    tokens = await register_and_login(client)
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


# ── Transaction Tests ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_and_list_transactions(client):
    tokens = await register_and_login(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    resp = await client.post("/api/v1/transactions", headers=headers, json={
        "description": "Whole Foods",
        "amount": "94.50",
        "type": "expense",
        "transaction_date": "2025-10-15",
    })
    assert resp.status_code == 201
    txn = resp.json()
    assert txn["description"] == "Whole Foods"
    assert float(txn["amount"]) == 94.50

    list_resp = await client.get("/api/v1/transactions", headers=headers)
    assert list_resp.status_code == 200
    assert list_resp.json()["total"] == 1


@pytest.mark.asyncio
async def test_update_transaction(client):
    tokens = await register_and_login(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    create = await client.post("/api/v1/transactions", headers=headers, json={
        "description": "Amazon", "amount": "50.00", "type": "expense",
        "transaction_date": "2025-10-10",
    })
    txn_id = create.json()["id"]

    update = await client.patch(f"/api/v1/transactions/{txn_id}", headers=headers, json={
        "description": "Amazon Prime", "amount": "14.99"
    })
    assert update.status_code == 200
    assert update.json()["description"] == "Amazon Prime"


@pytest.mark.asyncio
async def test_delete_transaction(client):
    tokens = await register_and_login(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    create = await client.post("/api/v1/transactions", headers=headers, json={
        "description": "Coffee", "amount": "5.00", "type": "expense",
        "transaction_date": "2025-10-01",
    })
    txn_id = create.json()["id"]

    del_resp = await client.delete(f"/api/v1/transactions/{txn_id}", headers=headers)
    assert del_resp.status_code == 200

    list_resp = await client.get("/api/v1/transactions", headers=headers)
    assert list_resp.json()["total"] == 0


# ── Budget Tests ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_and_get_budget(client):
    tokens = await register_and_login(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    resp = await client.post("/api/v1/budgets", headers=headers, json={
        "month": 10, "year": 2025,
        "monthly_income": "4500.00",
        "savings_goal": "700.00",
        "items": [],
    })
    assert resp.status_code == 201
    assert resp.json()["month"] == 10


# ── Goal Tests ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_goal_contribution(client):
    tokens = await register_and_login(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    create = await client.post("/api/v1/goals", headers=headers, json={
        "name": "Emergency Fund",
        "target_amount": "10000.00",
        "current_amount": "0.00",
    })
    goal_id = create.json()["id"]

    contrib = await client.post(f"/api/v1/goals/{goal_id}/contribute", headers=headers, json={
        "amount": "500.00"
    })
    assert contrib.status_code == 200
    assert float(contrib.json()["current_amount"]) == 500.0
    assert contrib.json()["percent_complete"] == 5.0


@pytest.mark.asyncio
async def test_goal_auto_completes(client):
    tokens = await register_and_login(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    create = await client.post("/api/v1/goals", headers=headers, json={
        "name": "Small Goal", "target_amount": "100.00", "current_amount": "0.00"
    })
    goal_id = create.json()["id"]

    contrib = await client.post(f"/api/v1/goals/{goal_id}/contribute", headers=headers, json={"amount": "100.00"})
    assert contrib.json()["status"] == "completed"


# ── Pro Gate Tests ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reports_blocked_for_free_users(client):
    tokens = await register_and_login(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    resp = await client.get("/api/v1/reports/annual/2025", headers=headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_unauthenticated_request_rejected(client):
    resp = await client.get("/api/v1/transactions")
    assert resp.status_code in (401, 403)
