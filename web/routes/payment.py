import logging
import jwt
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
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

def verify_yookassa_signature(request: Request, body: bytes) -> bool:
    """Проверяет подпись вебхука от ЮKassa."""
    import hashlib
    import hmac
    signature = request.headers.get("X-Yookassa-Signature", "")
    if not signature or not settings.YOOKASSA_API_KEY:
        logger.warning("Missing signature or API key, skipping verification")
        return False
    expected = hmac.new(
        settings.YOOKASSA_API_KEY.encode("utf-8"),
        body,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature, expected)

# ---------- Новый эндпоинт для VPN-оплаты из бота ----------
@router.post("/initiate-vpn")
async def initiate_vpn_payment(token: str = Query(...), db: Session = Depends(get_db)):
    """Создаёт платёж в ЮKassa для покупки, инициированной из бота."""
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

    # Сохраняем payment_id в куки, чтобы страница успеха могла его получить
    response = JSONResponse(content={"confirmation_url": payment["confirmation_url"]})
    response.set_cookie(
        key="vpn_payment_id",
        value=payment["payment_id"],
        max_age=3600,    # 1 час
        httponly=True,
        path="/"
    )
    return response

# ---------- Эндпоинт проверки и активации (для страницы успеха) ----------
@router.get("/check-vpn-payment")
async def check_vpn_payment(payment_id: str, db: Session = Depends(get_db)):
    """Проверяет статус платежа и активирует подписку (для страницы успеха)."""
    success = await yookassa_service.check_and_activate(payment_id, db)
    return {"activated": success}

# ---------- Существующие маршруты (без изменений) ----------
@router.post("/create")
async def create_payment(
    user_id: int,
    plan: str = Query(..., description="monthly или quarterly"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_optional)
):
    if not current_user or current_user.id != user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
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
    status = await yookassa_service.get_payment_status(payment_id)
    if not status:
        raise HTTPException(status_code=404, detail="Payment not found")
    return {"payment_id": payment_id, "status": status}

@router.post("/webhook/yookassa")
async def yookassa_webhook(request: Request, db: Session = Depends(get_db)):
    """Webhook от Yookassa с проверкой подписи."""
    body = await request.body()
    if not verify_yookassa_signature(request, body):
        if settings.DEBUG:
            logger.warning("Invalid webhook signature, but DEBUG mode allows ignoring")
        else:
            logger.warning("Invalid webhook signature, rejecting")
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

# Для отладки – временный эндпоинт
if settings.DEBUG:
    @router.post("/test-activate/{user_id}")
    async def test_activate_subscription(user_id: int, db: Session = Depends(get_db)):
        user = await AuthService.get_user_by_id(db, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        await SubscriptionService.renew_subscription(db, user, days=30)
        return {"status": "activated", "expiry_date": user.expiry_date}