# 🧪 Гайд по тестированию и проверке кода перед коммитом

Перед тем как пушить изменения на GitHub, используй этот гайд для проверки кода.

## 1️⃣ Быстрая проверка синтаксиса

Проверь что в коде нет синтаксических ошибок:

```bash
python -m py_compile main.py config.py services/vpn_manager.py db/models.py handlers/common.py
```

Или проще - в VS Code: `Ctrl+Shift+P` > "Python: Run Linting"

## 2️⃣ Проверка импортов

Убедись что все зависимости установлены и импортируются:

```bash
python -c "import aiogram, aiohttp, sqlalchemy, asyncpg, alembic, dotenv; print('All imports OK!')"
```

## 3️⃣ Запуск тестов

Главный способ проверить что код работает:

```bash
# Запустить все тесты
pytest test_vpn_manager.py -v

# Или конкретный тест
pytest test_vpn_manager.py::test_config_loading -v

# С покрытием (если нужно)
pytest test_vpn_manager.py --cov=services --cov=config
```

## 4️⃣ Проверка конфигурации

Убедись что конфиг загружается правильно:

```bash
python -c "from config import TOKEN, DATABASE_URL, VPN_PRICES; print('Config OK!')"
```

## 5️⃣ Проверка логики основных модулей

Проверь что основные модули импортируются без ошибок:

```bash
python -c "from db.models import User; from services.vpn_manager import VPNManager; print('Modules OK!')"
```

## 📋 Полный чек перед коммитом

Используй эту команду для полной проверки:

```bash
@echo off
echo Checking Python syntax...
python -m py_compile main.py config.py services/*.py db/*.py handlers/*.py
if %errorlevel% neq 0 (
    echo Syntax errors found!
    exit /b 1
)
echo OK!

echo Running tests...
pytest test_vpn_manager.py -v
if %errorlevel% neq 0 (
    echo Tests failed!
    exit /b 1
)
echo All tests passed!

echo Checking imports...
python -c "import aiogram, aiohttp, sqlalchemy, asyncpg, alembic, dotenv; print('All imports OK!')"
if %errorlevel% neq 0 (
    echo Import errors!
    exit /b 1
)

echo All checks passed! Ready to commit.
```

Сохрани это как `check_before_commit.bat` и запускай перед коммитом:
```bash
check_before_commit.bat
```

## 🚀 Запуск основного бота (если готова БД)

Когда будешь готова запустить реальный бот:

```bash
python main.py
```

**Важно**: Убедись что у тебя есть:
- ✅ Файл `.env` с правильными переменными
- ✅ PostgreSQL база данных запущена
- ✅ Панель 3x-ui доступна

## 📊 Результаты последнего теста:

```
test_vpn_manager.py::test_vpn_manager_initialization PASSED
test_vpn_manager.py::test_vpn_provider_initialization PASSED
test_vpn_manager.py::test_config_loading PASSED
test_vpn_manager.py::test_vpn_prices_structure PASSED

============================== 4 passed in 0.37s ==============================
```

✅ **Код готов к коммиту на GitHub!**
