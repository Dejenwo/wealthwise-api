# WealthWise API

**Personal Finance Tracker — FastAPI Backend**
Production-ready REST API with JWT auth, PostgreSQL, freemium monetization, and Claude AI advisor.

---

## Quick Start (Local Dev — 60 seconds)

```bash
# 1. Clone and install
git clone https://github.com/yourname/wealthwise-api
cd wealthwise-api
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env — at minimum set SECRET_KEY and ANTHROPIC_API_KEY

# 3. Run (SQLite auto-created, no Postgres needed locally)
uvicorn app.main:app --reload

# 4. Open interactive API docs
open http://localhost:8000/docs
```

---

## Project Structure

```
wealthwise/
├── app/
│   ├── main.py             # FastAPI app, CORS, middleware, router registration
│   ├── database.py         # Async SQLAlchemy engine + session dependency
│   ├── security.py         # JWT, bcrypt, get_current_user, require_pro
│   ├── models/
│   │   └── __init__.py     # All SQLAlchemy ORM models
│   ├── schemas/
│   │   └── __init__.py     # All Pydantic v2 request/response schemas
│   ├── routers/
│   │   ├── auth.py         # Register, login, refresh, logout
│   │   ├── users.py        # Profile + custom categories
│   │   ├── budgets.py      # Monthly budget CRUD + live spend totals
│   │   ├── transactions.py # Full CRUD, pagination, search, filter
│   │   ├── goals.py        # Savings goals + contribution tracking
│   │   ├── reports.py      # Annual reports + trends (Pro)
│   │   └── ai_advisor.py   # Claude-powered insights (Pro)
│   └── middleware/
│       └── rate_limit.py   # 60 req/min per IP
├── tests/
│   └── test_api.py         # Full pytest suite (14 tests)
├── requirements.txt
├── Dockerfile
└── .env.example
```

---

## API Reference

### Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/auth/register` | Create account, returns JWT pair |
| POST | `/api/v1/auth/login` | Login, returns JWT pair |
| POST | `/api/v1/auth/refresh` | Rotate refresh token |
| POST | `/api/v1/auth/logout` | Revoke refresh token |
| GET  | `/api/v1/auth/me` | Current user summary |

### Users & Categories

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET    | `/api/v1/users/me` | Full profile |
| PATCH  | `/api/v1/users/me` | Update profile |
| POST   | `/api/v1/users/me/change-password` | Change password |
| DELETE | `/api/v1/users/me` | Deactivate account |
| GET    | `/api/v1/users/me/categories` | List spending categories |
| POST   | `/api/v1/users/me/categories` | Create custom category |
| DELETE | `/api/v1/users/me/categories/{id}` | Delete category |

### Budgets

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET    | `/api/v1/budgets` | List all budgets |
| GET    | `/api/v1/budgets/current` | This month's budget with live spend |
| POST   | `/api/v1/budgets` | Create monthly budget |
| GET    | `/api/v1/budgets/{id}` | Budget detail |
| PATCH  | `/api/v1/budgets/{id}` | Update budget |
| DELETE | `/api/v1/budgets/{id}` | Delete budget |

### Transactions

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET    | `/api/v1/transactions` | Paginated list with filters |
| POST   | `/api/v1/transactions` | Add transaction |
| GET    | `/api/v1/transactions/{id}` | Single transaction |
| PATCH  | `/api/v1/transactions/{id}` | Update transaction |
| DELETE | `/api/v1/transactions/{id}` | Delete transaction |
| GET    | `/api/v1/transactions/summary/monthly` | Month income vs expense |

**Query params for GET /transactions:**
- `page`, `page_size` — pagination
- `category_id`, `type` (income/expense) — filter
- `search` — full-text on description + merchant
- `date_from`, `date_to` — date range

### Goals

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET    | `/api/v1/goals` | List goals |
| POST   | `/api/v1/goals` | Create goal |
| PATCH  | `/api/v1/goals/{id}` | Update goal |
| POST   | `/api/v1/goals/{id}/contribute` | Add money to goal |
| DELETE | `/api/v1/goals/{id}` | Delete goal |

### Reports (Pro)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET    | `/api/v1/reports/annual/{year}` | Full year breakdown + category totals |
| GET    | `/api/v1/reports/spending-trend` | Last N months trend data |

### AI Advisor (Pro)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST   | `/api/v1/ai/insight` | Auto-generate 3 personalized insights |
| POST   | `/api/v1/ai/chat` | Ask any finance question |

**Request body:**
```json
{ "question": "How can I cut my dining spending by $200 next month?" }
```

---

## Authentication Flow

```
1. POST /register  →  { access_token, refresh_token }
2. Use access_token in header: Authorization: Bearer <token>
3. Access token expires in 30 min
4. POST /refresh with refresh_token  →  new token pair (rotated)
5. POST /logout to revoke refresh token
```

---

## Freemium / Pro Gating

Free tier: all CRUD (budgets, transactions, goals, categories)
Pro tier: reports, AI advisor, spending trend, forecasting

**To upgrade a user to Pro** (until Stripe is wired up, do this manually):
```sql
UPDATE users SET plan = 'pro', pro_expires_at = NOW() + INTERVAL '1 month'
WHERE email = 'user@example.com';
```

After Stripe integration (Step 2), the webhook handler sets this automatically.

---

## Deployment

### Render (recommended for MVP)

1. Create a new Web Service pointing to this repo
2. Set build command: `pip install -r requirements.txt`
3. Set start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. Add environment variables from `.env.example`
5. Add a PostgreSQL database — copy the connection string to `DATABASE_URL`

### Railway / Heroku

Same steps — just add a Postgres plugin and set `DATABASE_URL`.

### Docker

```bash
docker build -t wealthwise-api .
docker run -p 8000:8000 --env-file .env wealthwise-api
```

---

## Running Tests

```bash
pytest tests/ -v
# Expected: 14 passed
```

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SECRET_KEY` | Yes | JWT signing key (openssl rand -hex 32) |
| `DATABASE_URL` | Yes | SQLite (dev) or PostgreSQL (prod) |
| `ANTHROPIC_API_KEY` | For AI | Your Claude API key |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | Default 30 |
| `REFRESH_TOKEN_EXPIRE_DAYS` | No | Default 30 |
| `STRIPE_SECRET_KEY` | Step 2 | Stripe backend key |
| `STRIPE_WEBHOOK_SECRET` | Step 2 | Stripe webhook signing secret |
| `STRIPE_PRO_PRICE_ID` | Step 2 | Your Pro plan price ID |

---

## Next Steps

- **Step 2:** Stripe subscription integration (webhook handler to auto-upgrade users)
- **Step 3:** Plaid bank sync (import real transactions automatically)
- **Step 4:** Email notifications (SendGrid) for budget alerts
- **Step 5:** React frontend deployment + API integration

---

## Revenue Math

| Users | MRR | ARR |
|-------|-----|-----|
| 100 Pro | $900 | $10,800 |
| 500 Pro | $4,500 | $54,000 |
| 1,000 Pro | $9,000 | $108,000 |
| 5,000 Pro | $45,000 | $540,000 |

At $540K ARR with 30%+ margins, WealthWise is in acquisition territory for fintech players.
