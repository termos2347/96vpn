import logging
from pathlib import Path
from contextlib import asynccontextmanager
import secrets

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

from web.routes import web, auth, payment, prompts
from config import settings
from db.base import init_db
from web.services.auth import PromptService
from web.rate_limit import limiter

import sentry_sdk

logger = logging.getLogger(__name__)

if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        traces_sample_rate=0.1,
        environment="production" if not settings.DEBUG else "development",
        release="1.0.0",
    )
    logger.info("Sentry initialized")


class CSRFMiddleware(BaseHTTPMiddleware):
    EXEMPT_PATHS = {
        "/webhook",
        "/webhook/admin",
        "/api/payment/webhook/yookassa",
        "/health",
        "/health/bot",
    }

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)

        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            # Получаем CSRF-токен из заголовка
            csrf_header = request.headers.get("X-CSRF-Token")
            # Пытаемся получить токен из тела запроса (form, json)
            csrf_form = None
            content_type = request.headers.get("content-type", "")

            if content_type.startswith("application/x-www-form-urlencoded"):
                form = await request.form()
                csrf_form = form.get("csrf_token")
            elif content_type.startswith("multipart/form-data"):
                form = await request.form()
                csrf_form = form.get("csrf_token")
            elif content_type == "application/json":
                body = await request.json()
                csrf_form = body.get("csrf_token")

            csrf_cookie = request.cookies.get("csrf_token")

            is_valid = False
            if csrf_header and csrf_cookie and csrf_header == csrf_cookie:
                is_valid = True
            elif csrf_form and csrf_cookie and csrf_form == csrf_cookie:
                is_valid = True

            if not is_valid:
                return JSONResponse(status_code=403, content={"detail": "CSRF token missing or invalid"})

        response = await call_next(request)
        if "csrf_token" not in request.cookies:
            token = secrets.token_urlsafe(32)
            response.set_cookie(
                key="csrf_token",
                value=token,
                secure=not settings.DEBUG,   # в production secure=True
                httponly=False,
                samesite="lax",
                max_age=3600
            )
        return response


class CacheControlStaticMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up...")
    try:
        await init_db()
        logger.info("Database tables initialized (async)")
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
    await PromptService.init_cache()
    yield
    logger.info("Shutting down...")


app = FastAPI(
    title=settings.APP_NAME,
    description="Платформа для продажи AI-промптов по подписке",
    version="1.0.0",
    lifespan=lifespan
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.SITE_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(CSRFMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=500, compresslevel=6)

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

app.add_middleware(CacheControlStaticMiddleware)

app.include_router(web.router)
app.include_router(auth.router)
app.include_router(payment.router)
app.include_router(prompts.router)


@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.APP_NAME}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
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