### ВЕТКА MAIN ЯВЛЯЕТСЯ УТСАРЕВШЕЙ, РАЗРАБОТКА ВЕДЕТСЯ В ВЕТКЕ no-site

96VPN – универсальная платформа для продажи VPN и AI-промптов
Telegram-бот + веб-сайт с платёжной системой (ЮKassa, Telegram Stars).
Возможности: управление VPN-подписками (3x‑UI), продажа доступа к базе профессиональных промптов, административный бот для управления контентом и серверами.

🚀 Основные возможности
VPN-подписки (протокол VLESS) через пул серверов 3x‑UI.

Обход DPI (опционально, в разработке).

База AI-промптов (ChatGPT, Midjourney) с платной подпиской.

Платежи: ЮKassa (RUB), Telegram Stars, USDT (через ссылку на сайт).

Административный бот для рассылок, выдачи подписок, управления серверами, категориями и промптами.

Веб-сайт на FastAPI с личным кабинетом, каталогом промптов, оплатой.

Автоматические напоминания об истечении подписки, отзыв ключей.

Docker‑ready (разработка и продакшен с автоматическим SSL).

📦 Технологический стек
Компонент	Технологии
Бот	aiogram 3.x, aiohttp
Веб-приложение	FastAPI, Jinja2, Uvicorn
База данных	PostgreSQL (asyncpg) / SQLite, SQLAlchemy 2.0, Alembic
Кэширование	Redis + in‑memory fallback
Платежи	ЮKassa SDK, Telegram Stars
VPN-интеграция	3x‑UI API (VLESS)
Безопасность	JWT, bcrypt, CSRF, Fernet (шифрование паролей серверов)
Инфраструктура	Docker, nginx‑proxy + Let's Encrypt, Sentry, Prometheus (опционально)
⚙️ Требования к окружению
Python 3.9+

PostgreSQL 13+ (или SQLite для разработки)

Redis (рекомендуется, но не обязательно)

Docker и Docker Compose (для контейнеризации)

3x‑UI панель (одна или несколько) с настроенным inbound (VLESS)

🛠 Установка и настройка
1. Клонирование репозитория
bash
git clone https://github.com/your-org/96vpn.git
cd 96vpn
2. Виртуальное окружение
bash
python -m venv venv
source venv/bin/activate      # Linux/Mac
venv\Scripts\activate          # Windows
3. Установка зависимостей
bash
pip install -r requirements.txt
4. Переменные окружения (файл .env)
Скопируйте .env.example в .env и заполните обязательные поля:

ini
# Telegram боты
BOT_TOKEN=123456:ABC...
ADMIN_BOT_TOKEN=789012:XYZ...
ADMIN_CHAT_ID=123456789

# База данных (PostgreSQL)
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/vpn_db

# ЮKassa (обязательно для приёма рублёвых платежей)
YOOKASSA_SHOP_ID=...
YOOKASSA_API_KEY=...

# Внутренний API (для связи бота и сайта)
INTERNAL_API_SECRET=ваш_секретный_ключ

# Шифрование паролей VPN-серверов (сгенерировать командой: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
ENCRYPTION_KEY=...

# JWT
SECRET_KEY=super-secret-jwt-key

# URLs
SITE_URL=https://yourdomain.com
WEBHOOK_URL=https://yourdomain.com/webhook
ADMIN_WEBHOOK_URL=https://yourdomain.com/webhook/admin

# Ссылки на юридические документы (Google Docs и т.п.) – опционально
LEGAL_TERMS_URL=https://docs.google.com/document/d/...
LEGAL_PRIVACY_URL=https://docs.google.com/document/d/...
5. Инициализация базы данных
bash
# Создание таблиц (автоматически через SQLAlchemy)
python -c "import asyncio; from db.base import init_db; asyncio.run(init_db())"

# Применение миграций Alembic (рекомендуется в продакшене)
alembic upgrade head
6. Запуск
Локально (разработка):

bash
# Только бот (polling)
python main.py

# Только веб-сервер (FastAPI)
python run_web.py

# Всё вместе (бот + веб + внутреннее API)
python run_all.py
Через Docker (разработка):

bash
docker-compose up -d
Продакшен (автоматический SSL через nginx-proxy):

bash
# Убедитесь, что домен настроен на ваш сервер
./start_server.sh
Скрипт запросит домен, настроит SSL и установит вебхуки.

