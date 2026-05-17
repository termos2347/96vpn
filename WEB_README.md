# NeuroPrompt Premium - FastAPI Веб-приложение

## 📋 Описание

**NeuroPrompt Premium** — это современное веб-приложение на FastAPI для продажи AI-промптов по подписке. Одновременно служит платёжным шлюзом для существующего Telegram-бота.

### Основные возможности:
- 🎨 Современный веб-интерфейс на Tailwind CSS
- 👥 Система регистрации и аутентификации
- 💳 Интеграция с Yookassa для обработки платежей
- 🤖 Интеграция с Telegram-ботом
- 📚 База из 100+ профессиональных AI-промптов
- 🔐 Защита данных и управление подписками
- 📱 Адаптивный дизайн

## 🛠️ Требования

- Python 3.9+
- FastAPI 0.104+
- SQLAlchemy 2.0+
- SQLite (или PostgreSQL)

## 📦 Установка и запуск

### 1. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 2. Конфигурация

Скопируйте `.env.example` в `.env` и заполните необходимые параметры:

```bash
cp .env.example .env
```

**Важные параметры для редактирования в `.env`:**

```env
# Yookassa (получить на https://yookassa.ru/)
YOOKASSA_SHOP_ID=your_shop_id_here
YOOKASSA_API_KEY=your_api_key_here

# Безопасность
SECRET_KEY=your-super-secret-key

# Базовые данные
SITE_URL=http://localhost:8000
ADMIN_EMAIL=admin@neuroprompt.ai
```

### 3. Инициализация БД

```bash
# Применить миграции
alembic upgrade head
```

### 4. Запуск приложения

```bash
# Способ 1: Через скрипт
python run_web.py

# Способ 2: Через uvicorn напрямую
uvicorn web.app:app --reload --host 0.0.0.0 --port 8000

# Способ 3: Через main.py (если интегрируете с ботом)
python main.py
```

Приложение будет доступно по адресу: **http://localhost:8000**

## 📖 Структура проекта

```
web/
├── app.py                 # Главное FastAPI приложение
├── config.py             # Конфигурация приложения
├── security.py           # JWT и аутентификация
├── routes/               # API маршруты
│   ├── web.py           # Маршруты фронтенда
│   ├── auth.py          # Регистрация и вход
│   ├── payment.py       # Платежи и Yookassa
│   └── prompts.py       # API промптов
├── services/            # Бизнес-логика
│   ├── auth.py          # Сервис аутентификации
│   ├── payment.py       # Интеграция Yookassa
│   └── __init__.py
├── schemas/             # Pydantic модели
│   └── schemas.py       # DTO и валидация
├── templates/           # Jinja2 шаблоны HTML
│   ├── base.html
│   ├── index.html       # Главная страница
│   ├── login.html
│   ├── register.html
│   ├── dashboard.html   # Личный кабинет
│   ├── prompts.html     # Список промптов
│   ├── prompt_detail.html
│   ├── payment_telegram.html  # Оплата для Telegram
│   ├── terms.html       # Публичная оферта
│   └── privacy.html     # Политика конфиденциальности
└── static/              # Статические файлы
    └── css/
```

## 🌐 Основные страницы

### Публичные:
- `/` — Главная страница/Лендинг
- `/register` — Регистрация
- `/login` — Вход
- `/pay/{tg_id}` — Оплата из Telegram-бота
- `/legal/terms` — Публичная оферта
- `/legal/privacy` — Политика конфиденциальности

### Защищённые:
- `/dashboard` — Личный кабинет
- `/prompts` — База промптов (только для активных подписчиков)
- `/prompt/{id}` — Детали промпта

## 🔌 API Endpoints

### Аутентификация
```
POST /api/auth/register
POST /api/auth/login
GET  /api/auth/profile/{user_id}
```

### Платежи
```
POST /api/payment/create/{user_id}?plan=monthly|quarterly
GET  /api/payment/status/{payment_id}
POST /api/payment/webhook/yookassa
GET  /api/payment/subscription-info/{user_id}
POST /api/payment/activate/{user_id}/{telegram_id}
```

### Промпты
```
GET /api/prompts/all
GET /api/prompts/{prompt_id}
```

## 💳 Интеграция Yookassa

### Как подключить:

1. **Создайте аккаунт на [Yookassa](https://yookassa.ru/)**
2. **Получите:**
   - `SHOP_ID` (идентификатор магазина)
   - `API_KEY` (секретный ключ API)
3. **Установите в `.env`:**
   ```env
   YOOKASSA_SHOP_ID=123456
   YOOKASSA_API_KEY=live_xxxxx...
   ```

### Как работает платёж:

1. Пользователь выбирает тариф
2. Создаётся платёж через Yookassa API
3. Пользователь перенаправляется на страницу оплаты Yookassa
4. После успешной оплаты Yookassa отправляет webhook
5. Подписка активируется автоматически

## 🤖 Интеграция с Telegram-ботом

### Для оплаты из Telegram:

```python
# В обработчике бота
payment_url = f"{SITE_URL}/pay/{user_telegram_id}"
```

Пользователь кликнет на ссылку и попадёт на упрощённую страницу оплаты.

## 👥 Типы пользователей

### Веб-пользователи (`source='web'`):
- Регистрируются с email и паролем
- Имеют доступ к личному кабинету
- Могут оформить подписку на сайте

### Telegram-пользователи (`source='bot'`):
- Регистрируются автоматически при первом платеже
- Имеют `user_id` = Telegram ID
- Могут оплатить через упрощённую форму

## 📊 Тарифы

| План | Цена | Срок |
|------|------|------|
| Месячная подписка | 290₽ | 1 месяц |
| Квартальная подписка | 790₽ | 3 месяца |

*Экономия на квартальной подписке: 180₽*

## 🔐 Безопасность

- Пароли хешируются с помощью bcrypt
- JWT токены для аутентификации
- HTTPS рекомендуется для production
- SQL-injection защита через SQLAlchemy ORM
- CORS настроена для безопасности

## 🚀 Развёртывание на Production

### Через Gunicorn + Uvicorn:

```bash
pip install gunicorn

gunicorn -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000 web.app:app
```

### Через Docker:

```dockerfile
FROM python:3.11

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Nginx конфиг:

```nginx
server {
    listen 80;
    server_name neuroprompt.ai www.neuroprompt.ai;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## 📞 Поддержка

- **Email:** support@neuroprompt.ai
- **Сайт:** http://localhost:8000

## 📄 Лицензия

Закрытая лицензия. Все права защищены.

---

**Создано для продажи AI-промптов и интеграции с Telegram-ботом.**
