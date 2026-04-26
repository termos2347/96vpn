# 96vpn

Telegram-бот для управления VPN-подписками с интеграцией 3x-ui панели.

## Функциональность
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
├── main.py                 # Точка входа
├── config.py              # Конфигурация
├── requirements.txt       # Зависимости
├── alembic.ini           # Настройки миграций
├── db/
│   ├── base.py           # Настройка БД
│   ├── models.py         # Модели SQLAlchemy
│   └── crud.py           # Функции работы с БД
├── handlers/             # Обработчики команд
│   ├── common.py         # Общие команды
│   ├── keyboards.py      # Клавиатуры
│   └── ...
├── services/             # Бизнес-логика
│   ├── vpn_manager.py    # Управление VPN
│   ├── vpn_provider.py   # Интеграция с 3x-ui
│   └── scheduler.py      # Фоновые задачи
├── utils/                # Утилиты
└── migrations/           # Миграции БД
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

## Поддержка
По вопросам: @support_username