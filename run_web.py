#!/usr/bin/env python3
"""
Запуск FastAPI приложения NeuroPrompt Premium
"""
import logging
import sys
import os
from pathlib import Path

# Добавляем корневую папку в путь
root = Path(__file__).parent.parent
sys.path.insert(0, str(root))

from web.app import app
import uvicorn

def main():
    """Запуск приложения"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    logger = logging.getLogger(__name__)
    logger.info("Starting NeuroPrompt Premium web application...")
    
    # Инициализируем БД
    from db.base import init_db
    import asyncio
    asyncio.run(init_db())
    
    # Запускаем сервер
    uvicorn.run(
        "web.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )

if __name__ == "__main__":
    main()
