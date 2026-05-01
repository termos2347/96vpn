from datetime import datetime
import logging
import hashlib
import hmac
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from web.schemas.schemas import PaymentResponse, SubscriptionInfo
from web.services.payment import yookassa_service
from web.services.auth import SubscriptionService, AuthService
from web.security import get_current_user_optional
from config import settings
from db.base import get_db
from db.models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/payment", tags=["payment"])

@router.post("/create")
async def create_payment(
    user_id: int,
    plan: str = Query(..., description="monthly или quarterly"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_optional)
):
    """Создание платежа (требует авторизации, user_id должен совпадать с current_user.id)"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    if current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Cannot create payment for another user")
    
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
    """Получить статус платежа (публичный)"""
    status = await yookassa_service.get_payment_status(payment_id)
    if not status:
        raise HTTPException(status_code=404, detail="Payment not found")
    return {"payment_id": payment_id, "status": status}

@router.post("/webhook/yookassa")
async def yookassa_webhook(request: Request, db: Session = Depends(get_db)):
    """Webhook от Yookassa с проверкой подписи"""
    # Получаем тело запроса
    body = await request.body()
    # Проверяем подпись (если настроено)
    signature = request.headers.get("HTTP_X_YOOKASSA_SIGNATURE", "")
    if settings.YOOKASSA_API_KEY:
        expected = hmac.new(
            settings.YOOKASSA_API_KEY.encode(),
            body,
            hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            logger.warning("Invalid webhook signature")
        return {"status": "invalid signature"}
    
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
async def get_subscription_info(current_user: User = Depends(get_current_user_optional)):
    """Получить информацию о своей подписке"""
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    days_remaining = SubscriptionService.get_days_remaining(current_user)
    return {
        "is_active": current_user.is_active,
        "days_remaining": days_remaining,
        "expiry_date": current_user.expiry_date
    }

@router.post("/activate-telegram/{telegram_id}")
async def activate_telegram_payment(
    telegram_id: int,
    plan: str = Query("monthly"),
    db: Session = Depends(get_db)
):
    """
    Активировать платёж для Telegram пользователя.
    Инициирует платёж и возвращает ссылку на оплату.
    """
    # Ищем или создаём пользователя по telegram_id
    user = await AuthService.get_user_by_telegram(db, telegram_id)
    if not user:
        user = User(
            user_id=telegram_id,
            source="bot",
            is_active=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    
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