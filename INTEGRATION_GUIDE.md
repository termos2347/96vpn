"""
Руководство по использованию NeuroPrompt Premium с Telegram ботом

Есть два способа запуска:

1. ТОЛЬКО TELEGRAM БОТ:
   python main.py

2. ТОЛЬКО WEB ПРИЛОЖЕНИЕ:
   python run_web.py

3. ОБА ОДНОВРЕМЕННО (рекомендуется для продакшена):
   - Запустить бота: python main.py &
   - Запустить веб в отдельном терминале: python run_web.py
   - Или использовать supervisor/systemd для управления обоими процессами

СТРУКТУРА ПРОЕКТА:
==================

Telegram Bot:
- main.py - точка входа бота
- handlers/ - обработчики команд бота
- services/ - сервисы (VPN, платежи, планировщик)

Web Application:
- run_web.py - точка входа веб-приложения
- web/app.py - главное FastAPI приложение
- web/routes/ - маршруты (web, auth, payment, prompts)
- web/templates/ - HTML шаблоны
- web/services/ - бизнес-логика (auth, payment)

Database:
- db/models.py - SQLAlchemy модели (общие для обоих)
- db/crud.py - CRUD операции
- migrations/ - Alembic миграции

КОНФИГУРАЦИЯ:
=============

Скопируйте .env.example в .env и заполните:

# Для Telegram бота:
BOT_TOKEN=your_bot_token
DATABASE_URL=your_database_url

# Для Yookassa платежей:
YOOKASSA_SHOP_ID=your_shop_id
YOOKASSA_API_KEY=your_api_key

ПРИМЕРЫ ИСПОЛЬЗОВАНИЯ:
======================

1. Запуск только веб (для разработки):
   python run_web.py
   → http://localhost:8000

2. Запуск бота (для разработки):
   python main.py

3. Для production рекомендуется использовать:
   - Gunicorn + Uvicorn для веб
   - Systemd или Docker для управления процессами

ИНТЕГРАЦИЯ:
===========

Когда пользователь Telegram-бота хочет оплатить:

1. Бот отправляет ссылку:
   https://neuroprompt.ai/pay/{user_telegram_id}

2. Пользователь заполняет форму оплаты

3. После оплаты Yookassa отправляет webhook на:
   POST /api/payment/webhook/yookassa

4. Подписка активируется в БД

5. Бот может проверить статус:
   GET /api/payment/subscription-info/{user_id}

ПЕРВЫЙ ЗАПУСК:
==============

1. Установить зависимости:
   pip install -r requirements.txt

2. Создать .env:
   cp .env.example .env
   # Заполнить параметры

3. Применить миграции БД:
   alembic upgrade head

4. Запустить веб:
   python run_web.py

5. Открыть http://localhost:8000

ДОКУМЕНТАЦИЯ:
=============

- WEB_README.md - подробное руководство веб-приложения
- API_EXAMPLES.py - примеры API запросов
- /api/docs - интерактивная документация FastAPI (swagger)
- /api/redoc - альтернативная документация ReDoc
