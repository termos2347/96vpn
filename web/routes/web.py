import logging
import jwt
from datetime import datetime, timezone
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader
from pathlib import Path
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.base import get_async_db, AsyncSessionLocal
from db.models import WebUser
from config import settings
from web.services.auth import PromptService, SubscriptionService, AuthService
from web.security import get_current_user_optional

from aiogram import Bot, Dispatcher
from aiogram.types import Update
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
webhook_bot: Bot = None
webhook_admin_bot: Bot = None
webhook_admin_dp: Dispatcher = None
webhook_dp: Dispatcher = None

templates_dir = Path(__file__).parent.parent / "templates"
jinja_env = Environment(loader=FileSystemLoader(str(templates_dir)))

router = APIRouter(tags=["web"])

def _render_template(template_name: str, request: Request, **kwargs):
    current_user = getattr(request.state, "user", None)
    template = jinja_env.get_template(template_name)
    return template.render(site_name=settings.APP_NAME, user=current_user, **kwargs)

# ---------- VPN оплата (из бота) ----------
@router.get("/pay/subscription", response_class=HTMLResponse)
async def vpn_payment_page(request: Request, token: str):
    try:
        payload = jwt.decode(
            token,
            settings.INTERNAL_API_SECRET,
            algorithms=["HS256"],
            leeway=60
        )
        logger.info(f"Token decoded, exp: {payload.get('exp')}, now: {datetime.now(timezone.utc).timestamp()}")
    except jwt.ExpiredSignatureError:
        logger.warning("Token expired")
        return HTMLResponse("Ссылка истекла", status_code=410)
    except jwt.InvalidTokenError:
        logger.warning("Invalid token")
        return HTMLResponse("Недействительная ссылка", status_code=400)

    template = jinja_env.get_template("vpn_payment.html")
    return template.render(
        site_name=settings.APP_NAME,
        token=token,
        amount=payload["amount"],
        product=f"{payload['product_type']} ({payload['period']})",
        currency=payload["currency"],
        user=None
    )

# ---------- Страница успеха VPN ----------
@router.get("/payment/success", response_class=HTMLResponse)
async def vpn_success_page(request: Request, orderId: str = None, current_user: WebUser = Depends(get_current_user_optional)):
    template = jinja_env.get_template("vpn_success.html")
    return template.render(site_name=settings.APP_NAME, payment_id=orderId, user=current_user)

# ---------- Остальные маршруты ----------
@router.get("/", response_class=HTMLResponse)
async def index(request: Request, current_user: WebUser = Depends(get_current_user_optional)):
    request.state.user = current_user
    template = jinja_env.get_template("index.html")
    return template.render(
        site_name=settings.APP_NAME,
        user=current_user,
        monthly_price=int(settings.MONTHLY_PRICE),
        quarterly_price=int(settings.QUARTERLY_PRICE),
        semiannual_price=int(settings.SEMIANNUAL_PRICE)
    )

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, current_user: WebUser = Depends(get_current_user_optional)):
    template = jinja_env.get_template("login.html")
    return template.render(site_name=settings.APP_NAME, user=current_user)

@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, current_user: WebUser = Depends(get_current_user_optional)):
    template = jinja_env.get_template("register.html")
    return template.render(site_name=settings.APP_NAME, user=current_user)

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, current_user: WebUser = Depends(get_current_user_optional)):
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)
    days_remaining = SubscriptionService.get_days_remaining(current_user)
    template = jinja_env.get_template("dashboard.html")
    return template.render(
        site_name=settings.APP_NAME,
        user=current_user,
        is_active=current_user.is_active,
        expiry_date=current_user.expiry_date,
        days_remaining=days_remaining
    )

@router.get("/prompts", response_class=HTMLResponse)
async def prompts_page(request: Request, current_user: WebUser = Depends(get_current_user_optional)):
    data = await PromptService.get_prompts_data()
    template = jinja_env.get_template("prompts.html")
    return template.render(
        site_name=settings.APP_NAME,
        prompts=data["prompts"],
        categories=data["categories"],
        user=current_user,
        is_active=current_user.is_active if current_user else False
    )

@router.get("/pay-choice", response_class=HTMLResponse)
async def pay_choice(request: Request, db: AsyncSession = Depends(get_async_db),
                     current_user: WebUser = Depends(get_current_user_optional)):
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)
    template = jinja_env.get_template("pay_choice.html")
    return template.render(
        site_name=settings.APP_NAME,
        monthly_price=int(settings.MONTHLY_PRICE),
        quarterly_price=int(settings.QUARTERLY_PRICE),
        semiannual_price=int(settings.SEMIANNUAL_PRICE),
        user=current_user
    )

@router.get("/pay/{tg_id}", response_class=HTMLResponse)
async def payment_telegram(request: Request, tg_id: int, db: AsyncSession = Depends(get_async_db),
                           current_user: WebUser = Depends(get_current_user_optional)):
    template = jinja_env.get_template("payment_telegram.html")
    return template.render(
        site_name=settings.APP_NAME,
        tg_id=tg_id,
        monthly_price=int(settings.MONTHLY_PRICE),
        quarterly_price=int(settings.QUARTERLY_PRICE),
        site_url=settings.SITE_URL,
        user=current_user
    )

