import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

from web.routes import web, auth, payment, prompts
from config import settings
from db.base import init_db
from web.services.auth import PromptService
from web.rate_limit import limiter  # наш отдельный модуль с лимитером

import sentry_sdk
from config import settings

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        traces_sample_rate=0.1,          # 10% запросов для performance мониторинга
        environment="production" if not settings.DEBUG else "development",
        release="1.0.0",                 # можно указать версию из git или другую
    )
    logger.info("Sentry initialized")
    
# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения."""
    # Startup
    logger.info("Starting up...")
    try:
        await init_db()
        logger.info("Database tables initialized (async)")
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
    # Предзагрузка кэша промптов
    await PromptService.init_cache()
    yield
    # Shutdown
    logger.info("Shutting down...")
    # Здесь можно закрыть глобальные ресурсы, например aiohttp сессию, если добавите


# Инициализация FastAPI приложения с lifespan
app = FastAPI(
    title=settings.APP_NAME,
    description="Платформа для продажи AI-промптов по подписке",
    version="1.0.0",
    lifespan=lifespan
)

# Подключение лимитера к приложению
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — разрешён только ваш домен
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.SITE_URL],  # конкретный домен из настроек
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Статические файлы
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Подключаем маршруты
app.include_router(web.router)
app.include_router(auth.router)
app.include_router(payment.router)
app.include_router(prompts.router)


@app.get("/health")
async def health():
    """Health check"""
    return {"status": "ok", "app": settings.APP_NAME}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Favicon"""
    favicon_path = Path(__file__).parent / "static" / "favicon.ico"
    if favicon_path.exists():
        return FileResponse(favicon_path)
    return {"status": "not found"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "web.app:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG
    )