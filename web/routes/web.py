import logging
import jwt
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from aiogram import Bot, Dispatcher
from aiogram.types import Update

from config import settings
from db.base import get_async_db, AsyncSessionLocal
from db.models import WebUser
from web.services.auth import PromptService, SubscriptionService
from web.security import get_current_user_optional

logger = logging.getLogger(__name__)

# ---------- Jinja2 окружение ----------
templates_dir = Path(__file__).parent.parent / "templates"
jinja_env = Environment(loader=FileSystemLoader(str(templates_dir)))
jinja_env.globals['admin_email'] = settings.ADMIN_EMAIL

# ---------- Глобальные переменные для вебхуков (устанавливаются из run_all.py) ----------
webhook_bot: Bot = None
webhook_admin_bot: Bot = None
webhook_admin_dp: Dispatcher = None
webhook_dp: Dispatcher = None

router = APIRouter(tags=["web"])

# ---------- Вспомогательная функция рендеринга ----------
def render_template(request: Request, template_name: str, **context) -> HTMLResponse:
    """
    Рендерит HTML-шаблон через Jinja2, автоматически добавляя csrf_token в контекст.
    """
    csrf_token = request.cookies.get("csrf_token", "")
    template = jinja_env.get_template(template_name)
    context["request"] = request
    context["csrf_token"] = csrf_token
    return HTMLResponse(content=template.render(**context))

# ---------- VPN оплата (из бота) ----------
@router.get("/pay/subscription", response_class=HTMLResponse)
async def vpn_payment_page(request: Request, token: str):
    try:
        payload = jwt.decode(token, settings.INTERNAL_API_SECRET, algorithms=["HS256"], leeway=60)
    except jwt.ExpiredSignatureError:
        return HTMLResponse("Ссылка истекла", status_code=410)
    except jwt.InvalidTokenError:
        return HTMLResponse("Недействительная ссылка", status_code=400)

    return render_template(
        request,
        "vpn_payment.html",
        site_name=settings.APP_NAME,
        token=token,
        amount=payload["amount"],
        product=f"{payload['product_type']} ({payload['period']})",
        currency=payload["currency"],
        user=None
    )

@router.get("/payment/success", response_class=HTMLResponse)
async def vpn_success_page(
    request: Request,
    orderId: str = None,
    current_user: WebUser = Depends(get_current_user_optional)
):
    return render_template(
        request,
        "vpn_success.html",
        site_name=settings.APP_NAME,
        payment_id=orderId,
        user=current_user
    )

# ---------- Основные страницы ----------
@router.get("/", response_class=HTMLResponse)
async def index(request: Request, current_user: WebUser = Depends(get_current_user_optional)):
    request.state.user = current_user
    return render_template(
        request,
        "index.html",
        site_name=settings.APP_NAME,
        user=current_user,
        monthly_price=int(settings.MONTHLY_PRICE),
        quarterly_price=int(settings.QUARTERLY_PRICE),
        semiannual_price=int(settings.SEMIANNUAL_PRICE)
    )

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, current_user: WebUser = Depends(get_current_user_optional)):
    return render_template(request, "login.html", site_name=settings.APP_NAME, user=current_user)

@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, current_user: WebUser = Depends(get_current_user_optional)):
    return render_template(request, "register.html", site_name=settings.APP_NAME, user=current_user)

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, current_user: WebUser = Depends(get_current_user_optional)):
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)
    days_remaining = SubscriptionService.get_days_remaining(current_user)
    return render_template(
        request,
        "dashboard.html",
        site_name=settings.APP_NAME,
        user=current_user,
        is_active=current_user.is_active,
        expiry_date=current_user.expiry_date,
        days_remaining=days_remaining
    )

@router.get("/prompts", response_class=HTMLResponse)
async def prompts_page(request: Request, current_user: WebUser = Depends(get_current_user_optional)):
    data = await PromptService.get_prompts_data()
    return render_template(
        request,
        "prompts.html",
        site_name=settings.APP_NAME,
        prompts=data["prompts"],
        categories=data["categories"],
        user=current_user,
        is_active=current_user.is_active if current_user else False
    )

