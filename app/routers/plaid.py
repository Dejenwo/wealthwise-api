"""
Plaid Bank Sync — WealthWise
Compatible with plaid-python 20.0.1
"""

import os
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

import plaid
from plaid.api import plaid_api
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.transactions_get_request import TransactionsGetRequest
from plaid.model.transactions_get_request_options import TransactionsGetRequestOptions
from plaid.model.country_code import CountryCode
from plaid.model.products import Products

from app.database import get_db
from app.models import User, Transaction, TransactionType
from app.security import get_current_user

router = APIRouter()

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
    api_key={
        "clientId": PLAID_CLIENT_ID,
        "secret":   PLAID_SECRET,
    },
)
api_client = plaid.ApiClient(configuration)
client = plaid_api.PlaidApi(api_client)


class ExchangeTokenRequest(BaseModel):
    public_token: str
    institution_name: str


@router.post("/create-link-token")
async def create_link_token(current_user=Depends(get_current_user)):
    try:
        request = LinkTokenCreateRequest(
            products=[Products("transactions")],
            client_name="WealthWise",
            country_codes=[CountryCode("US")],
            language="en",
            user=LinkTokenCreateRequestUser(
                client_user_id=current_user.id
            ),
        )
        response = client.link_token_create(request)
        return {"link_token": response["link_token"]}
    except plaid.ApiException as e:
        raise HTTPException(status_code=400, detail=str(e.body))


@router.post("/exchange-token")
async def exchange_token(
    body: ExchangeTokenRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        exchange_request = ItemPublicTokenExchangeRequest(
            public_token=body.public_token
        )
        exchange_response = client.item_public_token_exchange(exchange_request)
        access_token = exchange_response["access_token"]

        current_user.plaid_access_token = access_token
        current_user.plaid_institution  = body.institution_name
        await db.flush()

        return {
            "message": "Bank account connected successfully",
            "institution": body.institution_name,
        }
    except plaid.ApiException as e:
        raise HTTPException(status_code=400, detail=str(e.body))


@router.post("/sync-transactions")
async def sync_transactions(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    access_token = getattr(current_user, "plaid_access_token", None)
    if not access_token:
        raise HTTPException(status_code=400, detail="No bank account connected.")

    try:
        start_date = (datetime.now() - timedelta(days=30)).date()
        end_date   = datetime.now().date()

        request = TransactionsGetRequest(
            access_token=access_token,
            start_date=start_date,
            end_date=end_date,
            options=TransactionsGetRequestOptions(count=100),
        )
        response     = client.transactions_get(request)
        transactions = response["transactions"]

        imported = 0
        skipped  = 0

        for txn in transactions:
            if txn.get("pending"):
                skipped += 1
                continue

            plaid_id = txn["transaction_id"]
            existing = await db.execute(
                select(Transaction).where(
                    Transaction.plaid_transaction_id == plaid_id
                )
            )
            if existing.scalar_one_or_none():
                skipped += 1
                continue

            amount   = abs(Decimal(str(txn["amount"])))
            txn_type = TransactionType.EXPENSE if txn["amount"] > 0 else TransactionType.INCOME

            db.add(Transaction(
                user_id=current_user.id,
                description=txn.get("name", "Bank transaction"),
                amount=amount,
                type=txn_type,
                transaction_date=txn["date"],
                merchant=txn.get("merchant_name"),
                plaid_transaction_id=plaid_id,
            ))
            imported += 1

        await db.flush()

        return {
            "message":        "Sync complete",
            "imported":       imported,
            "skipped":        skipped,
            "total_from_bank": len(transactions),
        }

    except plaid.ApiException as e:
        raise HTTPException(status_code=400, detail=str(e.body))


@router.get("/status")
async def plaid_status(current_user=Depends(get_current_user)):
    has_token = bool(getattr(current_user, "plaid_access_token", None))
    return {
        "connected":   has_token,
        "institution": getattr(current_user, "plaid_institution", None),
    }