📁 Структура проекта
```
96vpn/
├── config.py                 # Pydantic‑settings, загрузка .env
├── main.py                   # Запуск бота (polling)
├── run_all.py                # Запуск всех компонентов (веб + боты + внутр. API)
├── run_web.py                # Запуск только веб-сервера
├── internal_api.py           # aiohttp API для активации подписок (порт 8001)
│
├── db/                       # База данных
│   ├── base.py               # engine, async session
│   ├── models.py             # SQLAlchemy модели
│   ├── crud.py               # CRUD для пользователей, платежей, категорий, промптов
│   ├── crud_servers.py       # CRUD для VPN-серверов
│   └── migrate.py            # Автоматические миграции при старте
│
├── handlers/                 # Обработчики основного бота
│   ├── common.py             # /start, ℹ️ Инфо
│   ├── payment.py            # Оплата VPN (ссылки, Stars)
│   ├── subscription.py       # Подключить VPN
│   ├── proxy.py              # Бесплатный прокси (заглушка)
│   ├── keyboards.py          # Клавиатуры
│   └── __init__.py           # Сборка роутеров + глобальные менеджеры
│
├── handlers/admin/           # Административный бот
│   ├── bot.py                # Команды: /grant, /revoke, /broadcast, /stats и др.
│   ├── categories.py         # /addcategory, /renamecategory, /deletecategory
│   ├── prompts.py            # /addprompt (FSM), /editprompt, /deleteprompt, /listprompts
│   ├── servers.py            # /addserver (FSM), /listservers, /removeserver, /serversetactive
│   └── server_states.py      # FSM состояния для сервера
│
├── services/                 # Бизнес-логика
│   ├── vpn_provider.py       # XUIVPNProvider – API 3x‑UI
│   ├── vpn_manager.py        # VPNManager – создание/отзыв ключей через server_pool
│   ├── server_pool.py        # ServerPool – загрузка серверов из БД, round‑robin
│   ├── scheduler.py          # Фоновые задачи (проверка истекших, напоминания)
│   ├── subscription_service.py  # Единый сервис активации подписок
│   └── (dpi_bypass.py, payment_gateway.py – заглушки)
│
├── web/                      # FastAPI веб-приложение
│   ├── app.py                # Lifespan, CORS, CSRF, middleware
│   ├── routes/               # Маршруты: auth, payment, prompts, web
│   ├── services/             # AuthService, SubscriptionService, YookassaService, CacheService
│   ├── templates/            # Jinja2 шаблоны (главная, дашборд, промпты, оплата и т.д.)
│   ├── static/               # CSS, favicon (опционально)
│   └── schemas/              # Pydantic схемы
│
├── utils/                    # Вспомогательные модули
│   ├── validators.py         # Валидация user_id, email, days, currency, uuid
│   ├── decorators.py         # rate_limit (с исправленным окном 1 минута)
│   ├── logger.py             # Настройка логирования с ротацией
│   ├── email.py              # Отправка email (SMTP / мок)
│   ├── encryption.py         # Fernet шифрование/дешифрование
│   ├── cache.py              # Простой in‑memory кэш
│   └── helpers.py            # Генерация случайного пароля
│
├── migrations/               # Alembic миграции
├── tests/                    # Юнит-тесты (pytest)
├── docker-compose.yml        # Локальный запуск (Redis + app)
├── docker-compose.prod.yml   # Продакшен (nginx-proxy + acme-companion + app)
├── Dockerfile                # Сборка образа
├── start_local.sh            # Запуск в dev режиме
├── start_server.sh           # Автодеплой на сервер (с SSL)
├── healthcheck.sh            # Диагностика всех компонентов
├── requirements.txt
├── .env.example
└── README.md                 # Данный файл
```

🔌 API веб-приложения (основные эндпоинты)
Метод	Путь	Описание
POST	/api/auth/register	Регистрация
POST	/api/auth/login	Вход (устанавливает cookie)
POST	/api/auth/logout	Выход
POST	/api/auth/forgot-password	Восстановление пароля
POST	/api/auth/reset-password	Сброс пароля
POST	/api/payment/create	Создание платёжной ссылки (подписка на промпты)
POST	/api/payment/initiate-vpn	Создание платежа для VPN (по JWT‑токену из бота)
GET	/api/payment/status/{payment_id}	Статус платежа
POST	/api/payment/webhook/yookassa	Вебхук ЮKassa
GET	/api/prompts/all	Список промптов (с фильтром по подписке)
GET	/api/prompts/categories	Список категорий
GET	/health	Проверка состояния
POST	/webhook	Вебхук основного бота
POST	/webhook/admin	Вебхук админ-бота


🤖 Telegram боты
Основной бот (@YourVPNBot)
Команды (через Reply‑клавиатуру):

🚀 Подключить VPN – получить ссылку для подключения (VLESS).

💳 Оплатить VPN – выбор валюты (RUB, Stars, USDT) и периода, переход на сайт.

ℹ️ Инфо – статус подписок, контакты.

Оплата через Telegram Stars работает нативно (без сайта).

Административный бот (@YourAdminBot)
Только для пользователя с ADMIN_CHAT_ID. Команды:

