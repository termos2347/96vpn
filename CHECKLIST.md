# Чек-лист для запуска NeuroPrompt Premium

## ✅ Фаза 1: Подготовка

- [ ] Python 3.9+ установлен
- [ ] Клонирован репозиторий
- [ ] Установлены зависимости: `pip install -r requirements.txt`
- [ ] Скопирован файл: `cp .env.example .env`

## ✅ Фаза 2: Конфигурация

- [ ] Заполнены переменные в `.env`:
  - [ ] `YOOKASSA_SHOP_ID`
  - [ ] `YOOKASSA_API_KEY`
  - [ ] `SECRET_KEY`
  - [ ] `SITE_URL` (для локального тестирования: `http://localhost:8000`)
  - [ ] `DATABASE_URL` (для локального: `sqlite:///./neuroprompt.db`)

## ✅ Фаза 3: База данных

- [ ] Применены миграции: `alembic upgrade head`
- [ ] БД инициализирована: `python -c "from db.base import init_db; import asyncio; asyncio.run(init_db())"`

## ✅ Фаза 4: Yookassa

- [ ] Создан аккаунт на https://yookassa.ru/
- [ ] Включены платежи в кабинете
- [ ] Скопированы Shop ID и API Key в `.env`
- [ ] Настроена обработка webhooks (если нужно):
  - Webhook URL: `https://yourdomain.com/api/payment/webhook/yookassa`

## ✅ Фаза 5: Тестирование

- [ ] Запущено приложение: `python run_web.py`
- [ ] Открыта главная страница: `http://localhost:8000`
- [ ] Проверена регистрация
- [ ] Проверен вход
- [ ] Проверена страница оплаты
- [ ] Проверен личный кабинет
- [ ] Проверены промпты (после активации подписки)

## ✅ Фаза 6: Production (опционально)

- [ ] Получен SSL сертификат (Let's Encrypt)
- [ ] Настроен Nginx или Apache
- [ ] Запущен Gunicorn: `gunicorn -k uvicorn.workers.UvicornWorker web.app:app`
- [ ] Настроена база данных PostgreSQL
- [ ] Создана .env для production
- [ ] Включена система мониторинга

## 🚨 Частые ошибки

- ❌ `ModuleNotFoundError: No module named 'web'`
  → Убедитесь, что запускаете из корневой папки проекта

- ❌ `ImportError: cannot import name 'settings'`
  → Проверьте, что файл `web/config.py` существует и `.env` заполнен

- ❌ `Yookassa payment failed`
  → Проверьте `YOOKASSA_SHOP_ID` и `YOOKASSA_API_KEY` в `.env`

- ❌ `Port 8000 already in use`
  → Запустите на другом порте: `uvicorn web.app:app --port 8001`

## 📞 Справка

```bash
# Запуск веб-приложения
python run_web.py

# Запуск на другом порте
uvicorn web.app:app --port 8001 --reload

# Просмотр БД SQLite
sqlite3 neuroprompt.db ".tables"

# Применение новых миграций
alembic upgrade head

# Создание новой миграции
alembic revision --autogenerate -m "description"
```

## 🎯 Next Steps

1. Настроить интеграцию с Telegram ботом (если необходимо)
2. Подключить собственный домен
3. Настроить SSL сертификат
4. Перейти на PostgreSQL для production
5. Настроить резервные копии БД
6. Добавить аналитику (Mixpanel, Google Analytics)
7. Настроить Email уведомления
