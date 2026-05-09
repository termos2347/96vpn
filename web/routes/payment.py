import logging
import jwt
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from web.schemas.schemas import PaymentResponse, SubscriptionInfo
from web.services.payment import yookassa_service
from web.services.auth import SubscriptionService, AuthService
from web.security import get_current_user_optional
from config import settings
from db.base import AsyncSession, get_async_db, get_db,  AsyncSessionLocal
from db.models import WebUser

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/payment", tags=["payment"])

# ---------- Инициация VPN-оплаты из бота ----------
@router.post("/initiate-vpn")
async def initiate_vpn_payment(token: str = Query(...), db: AsyncSession = Depends(get_async_db)):
    try:
        payload = jwt.decode(
            token,
            settings.INTERNAL_API_SECRET,
            algorithms=["HS256"],
            leeway=60
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=400, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=400, detail="Invalid token")

    payment = await yookassa_service.create_payment(
        user_id=None,
        amount=payload["amount"],
        plan=f"{payload['product_type']}_{payload['period']}_{payload['currency']}",
        db=db,
        description=f"VPN подписка ({payload['period']})",
        metadata={
            "source": "bot",
            "token": token,
            "telegram_id": payload["telegram_id"],
            "product_type": payload["product_type"],
            "period": payload["period"],
            "currency": payload["currency"]
        }
    )

    if not payment:
        raise HTTPException(status_code=500, detail="Failed to create payment")

    confirmation_url = payment["confirmation_url"]
    if "?" in confirmation_url:
        confirmation_url += f"&payment_id={payment['payment_id']}"
    else:
        confirmation_url += f"?payment_id={payment['payment_id']}"

    response = JSONResponse(content={"confirmation_url": confirmation_url})
    response.set_cookie(
        key="vpn_payment_id",
        value=payment["payment_id"],
        max_age=3600,
        path="/"
    )
    return response

# ---------- Проверка и активация после возврата ----------
@router.get("/check-payment")
async def check_vpn_payment(payment_id: str, db: AsyncSession = Depends(get_async_db)):
    success = await yookassa_service.check_and_activate(payment_id, db)
    return {"activated": success}

# ---------- Прямая оплата (веб-пользователи) ----------
@router.post("/create")
async def create_payment(
    plan: str = Query(...),
    db: AsyncSession = Depends(get_async_db),
    current_user: WebUser = Depends(get_current_user_optional)
):
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")

    if plan == "monthly":
        amount = settings.MONTHLY_PRICE
    elif plan == "quarterly":
        amount = settings.QUARTERLY_PRICE
    elif plan == "semiannual":
        amount = settings.SEMIANNUAL_PRICE
    else:
        raise HTTPException(status_code=400, detail="Invalid plan")

    payment = await yookassa_service.create_payment(
        user_id=current_user.id,
        amount=amount,
        plan=plan,
        db=db
    )
    if not payment:
        raise HTTPException(status_code=500, detail="Failed to create payment")

    # Устанавливаем куку с payment_id для страницы успеха
    response = JSONResponse(content={
        "payment_id": payment["payment_id"],
        "status": payment["status"],
        "confirmation_url": payment["confirmation_url"],
        "created_at": str(payment["created_at"])  # преобразуем в строку
    })
    response.set_cookie(
        key="vpn_payment_id",
        value=payment["payment_id"],
        max_age=3600,
        path="/"
    )
    return response

@router.get("/status/{payment_id}")
async def get_payment_status(payment_id: str):
    status = await yookassa_service.get_payment_status(payment_id)
    if not status:
        raise HTTPException(status_code=404, detail="Payment not found")
    return {"payment_id": payment_id, "status": status}

@router.post("/webhook/yookassa")
async def yookassa_webhook(request: Request, db: AsyncSession = Depends(get_async_db)):
    try:
        webhook_data = await request.json()
        success = await yookassa_service.process_webhook(webhook_data, db)
        if success:
            return {"status": "ok"}
        else:
            return {"status": "error"}
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        return {"status": "error"}

@router.get("/subscription-info", response_model=SubscriptionInfo)
async def get_subscription_info(current_user: WebUser = Depends(get_current_user_optional)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    days_remaining = SubscriptionService.get_days_remaining(current_user)
    return {
        "is_active": current_user.is_active,
        "days_remaining": days_remaining,
        "expiry_date": current_user.expiry_date
    }