# 96VPN Bot

Telegram-бот для продажи VPN-подписок с интеграцией 3x‑UI, ЮKassa и Telegram Stars.

## Возможности
- VPN-подписки через пул серверов 3x‑UI.
- Оплата через ЮKassa (RUB), Telegram Stars, USDT (через ссылку).
- Автоматическое создание/отзыв ключей.
- Напоминания об истечении, фоновые задачи.
- Административный бот для управления пользователями, серверами, рассылками.

## Технологии
- aiogram 3.x
- aiohttp (внутреннее API)
- PostgreSQL, SQLAlchemy, Alembic
- Yookassa SDK, cryptography, tenacity

## Установка
1. Клонируйте репозиторий.
2. Создайте виртуальное окружение и установите зависимости (`pip install -r requirements.txt`).
3. Скопируйте `.env.example` в `.env` и заполните обязательные переменные.
4. Примените миграции: `alembic upgrade head`.
5. Запустите: `python run_all.py`.
```
git clone https://github.com/your-repo/96vpn-bot.git
cd 96vpn-bot
python3 -m venv .venv
source .venv/bin/activate          # для Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Запуск
```
npx localtunnel --port 5001 --subdomain my-vpn-bot
```

```
chmod +x run.sh
./run.sh
```
## Переменные окружения
(перечислите только необходимые – см. выше)

## Команды бота
- Основной бот: кнопки в меню.
- Админ-бот: `/health`, `/grant`, `/revoke`, `/stats`, `/broadcast`, `/addserver`, `/listservers` и т.д.

## Внутреннее API
- `/activate` – активация подписки (защищено токеном).
- `/yookassa_webhook` – вебхук для ЮKassa.
- `/webhook` – вебхук основного бота.
- `/webhook/admin` – вебхук админ-бота.

## Архитектурные особености
- Бот работает **только в одном экземпляре** (однопроцессный).
- **Rate limiting** и **кэш** хранятся в оперативной памяти и сбрасываются при перезапуске бота.
- Для горизонтального масштабирования (несколько воркеров) потребуется внешнее хранилище (Redis, Memcached) и централизованное управление сессиями.
- В текущей версии Redis **не используется** и не поддерживается.