@router.get("/legal/terms", response_class=HTMLResponse)
async def terms(request: Request, current_user: WebUser = Depends(get_current_user_optional)):
    template = jinja_env.get_template("terms.html")
    return template.render(
        site_name=settings.APP_NAME,
        user=current_user,
        current_date=datetime.now(timezone.utc).strftime("%d.%m.%Y")
    )

@router.get("/legal/privacy", response_class=HTMLResponse)
async def privacy(request: Request, current_user: WebUser = Depends(get_current_user_optional)):
    template = jinja_env.get_template("privacy.html")
    return template.render(
        site_name=settings.APP_NAME,
        user=current_user,
        current_date=datetime.now(timezone.utc).strftime("%d.%m.%Y")
    )

@router.get("/prompt/{prompt_id}", response_class=HTMLResponse)
async def prompt_detail(
    request: Request,
    prompt_id: int,
    current_user: WebUser = Depends(get_current_user_optional)
):
    prompt = await PromptService.get_prompt_by_id(prompt_id)
    if not prompt:
        return HTMLResponse("Prompt not found", status_code=404)
    if prompt.get("is_free", False):
        template = jinja_env.get_template("prompt_detail.html")
        return template.render(
            site_name=settings.APP_NAME,
            prompt=prompt,
            user=current_user,
            is_free=True
        )
    if not current_user or not current_user.is_active:
        template = jinja_env.get_template("subscribe_required.html")
        return template.render(
            site_name=settings.APP_NAME,
            prompt_title=prompt["title"],
            user_id=current_user.id if current_user else None,
            user=current_user
        )
    template = jinja_env.get_template("prompt_detail.html")
    return template.render(
        site_name=settings.APP_NAME,
        prompt=prompt,
        user=current_user,
        is_free=False
    )

@router.get("/payment-success", response_class=HTMLResponse)
async def payment_success(request: Request, current_user: WebUser = Depends(get_current_user_optional)):
    template = jinja_env.get_template("payment_success.html")
    return template.render(site_name=settings.APP_NAME, user=current_user)

@router.get("/payment-failed", response_class=HTMLResponse)
async def payment_failed(request: Request, user_id: int = None, current_user: WebUser = Depends(get_current_user_optional)):
    template = jinja_env.get_template("payment_failed.html")
    return template.render(site_name=settings.APP_NAME, user_id=user_id, user=current_user)

@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request, current_user: WebUser = Depends(get_current_user_optional)):
    template = jinja_env.get_template("forgot_password.html")
    return template.render(site_name=settings.APP_NAME, user=current_user)

@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request, token: str, current_user: WebUser = Depends(get_current_user_optional)):
    template = jinja_env.get_template("reset_password.html")
    return template.render(site_name=settings.APP_NAME, token=token, user=current_user)

@router.post("/webhook")
async def telegram_webhook(request: Request):
    """Обработчик вебхука от Telegram"""
    global webhook_bot, webhook_dp
    if webhook_bot is None or webhook_dp is None:
        return JSONResponse(status_code=500, content={"error": "Bot not initialized"})
    
    # Проверка секрета
    if settings.WEBHOOK_SECRET:
        secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if secret != settings.WEBHOOK_SECRET:
            return JSONResponse(status_code=403, content={"error": "Invalid secret"})
    
    try:
        update_data = await request.json()
        update = Update(**update_data)
        await webhook_dp.feed_update(webhook_bot, update)
        return JSONResponse(content={"status": "ok"})
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
    
@router.post("/webhook/admin")
async def admin_telegram_webhook(request: Request):
    """Обработчик вебхука для админ-бота"""
    global webhook_admin_bot, webhook_admin_dp
    if webhook_admin_bot is None or webhook_admin_dp is None:
        return JSONResponse(status_code=500, content={"error": "Admin bot not initialized"})
    
    # Проверка секрета
    if settings.ADMIN_WEBHOOK_SECRET:
        secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if secret != settings.ADMIN_WEBHOOK_SECRET:
            return JSONResponse(status_code=403, content={"error": "Invalid secret"})
    
    try:
        update_data = await request.json()
        update = Update(**update_data)
        await webhook_admin_dp.feed_update(webhook_admin_bot, update)
        return JSONResponse(content={"status": "ok"})
    except Exception as e:
        logger.error(f"Admin webhook error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
    
@router.get("/health")
async def health():
    db_ok = True
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception as e:
        db_ok = False
        logger.error(f"Health check DB error: {e}")

    bot_status = "unknown"
    bot_info = None
    if webhook_bot:
        try:
            me = await webhook_bot.get_me()
            bot_status = "ok"
            bot_info = {"username": me.username}
        except Exception as e:
            bot_status = "error"
            bot_info = {"error": str(e)}
    else:
        bot_status = "not_initialized"

    return {
        "status": "ok" if (db_ok and bot_status == "ok") else "degraded",
        "database": "ok" if db_ok else "error",
        "bot": {"status": bot_status, "info": bot_info},
        "app": settings.APP_NAME,
    }