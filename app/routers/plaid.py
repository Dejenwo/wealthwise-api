"""
Plaid Bank Sync — WealthWise
Endpoints: create link token, exchange token, sync transactions
"""

import os
from datetime import datetime, timedelta, date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from plaid.api import plaid_api
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.transactions_get_request import TransactionsGetRequest
from plaid.model.transactions_get_request_options import TransactionsGetRequestOptions
from plaid.model.country_code import CountryCode
from plaid.model.products import Products
import plaid

from app.database import get_db
from app.models import User, Transaction, TransactionType
from app.security import get_current_user

router = APIRouter()

# ── Plaid client setup ────────────────────────────────────────────────────────

PLAID_ENV = os.getenv("PLAID_ENV", "sandbox")
PLAID_CLIENT_ID = os.getenv("PLAID_CLIENT_ID", "")
PLAID_SECRET = os.getenv("PLAID_SECRET", "")

env_map = {
    "sandbox":     plaid.Environment.Sandbox,
    "development": plaid.Environment.Development,
    "production":  plaid.Environment.Production,
}

configuration = plaid.Configuration(
    host=env_map.get(PLAID_ENV, plaid.Environment.Sandbox),
    api_key={"clientId": PLAID_CLIENT_ID, "secret": PLAID_SECRET},
)
api_client = plaid.ApiClient(configuration)
client = plaid_api.PlaidApi(api_client)


# ── Schemas ───────────────────────────────────────────────────────────────────

class ExchangeTokenRequest(BaseModel):
    public_token: str
    institution_name: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/create-link-token")
async def create_link_token(current_user=Depends(get_current_user)):
    """Step 1 — Create a Plaid Link token to open the bank connection popup."""
    try:
        request = LinkTokenCreateRequest(
            products=[Products("transactions")],
            client_name="WealthWise",
            country_codes=[CountryCode("US")],
            language="en",
            user=LinkTokenCreateRequestUser(client_user_id=current_user.id),
        )
        response = client.link_token_create(request)
        return {"link_token": response["link_token"]}
    except plaid.ApiException as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/exchange-token")
async def exchange_token(
    body: ExchangeTokenRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Step 2 — Exchange public token for access token and save it."""
    try:
        exchange_request = ItemPublicTokenExchangeRequest(public_token=body.public_token)
        exchange_response = client.item_public_token_exchange(exchange_request)
        access_token = exchange_response["access_token"]

        # Save access token to user record
        current_user.plaid_access_token = access_token
        current_user.plaid_institution = body.institution_name
        await db.flush()

        return {
            "message": "Bank account connected successfully",
            "institution": body.institution_name
        }
    except plaid.ApiException as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/sync-transactions")
async def sync_transactions(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Step 3 — Pull last 30 days of transactions from the bank."""
    if not hasattr(current_user, 'plaid_access_token') or not current_user.plaid_access_token:
        raise HTTPException(status_code=400, detail="No bank account connected.")

    try:
        start_date = (datetime.now() - timedelta(days=30)).date()
        end_date = datetime.now().date()

        request = TransactionsGetRequest(
            access_token=current_user.plaid_access_token,
            start_date=start_date,
            end_date=end_date,
            options=TransactionsGetRequestOptions(count=100),
        )
        response = client.transactions_get(request)
        transactions = response["transactions"]

        imported = 0
        skipped = 0

        for txn in transactions:
            # Skip pending transactions
            if txn.get("pending"):
                skipped += 1
                continue

            plaid_id = txn["transaction_id"]

            # Check if already imported
            existing = await db.execute(
                select(Transaction).where(
                    Transaction.plaid_transaction_id == plaid_id
                )
            )
            if existing.scalar_one_or_none():
                skipped += 1
                continue

            # Plaid amounts: positive = money out, negative = money in
            amount = abs(Decimal(str(txn["amount"])))
            txn_type = TransactionType.EXPENSE if txn["amount"] > 0 else TransactionType.INCOME

            new_txn = Transaction(
                user_id=current_user.id,
                description=txn.get("name", "Bank transaction"),
                amount=amount,
                type=txn_type,
                transaction_date=txn["date"],
                merchant=txn.get("merchant_name"),
                plaid_transaction_id=plaid_id,
            )
            db.add(new_txn)
            imported += 1

        await db.flush()

        return {
            "message": f"Sync complete",
            "imported": imported,
            "skipped": skipped,
            "total_from_bank": len(transactions),
        }

    except plaid.ApiException as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/status")
async def plaid_status(current_user=Depends(get_current_user)):
    """Check if user has a connected bank account."""
    has_token = hasattr(current_user, 'plaid_access_token') and bool(current_user.plaid_access_token)
    return {
        "connected": has_token,
        "institution": getattr(current_user, 'plaid_institution', None),
    }