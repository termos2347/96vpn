# 96vpn

Telegram-бот для управления VPN-подписками с интеграцией 3x-ui панели.

## Функциональность?
- Управление VPN-подписками (VLESS протокол)
- Поддержка нескольких валют (RUB, Telegram Stars, USDT)
- Автоматическое создание и отзыв ключей
- Уведомления о истечении подписки
- DPI bypass для обхода блокировок

## Установка и запуск

### 1. Клонирование репозитория
```bash
git clone <repository-url>
cd 96vpn
```

### 2. Создание виртуального окружения
```bash
python -m venv venv
venv\Scripts\activate  # Windows
# или
source venv/bin/activate  # Linux/Mac
```

### 3. Установка зависимостей
```bash
pip install -r requirements.txt
```

### 4. Настройка переменных окружения
Создайте файл `.env` в корне проекта:
```env
# Telegram Bot
BOT_TOKEN=your_bot_token_here

# Database
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/vpn_db

# Proxy (опционально)
PROXY_URL=http://proxy.example.com:8080

# 3x-ui Panel
XUI_BASE_URL=https://your-xui-panel.com
XUI_USERNAME=admin
XUI_PASSWORD=your_password
XUI_INBOUND_ID=1
XUI_SUB_PORT=2096
```

### 5. Инициализация базы данных
```bash
# Создание таблиц
python -c "import asyncio; from db.base import init_db; asyncio.run(init_db())"

# Или через Alembic (рекомендуется для продакшена)
alembic upgrade head
```

### 6. Запуск бота
```bash
python main.py
```

## Структура проекта
```
96vpn/
├── config.py                # Pydantic‑settings, загрузка .env
├── .env.example             # Шаблон переменных окружения
├── requirements.txt
├── alembic.ini
│
├── db/                      # Модели, CRUD, миграции
│   ├── base.py              # async/sync engine, сессии
│   ├── models.py            # WebUser, BotUser, VPNServer, Category, Prompt, BotPayment
│   ├── crud.py              # операции с BotUser, платежами, категориями, промптами
│   └── crud_servers.py      # операции с VPNServer
│
├── handlers/                # Обработчики основного бота
│   ├── common.py            # /start, кнопка "Инфо"
│   ├── keyboards.py         # Reply‑ и Inline‑клавиатуры
│   ├── payment.py           # Оплата VPN / обхода (JWT‑токен -> ссылка на сайт)
│   ├── subscription.py      # "Подключить VPN" – отдать ссылку
│   ├── proxy.py             # Бесплатный прокси
│   └── __init__.py          # Сборка всех роутеров, глобальный VPNManager
│
├── handlers/admin/          # Административный бот (отдельный)
│   ├── bot.py               # Команды /health, /broadcast, /grant, /revoke, /stats
│   ├── categories.py        # /addcategory, /renamecategory, /deletecategory
│   ├── prompts.py           # /addprompt (FSM), /editprompt, /deleteprompt, /listprompts
│   ├── servers.py           # /addserver (FSM), /listservers, /removeserver, /serversetactive
│   ├── server_states.py     # FSM‑состояния для добавления сервера
│   └── __init__.py          # Роутер для админ‑бота
│
├── services/                # Бизнес‑логика
│   ├── vpn_provider.py      # XUIVPNProvider – работа с API 3x‑UI
│   ├── vpn_manager.py       # VPNManager – создание/отзыв ключей через ServerPool
│   ├── server_pool.py       # ServerPool – загрузка серверов из БД, round‑robin
│   ├── scheduler.py         # Фоновая проверка подписок и отзыв ключей
│   └── (ещё: dpi_bypass.py, payment_gateway.py – заглушки)
│
├── utils/                   # Вспомогательные модули
│   ├── validators.py        # Валидация user_id, email, days, currency, uuid
│   ├── decorators.py        # rate_limit для бота
│   ├── logger.py            # Настройка логгирования с ротацией
│   └── email.py             # Отправка писем (заглушка/реальный SMTP)
│
├── web/                     # FastAPI веб‑приложение
│   ├── app.py               # Создание app, lifespan, CORS, статика
│   ├── rate_limit.py        # SlowAPI лимитер
│   ├── security.py          # JWT (create_access_token, get_current_user_optional)
│   ├── schemas/schemas.py   # Pydantic‑схемы
│   ├── services/            # Сервисы для веба
│   │   ├── auth.py          # AuthService (регистрация, логин, сброс пароля)
│   │   └── payment.py       # YookassaService (create_payment, webhook, check_and_activate)
│   ├── routes/              # Маршруты
│   │   ├── auth.py          # /api/auth/register, /login, /forgot‑password и т.д.
│   │   ├── payment.py       # /api/payment/create, /initiate‑vpn, webhook
│   │   ├── prompts.py       # /api/prompts/all, /categories
│   │   └── web.py           # HTML‑страницы: /, /dashboard, /prompts, /pay/subscription ...
│   └── templates/           # Jinja2 шаблоны (все 15+ файлов)
│       ├── base.html
│       ├── index.html, login.html, register.html
│       ├── dashboard.html, prompts.html, prompt_detail.html
│       ├── payment_telegram.html, pay_choice.html
│       ├── vpn_payment.html, vpn_success.html
│       ├── terms.html, privacy.html
│       ├── forgot_password.html, reset_password.html
│       └── subscribe_required.html, payment_success.html, payment_failed.html
│
├── internal_api.py          # HTTP API на aiohttp (порт 8001) – активация подписки бота
├── run_web.py               # Запуск только веба (через uvicorn)
├── run_all.py               # Запуск всего: веб (FastAPI) + внутреннее API + боты (webhook)
├── main.py                  # Запуск только бота (polling, для разработки)
├── init.py                  # Скрипт инициализации проекта
│
└── tests/                   # Юнит‑тесты (test_vpn_manager, test_validators и др.)
```

## Тестирование
```bash
# Запуск всех тестов
pytest

# С конкретным файлом
pytest test_vpn_manager.py -v
```

## Развертывание
Для продакшена рекомендуется:
- Использовать PostgreSQL
- Настроить логирование в файл
- Добавить мониторинг (health checks)
- Использовать Docker для контейнеризации

## Юкасса
чтобы сайт мог получать платжеи необходимо подключить ngrok
в личном кабинете укажите ссылку котрую выдал ngrok чтобы сайт мог принимать вебхук от Юкассы

## Поддержка
По вопросам: @support_username