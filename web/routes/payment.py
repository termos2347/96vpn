import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from web.schemas.schemas import PaymentResponse, SubscriptionInfo
from web.services.payment import yookassa_service
from web.services.auth import SubscriptionService
from web.config import settings
from db.base import get_db
from sqlalchemy import select
from db.models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/payment", tags=["payment"])

@router.post("/create/{user_id}")
async def create_payment(
    user_id: int,
    plan: str = Query(..., description="monthly или quarterly"),
    db: Session = Depends(get_db)
):
    """Создание платежа"""
    if plan not in ["monthly", "quarterly"]:
        raise HTTPException(status_code=400, detail="Invalid plan")
    
    amount = settings.MONTHLY_PRICE if plan == "monthly" else settings.QUARTERLY_PRICE
    
    payment = await yookassa_service.create_payment(
        user_id=user_id,
        amount=amount,
        plan=plan,
        db=db
    )
    
    if not payment:
        raise HTTPException(status_code=500, detail="Failed to create payment")
    
    return PaymentResponse(**payment)

@router.get("/status/{payment_id}")
async def get_payment_status(payment_id: str):
    """Получить статус платежа"""
    status = await yookassa_service.get_payment_status(payment_id)
    if not status:
        raise HTTPException(status_code=404, detail="Payment not found")
    return {"payment_id": payment_id, "status": status}

@router.post("/webhook/yookassa")
async def yookassa_webhook(request: Request, db: Session = Depends(get_db)):
    """Webhook от Yookassa"""
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

@router.get("/subscription-info/{user_id}", response_model=SubscriptionInfo)
async def get_subscription_info(user_id: int, db: Session = Depends(get_db)):
    """Получить информацию о подписке"""
    stmt = select(User).where(User.id == user_id)
    user = db.execute(stmt).scalars().first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    days_remaining = SubscriptionService.get_days_remaining(user)
    
    return {
        "is_active": user.is_active,
        "days_remaining": days_remaining,
        "expiry_date": user.expiry_date
    }

@router.post("/activate/{user_id}/{telegram_id}")
async def activate_telegram_payment(
    user_id: int,
    telegram_id: int,
    plan: str = Query("monthly"),
    db: Session = Depends(get_db)
):
    """
    Активировать платёж для Telegram пользователя.
    Используется для платежей, инициированных из Telegram-бота.
    """
    # Ищем или создаём пользователя по telegram_id
    stmt = select(User).where(User.user_id == telegram_id)
    user = db.execute(stmt).scalars().first()
    
    if not user:
        user = User(
            user_id=telegram_id,
            source="bot",
            is_active=False,
            created_at=__import__('datetime').datetime.utcnow()
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    
    # Создаём платёж
    amount = settings.MONTHLY_PRICE if plan == "monthly" else settings.QUARTERLY_PRICE
    
    payment = await yookassa_service.create_payment(
        user_id=user.id,
        amount=amount,
        plan=plan,
        db=db,
        description=f"Подписка для Telegram: {telegram_id}"
    )
    
    if not payment:
        raise HTTPException(status_code=500, detail="Failed to create payment")
    
    return PaymentResponse(**payment)
