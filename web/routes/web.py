import logging
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader
from pathlib import Path
from sqlalchemy.orm import Session
from db.base import get_db
from sqlalchemy import select
from db.models import User
from config import settings
from web.services.auth import PromptService, SubscriptionService
from datetime import datetime

logger = logging.getLogger(__name__)

# Инициализируем Jinja2
templates_dir = Path(__file__).parent.parent / "templates"
jinja_env = Environment(loader=FileSystemLoader(str(templates_dir)))

router = APIRouter(tags=["web"])

def get_current_user(request: Request, db: Session = Depends(get_db)) -> dict:
    """Получить текущего пользователя из сессии"""
    # Здесь можно добавить реальную логику сессий/JWT
    user_id = request.cookies.get("user_id")
    if not user_id:
        return None
    
    try:
        stmt = select(User).where(User.id == int(user_id))
        user = db.execute(stmt).scalars().first()
        return user
    except:
        return None

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
async def dashboard(request: Request, current_user: dict = Depends(get_current_user)):
    """Личный кабинет"""
    if not current_user:
        return HTMLResponse("Unauthorized", status_code=401)
    
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
async def prompts_page(request: Request, current_user: dict = Depends(get_current_user)):
    """Страница с промптами"""
    if not current_user or not current_user.is_active:
        return HTMLResponse("Access Denied: Active subscription required", status_code=403)
    
    prompts = PromptService.get_all_prompts()
    template = jinja_env.get_template("prompts.html")
    return template.render(
        site_name=settings.APP_NAME,
        prompts=prompts,
        user=current_user
    )

@router.get("/pay/{tg_id}", response_class=HTMLResponse)
async def payment_telegram(request: Request, tg_id: int, db: Session = Depends(get_db)):
    """Упрощённая страница оплаты для Telegram"""
    from config import settings
    
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
    current_user: dict = Depends(get_current_user)
):
    """Страница с деталями промпта"""
    if not current_user or not current_user.is_active:
        return HTMLResponse("Access Denied: Active subscription required", status_code=403)
    
    prompt = PromptService.get_prompt_by_id(prompt_id)
    if not prompt:
        return HTMLResponse("Prompt not found", status_code=404)
    
    template = jinja_env.get_template("prompt_detail.html")
    return template.render(
        site_name=settings.APP_NAME,
        prompt=prompt,
        user=current_user
    )
