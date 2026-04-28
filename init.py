#!/usr/bin/env python3
"""
Скрипт инициализации NeuroPrompt Premium
Устанавливает зависимости и инициализирует БД
"""
import subprocess
import sys
import os
from pathlib import Path

def run_command(cmd, description):
    """Выполнить команду с описанием"""
    print(f"\n{'='*60}")
    print(f"📦 {description}")
    print(f"{'='*60}")
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        print(f"❌ Ошибка при выполнении: {description}")
        return False
    print(f"✅ {description} завершено")
    return True

def main():
    root = Path(__file__).parent
    
    print("""
╔════════════════════════════════════════════════════════════════╗
║         NeuroPrompt Premium - Инициализация проекта            ║
╚════════════════════════════════════════════════════════════════╝
    """)
    
    # 1. Проверка Python
    print(f"🐍 Python версия: {sys.version}")
    if sys.version_info < (3, 9):
        print("❌ Требуется Python 3.9+")
        return False
    
    # 2. Создание .env если не существует
    env_file = root / ".env"
    env_example = root / ".env.example"
    
    if not env_file.exists() and env_example.exists():
        print("\n📝 Создание .env из .env.example...")
        import shutil
        shutil.copy(env_example, env_file)
        print("✅ Файл .env создан")
        print("⚠️  ВНИМАНИЕ: Заполните значения в файле .env (особенно YOOKASSA_SHOP_ID и YOOKASSA_API_KEY)")
    
    # 3. Установка зависимостей
    if not run_command(
        f"{sys.executable} -m pip install -q --upgrade pip",
        "Обновление pip"
    ):
        return False
    
    if not run_command(
        f"{sys.executable} -m pip install -r {root}/requirements.txt",
        "Установка зависимостей из requirements.txt"
    ):
        return False
    
    # 4. Инициализация БД
    print(f"\n{'='*60}")
    print("🗄️  Инициализация базы данных")
    print(f"{'='*60}")
    try:
        os.chdir(root)
        from db.base import init_db, sync_engine
        import asyncio
        
        asyncio.run(init_db())
        print("✅ База данных инициализирована")
    except Exception as e:
        print(f"⚠️  Ошибка инициализации БД: {e}")
        print("   Можно попробовать позже")
    
    # 5. Итоговая информация
    print(f"""
╔════════════════════════════════════════════════════════════════╗
║                    ✅ Инициализация завершена                 ║
╚════════════════════════════════════════════════════════════════╝

🚀 Для запуска приложения:

   Веб-приложение:
   $ python run_web.py
   → http://localhost:8000

   Telegram-бот:
   $ python main.py

📝 Важно:
   1. Заполните значения в файле .env
   2. Особенно YOOKASSA_SHOP_ID и YOOKASSA_API_KEY
   3. Установите SECRET_KEY на уникальное значение

📚 Документация:
   - WEB_README.md - Полное руководство
   - API_EXAMPLES.py - Примеры API
   - INTEGRATION_GUIDE.md - Интеграция с ботом
    """)
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
