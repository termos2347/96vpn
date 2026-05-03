import logging
from pathlib import Path

from fastapi import FastAPI, staticfiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from web.routes import web, auth, payment, prompts
from config import settings
from db.base import init_sync_db

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация таблиц базы данных (синхронно)
try:
    init_sync_db()
    logger.info("Database tables initialized")
except Exception as e:
    logger.error(f"Database initialization error: {e}")

# Инициализация FastAPI приложения
app = FastAPI(
    title=settings.APP_NAME,
    description="Платформа для продажи AI-промптов по подписке",
    version="1.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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