@router.get("/pay-choice", response_class=HTMLResponse)
async def pay_choice(request: Request, current_user: WebUser = Depends(get_current_user_optional)):
    if not current_user:
        return RedirectResponse(url="/login", status_code=302)
    return render_template(
        request,
        "pay_choice.html",
        site_name=settings.APP_NAME,
        monthly_price=int(settings.MONTHLY_PRICE),
        quarterly_price=int(settings.QUARTERLY_PRICE),
        semiannual_price=int(settings.SEMIANNUAL_PRICE),
        user=current_user
    )

@router.get("/pay/{tg_id}", response_class=HTMLResponse)
async def payment_telegram(request: Request, tg_id: int, current_user: WebUser = Depends(get_current_user_optional)):
    return render_template(
        request,
        "payment_telegram.html",
        site_name=settings.APP_NAME,
        tg_id=tg_id,
        monthly_price=int(settings.MONTHLY_PRICE),
        quarterly_price=int(settings.QUARTERLY_PRICE),
        site_url=settings.SITE_URL,
        user=current_user
    )

@router.get("/legal/terms", response_class=HTMLResponse)
async def terms(request: Request, current_user: WebUser = Depends(get_current_user_optional)):
    return render_template(
        request,
        "terms.html",
        site_name=settings.APP_NAME,
        site_url=settings.SITE_URL,
        user=current_user,
        current_date=datetime.now(timezone.utc).strftime("%d.%m.%Y")
    )

@router.get("/legal/privacy", response_class=HTMLResponse)
async def privacy(request: Request, current_user: WebUser = Depends(get_current_user_optional)):
    return render_template(
        request,
        "privacy.html",
        site_name=settings.APP_NAME,
        user=current_user,
        current_date=datetime.now(timezone.utc).strftime("%d.%m.%Y")
    )

@router.get("/prompt/{prompt_id}", response_class=HTMLResponse)
async def prompt_detail(request: Request, prompt_id: int, current_user: WebUser = Depends(get_current_user_optional)):
    prompt = await PromptService.get_prompt_by_id(prompt_id)
    if not prompt:
        return HTMLResponse("Prompt not found", status_code=404)
    if prompt.get("is_free", False):
        return render_template(
            request,
            "prompt_detail.html",
            site_name=settings.APP_NAME,
            prompt=prompt,
            user=current_user,
            is_free=True
        )
    if not current_user or not current_user.is_active:
        return render_template(
            request,
            "subscribe_required.html",
            site_name=settings.APP_NAME,
            prompt_title=prompt["title"],
            user_id=current_user.id if current_user else None,
            user=current_user
        )
    return render_template(
        request,
        "prompt_detail.html",
        site_name=settings.APP_NAME,
        prompt=prompt,
        user=current_user,
        is_free=False
    )

@router.get("/payment-success", response_class=HTMLResponse)
async def payment_success(request: Request, current_user: WebUser = Depends(get_current_user_optional)):
    return render_template(request, "payment_success.html", site_name=settings.APP_NAME, user=current_user)

@router.get("/payment-failed", response_class=HTMLResponse)
async def payment_failed(request: Request, user_id: int = None, current_user: WebUser = Depends(get_current_user_optional)):
    return render_template(request, "payment_failed.html", site_name=settings.APP_NAME, user_id=user_id, user=current_user)

@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request, current_user: WebUser = Depends(get_current_user_optional)):
    return render_template(request, "forgot_password.html", site_name=settings.APP_NAME, user=current_user)

@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request, token: str, current_user: WebUser = Depends(get_current_user_optional)):
    return render_template(request, "reset_password.html", site_name=settings.APP_NAME, token=token, user=current_user)

# ---------- Health checks ----------
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

@router.get("/health/bot")
async def bot_health():
    if not webhook_bot:
        return {"status": "error", "detail": "Bot not initialized"}
    try:
        me = await webhook_bot.get_me()
        return {
            "status": "ok",
            "bot_username": me.username,
            "is_bot": me.is_bot,
            "webhook": webhook_bot.session is not None
        }
    except Exception as e:
        logger.error(f"Health check bot error: {e}")
        return {"status": "error", "detail": str(e)}

# ---------- Webhooks для Telegram ----------
@router.post("/webhook")
async def telegram_webhook(request: Request):
    global webhook_bot, webhook_dp
    if webhook_bot is None or webhook_dp is None:
        return JSONResponse(status_code=500, content={"error": "Bot not initialized"})

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
    global webhook_admin_bot, webhook_admin_dp
    if webhook_admin_bot is None or webhook_admin_dp is None:
        return JSONResponse(status_code=500, content={"error": "Admin bot not initialized"})

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