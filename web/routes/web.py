import logging
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader
from pathlib import Path
from sqlalchemy.orm import Session

from db.base import get_db
from db.models import User
from config import settings
from web.services.auth import PromptService, SubscriptionService
from web.security import get_current_user_optional

logger = logging.getLogger(__name__)

# Jinja2
templates_dir = Path(__file__).parent.parent / "templates"
jinja_env = Environment(loader=FileSystemLoader(str(templates_dir)))

router = APIRouter(tags=["web"])

@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Главная страница / Лендинг"""
    template = jinja_env.get_template("index.html")
    return template.render(
        site_name=settings.APP_NAME,
        monthly_price=int(settings.MONTHLY_PRICE),
        quarterly_price=int(settings.QUARTERLY_PRICE)
    )

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Страница логина"""
    template = jinja_env.get_template("login.html")
    return template.render(site_name=settings.APP_NAME)

@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    """Страница регистрации"""
    template = jinja_env.get_template("register.html")
    return template.render(site_name=settings.APP_NAME)

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, current_user: User = Depends(get_current_user_optional)):
    """Личный кабинет"""
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
async def prompts_page(request: Request, current_user: User = Depends(get_current_user_optional)):
    """Страница со списком промптов – доступна всем (даже без логина/подписки)"""
    prompts = PromptService.get_all_prompts()
    categories = PromptService.get_categories()
    template = jinja_env.get_template("prompts.html")
    return template.render(
        site_name=settings.APP_NAME,
        prompts=prompts,
        categories=categories,
        user=current_user,
        is_active=current_user.is_active if current_user else False
    )

@router.get("/pay/{tg_id}", response_class=HTMLResponse)
async def payment_telegram(request: Request, tg_id: int, db: Session = Depends(get_db)):
    """Упрощённая страница оплаты для Telegram"""
    template = jinja_env.get_template("payment_telegram.html")
    return template.render(
        site_name=settings.APP_NAME,
        tg_id=tg_id,
        monthly_price=int(settings.MONTHLY_PRICE),
        quarterly_price=int(settings.QUARTERLY_PRICE),
        site_url=settings.SITE_URL
    )

@router.get("/legal/terms", response_class=HTMLResponse)
async def terms(request: Request):
    """Публичная оферта"""
    template = jinja_env.get_template("terms.html")
    return template.render(site_name=settings.APP_NAME)

@router.get("/legal/privacy", response_class=HTMLResponse)
async def privacy(request: Request):
    """Политика конфиденциальности"""
    template = jinja_env.get_template("privacy.html")
    return template.render(site_name=settings.APP_NAME)

@router.get("/prompt/{prompt_id}", response_class=HTMLResponse)
async def prompt_detail(
    request: Request,
    prompt_id: int,
    current_user: User = Depends(get_current_user_optional)):
    """Страница деталей промпта – полный текст только для активных подписчиков"""
    prompt = PromptService.get_prompt_by_id(prompt_id)
    if not prompt:
        return HTMLResponse("Prompt not found", status_code=404)
    
    # Если промпт бесплатный – показываем без проверки
    if prompt.get("is_free", False):
        template = jinja_env.get_template("prompt_detail.html")
        return template.render(
            site_name=settings.APP_NAME,
            prompt=prompt,
            user=current_user,
            is_free=True
        )
    
    # Если не бесплатный и пользователь не активен – показываем страницу с предложением подписаться
    if not current_user or not current_user.is_active:
        template = jinja_env.get_template("subscribe_required.html")
        return template.render(
            site_name=settings.APP_NAME,
            prompt_title=prompt["title"],
            user_id=current_user.id if current_user else None
        )
    
    # Активный подписчик – видит полное содержимое
    template = jinja_env.get_template("prompt_detail.html")
    return template.render(
        site_name=settings.APP_NAME,
        prompt=prompt,
        user=current_user,
        is_free=False
    )
    
@router.get("/payment-success", response_class=HTMLResponse)
async def payment_success(request: Request):
    """Страница успешной оплаты"""
    template = jinja_env.get_template("payment_success.html")
    return template.render(
        site_name=settings.APP_NAME
    )
    
@router.get("/payment-failed", response_class=HTMLResponse)
async def payment_failed(request: Request, user_id: int = None):
    template = jinja_env.get_template("payment_failed.html")
    return template.render(site_name=settings.APP_NAME, user_id=user_id)

@router.get("/pay-choice", response_class=HTMLResponse)
async def pay_choice(request: Request, user_id: int, db: Session = Depends(get_db)):
    """Страница выбора тарифа после регистрации"""
    from web.services.auth import AuthService
    user = await AuthService.get_user_by_id(db, user_id)
    if not user:
        return HTMLResponse("User not found", status_code=404)
    template = jinja_env.get_template("pay_choice.html")
    return template.render(
        site_name=settings.APP_NAME,
        user_id=user_id,
        monthly_price=int(settings.MONTHLY_PRICE),
        quarterly_price=int(settings.QUARTERLY_PRICE)
    )