Команда	Описание
/health	Проверка БД и VPN-панели
/errors	Последние ошибки из логов
/broadcast (reply на сообщение)	Рассылка текста/медиа всем пользователям
/userinfo <id>	Информация о подписке, ключе
/grant <id> <days>	Выдать/продлить VPN-подписку
/revoke <id>	Отозвать VPN-ключ и деактивировать подписку
/stats	Статистика (всего, активных, истекающих и т.д.)
/addcategory <name>	Создать категорию промптов
/renamecategory <old> <new>	Переименовать
/deletecategory <name>	Удалить (вместе с промптами)
/addprompt	Пошаговое добавление промпта (FSM)
/editprompt <id> поле=значение	Редактирование (title, description, content, is_free)
/deleteprompt <id>	Удалить
/listprompts [категория]	Список промптов
/addserver	Пошаговое добавление VPN-сервера
/listservers	Список всех серверов
/removeserver <id>	Удалить (только если нет привязанных пользователей)
/serversetactive <id> <0|1>	Вкл/выкл сервер
🌐 Управление VPN-серверами
Серверы хранятся в таблице vpn_servers (хост, порт, inbound_id, API‑путь, пароль (зашифрован), вес, активность).

Пароли шифруются через Fernet (ключ ENCRYPTION_KEY).

При старте бот загружает активные серверы, логинится на каждый (фоновая авторизация).

Клиенты создаются на сервере с наименьшим весом (round‑robin с учётом веса).

При отзыве подписки ключ удаляется с того сервера, где был создан.

Добавление нового сервера (через админ-бота):

text
/addserver → вводим: название, полный URL панели (https://host:port/api_path), inbound_id, логин, пароль, вес.
После добавления сервер автоматически появится в пуле и начнёт использоваться.

📝 Управление промптами (категории + промпты)
Категории и промпты хранятся в БД.

Промпты могут быть бесплатными или платными (доступ по активной веб-подписке).

Кэширование списка промптов в Redis (TTL 5 минут). После изменений через админ-бота кэш сбрасывается.

На сайте промпты отображаются с фильтром по категориям и поиском.

💳 Платежи
ЮKassa (RUB)
Пользователь на сайте выбирает тариф (месяц, квартал, полгода) → создаётся платёж → редирект на платёжную страницу → после успеха вебхук активирует подписку.

Для VPN используется JWT‑токен с метаданными (telegram_id, продукт, период). Вебхук вызывает внутреннее API бота.

Telegram Stars
В боте выбирается период → выставляется инвойс → после оплаты напрямую активируется подписка (идемпотентность через таблицу bot_payments).

USDT
При выборе USDT генерируется ссылка на сайт с JWT‑токеном, где пользователь оплачивает через ЮKassa (сумма в рублях по курсу). В будущем возможна прямая крипто-оплата.

Идемпотентность гарантируется через таблицу bot_payments (уникальный payment_id).

🩺 Healthcheck и мониторинг
Скрипт ./healthcheck.sh проверяет:

Запущены ли контейнеры/процессы

Доступность веб-сайта (/health)

Подключение к БД и Redis

Установку вебхуков Telegram

Внутреннее API (порт 8001)

Логи на наличие ошибок

Опционально – отправляет тестовое сообщение в чат

Эндпоинты:

GET /health – общий статус (БД, бот)

GET /health/bot – статус основного бота (username, webhook)

🧪 Устранение типичных проблем
Проблема	Решение
Бот не отвечает / вебхук не работает	Проверить WEBHOOK_URL и WEBHOOK_SECRET, запустить ./healthcheck.sh
Платежи не проходят (ЮKassa)	Убедиться, что вебхук https://domain/api/payment/webhook/yookassa доступен снаружи (ngrok для тестов), проверить YOOKASSA_SHOP_ID и API_KEY
VPN‑ключ не создаётся	Проверить логи: ошибка авторизации на 3x‑UI, неверный inbound_id или URL. Включить XUI_VERIFY_SSL=false для самоподписного сертификата
Ошибка sqlalchemy.exc.ArgumentError	Убедиться, что миграции применены (alembic upgrade head)
Rate limit срабатывает слишком часто	Исправлен декоратор в utils/decorators.py (окно 1 минута). Если нужно изменить лимит, передавайте max_per_minute
Пользователь не может получить ссылку, хотя подписка активна	Выполнить /grant повторно или /revoke / /grant – принудительно пересоздаст ключ
📄 Лицензия
Проект распространяется под лицензией MIT. Используйте, модифицируйте, распространяйте свободно.

🙌 Благодарности
aiogram – асинхронный фреймворк для ботов

FastAPI – современный веб-фреймворк

3x‑UI – панель управления Xray

ЮKassa – платёжная система

Вопросы и предложения: создавайте Issue в репозитории или пишите в поддержку бота.
