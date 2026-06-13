import os
import stripe
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models import User, PlanTier
from app.security import get_current_user

router = APIRouter()
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
PRO_PRICE_ID   = os.getenv("STRIPE_PRO_PRICE_ID", "")
FRONTEND_URL   = os.getenv("FRONTEND_URL", "http://localhost:3000")

@router.post("/create-checkout-session")
async def create_checkout_session(current_user=Depends(get_current_user), db: AsyncSession=Depends(get_db)):
    if current_user.plan == PlanTier.PRO:
        raise HTTPException(status_code=400, detail="Already on Pro plan.")
    if not current_user.stripe_customer_id:
        customer = stripe.Customer.create(email=current_user.email, name=current_user.full_name, metadata={"user_id": current_user.id})
        current_user.stripe_customer_id = customer.id
        await db.flush()
    session = stripe.checkout.Session.create(
        customer=current_user.stripe_customer_id,
        payment_method_types=["card"],
        line_items=[{"price": PRO_PRICE_ID, "quantity": 1}],
        mode="subscription",
        success_url=f"{FRONTEND_URL}/upgrade/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{FRONTEND_URL}/upgrade/cancelled",
        subscription_data={"trial_period_days": 14, "metadata": {"user_id": current_user.id}},
        metadata={"user_id": current_user.id},
    )
    return {"checkout_url": session.url, "session_id": session.id}

@router.post("/billing-portal")
async def billing_portal(current_user=Depends(get_current_user)):
    if not current_user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No billing account found.")
    session = stripe.billing_portal.Session.create(customer=current_user.stripe_customer_id, return_url=f"{FRONTEND_URL}/settings")
    return {"portal_url": session.url}

@router.get("/subscription-status")
async def subscription_status(current_user=Depends(get_current_user)):
    result = {"plan": current_user.plan.value, "is_pro": current_user.plan == PlanTier.PRO, "stripe_customer_id": current_user.stripe_customer_id, "pro_expires_at": current_user.pro_expires_at}
    if current_user.stripe_subscription_id:
        try:
            sub = stripe.Subscription.retrieve(current_user.stripe_subscription_id)
            result["subscription_status"] = sub.status
            result["current_period_end"] = datetime.fromtimestamp(sub.current_period_end, tz=timezone.utc).isoformat()
            result["cancel_at_period_end"] = sub.cancel_at_period_end
        except stripe.StripeError:
            pass
    return result

@router.post("/webhook")
async def stripe_webhook(request: Request, stripe_signature: str=Header(None), db: AsyncSession=Depends(get_db)):
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(payload, stripe_signature, WEBHOOK_SECRET)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    event_type = event["type"]
    data = event["data"]["object"]
    if event_type == "checkout.session.completed":
        user_id = data.get("metadata", {}).get("user_id")
        sub_id = data.get("subscription")
        if user_id:
            await _upgrade_user(user_id, sub_id, db)
    elif event_type == "customer.subscription.updated":
        user_id = data.get("metadata", {}).get("user_id")
        status = data.get("status")
        if user_id:
            if status in ("active", "trialing"):
                await _upgrade_user(user_id, data["id"], db)
            elif status in ("past_due", "unpaid", "canceled"):
                await _downgrade_user(user_id, db)
    elif event_type == "customer.subscription.deleted":
        customer_id = data.get("customer")
        if customer_id:
            result = await db.execute(select(User).where(User.stripe_customer_id == customer_id))
            user = result.scalar_one_or_none()
            if user:
                await _downgrade_user(user.id, db)
    elif event_type == "invoice.payment_succeeded":
        customer_id = data.get("customer")
        sub_id = data.get("subscription")
        if customer_id:
            result = await db.execute(select(User).where(User.stripe_customer_id == customer_id))
            user = result.scalar_one_or_none()
            if user and sub_id:
                await _upgrade_user(user.id, sub_id, db)
    return JSONResponse(content={"received": True})

async def _upgrade_user(user_id: str, subscription_id: str, db: AsyncSession):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user:
        user.plan = PlanTier.PRO
        user.stripe_subscription_id = subscription_id
        await db.flush()

async def _downgrade_user(user_id: str, db: AsyncSession):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user:
        user.plan = PlanTier.FREE
        user.stripe_subscription_id = None
        await db.flush()
