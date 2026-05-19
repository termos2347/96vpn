#!/bin/bash
# ============================================================
# NeuroPrompt Premium - Полная проверка работоспособности
# Запуск: ./healthcheck.sh
# ============================================================

set -e  # не выходим при ошибках, продолжаем проверки

# Цвета для вывода
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Флаг общей ошибки
HAS_ERROR=0

# Загрузка переменных из .env, если файл существует
if [ -f .env ]; then
    set -a
    source .env
    set +a
    echo -e "${GREEN}✅ Загружены переменные из .env${NC}"
else
    echo -e "${YELLOW}⚠️  Файл .env не найден, используем переменные окружения${NC}"
fi

# Определяем базовый URL сайта (из .env или localhost)
SITE_URL="${SITE_URL:-http://localhost:8000}"
WEBHOOK_URL="${WEBHOOK_URL:-}"
ADMIN_WEBHOOK_URL="${ADMIN_WEBHOOK_URL:-}"
BOT_TOKEN="${BOT_TOKEN:-}"
ADMIN_BOT_TOKEN="${ADMIN_BOT_TOKEN:-}"
TEST_CHAT_ID="${TEST_CHAT_ID:-}"  # ваш Telegram ID для отправки тестового сообщения

# Определяем, запущены ли контейнеры Docker
if command -v docker &> /dev/null && docker ps --format '{{.Names}}' | grep -q 'neuroprompt_app'; then
    IN_DOCKER=true
    CONTAINER_NAME="neuroprompt_app"
    REDIS_CONTAINER="neuroprompt_redis"
    echo -e "${GREEN}🐳 Обнаружен запущенный Docker-контейнер${NC}"
else
    IN_DOCKER=false
    echo -e "${YELLOW}⚠️  Docker-контейнер не запущен, проверяем локальный процесс${NC}"
fi

# Функция для выполнения команды внутри контейнера (если в Docker)
exec_in_container() {
    if [ "$IN_DOCKER" = true ]; then
        docker exec "$CONTAINER_NAME" "$@"
    else
        "$@"
    fi
}

echo ""
echo "============================================================"
echo "🔍 НАЧАЛО ПРОВЕРКИ ВСЕХ КОМПОНЕНТОВ"
echo "============================================================"
echo ""

# ----------------------------------------------------------------
# 1. Проверка запущенных контейнеров/процессов
# ----------------------------------------------------------------
echo -e "${GREEN}[1/10] Проверка запущенных процессов...${NC}"

if [ "$IN_DOCKER" = true ]; then
    if docker ps --filter "name=neuroprompt_app" --filter "status=running" | grep -q neuroprompt_app; then
        echo -e "  ✅ Контейнер neuroprompt_app запущен"
    else
        echo -e "  ${RED}❌ Контейнер neuroprompt_app НЕ запущен${NC}"
        HAS_ERROR=1
    fi
    if docker ps --filter "name=neuroprompt_redis" --filter "status=running" | grep -q neuroprompt_redis; then
        echo -e "  ✅ Контейнер neuroprompt_redis запущен"
    else
        echo -e "  ${RED}❌ Контейнер neuroprompt_redis НЕ запущен${NC}"
        HAS_ERROR=1
    fi
else
    if pgrep -f "python run_all.py" > /dev/null; then
        echo -e "  ✅ Процесс run_all.py запущен"
    else
        echo -e "  ${RED}❌ Процесс run_all.py НЕ запущен${NC}"
        HAS_ERROR=1
    fi
fi

# ----------------------------------------------------------------
# 2. Проверка HTTP-доступности сайта (главная страница)
# ----------------------------------------------------------------
echo -e "\n${GREEN}[2/10] Проверка HTTP-доступности сайта...${NC}"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$SITE_URL" --connect-timeout 5)
if [ "$HTTP_CODE" -eq 200 ]; then
    echo -e "  ✅ Главная страница доступна (HTTP $HTTP_CODE)"
else
    echo -e "  ${RED}❌ Главная страница недоступна (HTTP $HTTP_CODE)${NC}"
    HAS_ERROR=1
fi

# ----------------------------------------------------------------
# 3. Проверка эндпоинта /health
# ----------------------------------------------------------------
echo -e "\n${GREEN}[3/10] Проверка health-эндпоинта...${NC}"
HEALTH_RESPONSE=$(curl -s "$SITE_URL/health" --connect-timeout 5)
if echo "$HEALTH_RESPONSE" | grep -q '"status":"ok"'; then
    echo -e "  ✅ Health check OK"
else
    echo -e "  ${RED}❌ Health check провален: $HEALTH_RESPONSE${NC}"
    HAS_ERROR=1
fi

# ----------------------------------------------------------------
# 4. Проверка API промптов (доступность и структура)
# ----------------------------------------------------------------
echo -e "\n${GREEN}[4/10] Проверка API промптов...${NC}"
PROMPTS_RESPONSE=$(curl -s "$SITE_URL/api/prompts/all" --connect-timeout 5)
if echo "$PROMPTS_RESPONSE" | grep -q '\[\|\{' ; then
    echo -e "  ✅ API промптов отвечает"
    # Дополнительно: проверить, что приходит список (хотя бы пустой)
    PROMPTS_COUNT=$(echo "$PROMPTS_RESPONSE" | grep -o '"id"' | wc -l)
    echo -e "  ℹ️  Получено $PROMPTS_COUNT промптов (для неавторизованных - только бесплатные)"
else
    echo -e "  ${RED}❌ API промптов не отвечает или вернул ошибку${NC}"
    HAS_ERROR=1
fi

# ----------------------------------------------------------------
# 5. Проверка подключения к базе данных
# ----------------------------------------------------------------
echo -e "\n${GREEN}[5/10] Проверка подключения к базе данных...${NC}"
DB_CHECK=$(exec_in_container python -c "
import asyncio
from db.base import AsyncSessionLocal
from sqlalchemy import text
async def check():
    async with AsyncSessionLocal() as session:
        await session.execute(text('SELECT 1'))
        print('OK')
asyncio.run(check())
" 2>&1)

if echo "$DB_CHECK" | grep -q "OK"; then
    echo -e "  ✅ База данных доступна"
else
    echo -e "  ${RED}❌ Ошибка подключения к БД: $DB_CHECK${NC}"
    HAS_ERROR=1
fi

# ----------------------------------------------------------------
# 6. Проверка Redis (если используется)
# ----------------------------------------------------------------
if [ -n "$REDIS_URL" ] || [ "$IN_DOCKER" = true ]; then
    echo -e "\n${GREEN}[6/10] Проверка Redis...${NC}"
    if [ "$IN_DOCKER" = true ]; then
        REDIS_PING=$(docker exec "$REDIS_CONTAINER" redis-cli ping 2>/dev/null)
        if [ "$REDIS_PING" = "PONG" ]; then
            echo -e "  ✅ Redis отвечает PONG"
        else
            echo -e "  ${RED}❌ Redis не отвечает${NC}"
            HAS_ERROR=1
        fi
    else
        # если Redis запущен локально без Docker
        if command -v redis-cli &> /dev/null; then
            REDIS_PING=$(redis-cli ping 2>/dev/null)
            if [ "$REDIS_PING" = "PONG" ]; then
                echo -e "  ✅ Redis отвечает PONG"
            else
                echo -e "  ${YELLOW}⚠️  Redis не отвечает (возможно, не используется)${NC}"
            fi
        else
            echo -e "  ${YELLOW}⚠️  redis-cli не найден, пропускаем проверку${NC}"
        fi
    fi
else
    echo -e "\n${GREEN}[6/10] Проверка Redis...${NC}"
    echo -e "  ${YELLOW}⚠️  REDIS_URL не задан, пропускаем проверку Redis${NC}"
fi

# ----------------------------------------------------------------
# 7. Проверка вебхуков Telegram
# ----------------------------------------------------------------
echo -e "\n${GREEN}[7/10] Проверка вебхуков Telegram...${NC}"

if [ -n "$BOT_TOKEN" ]; then
    WEBHOOK_INFO=$(curl -s "https://api.telegram.org/bot${BOT_TOKEN}/getWebhookInfo")
    CURRENT_WEBHOOK_URL=$(echo "$WEBHOOK_INFO" | grep -o '"url":"[^"]*"' | cut -d '"' -f4)
    if [ -n "$CURRENT_WEBHOOK_URL" ] && [ "$CURRENT_WEBHOOK_URL" != "" ]; then
        echo -e "  ✅ Основной бот: вебхук установлен на $CURRENT_WEBHOOK_URL"
        # Проверяем, совпадает ли с ожидаемым
        if [ -n "$WEBHOOK_URL" ] && [ "$CURRENT_WEBHOOK_URL" != "$WEBHOOK_URL" ]; then
            echo -e "  ${YELLOW}⚠️  Ожидался вебхук: $WEBHOOK_URL${NC}"
        fi
    else
        echo -e "  ${RED}❌ Основной бот: вебхук НЕ установлен${NC}"
        HAS_ERROR=1
    fi
else
    echo -e "  ${YELLOW}⚠️  BOT_TOKEN не задан, пропускаем проверку вебхука основного бота${NC}"
fi

if [ -n "$ADMIN_BOT_TOKEN" ]; then
    ADMIN_WEBHOOK_INFO=$(curl -s "https://api.telegram.org/bot${ADMIN_BOT_TOKEN}/getWebhookInfo")
    ADMIN_CURRENT_WEBHOOK_URL=$(echo "$ADMIN_WEBHOOK_INFO" | grep -o '"url":"[^"]*"' | cut -d '"' -f4)
    if [ -n "$ADMIN_CURRENT_WEBHOOK_URL" ] && [ "$ADMIN_CURRENT_WEBHOOK_URL" != "" ]; then
        echo -e "  ✅ Админ-бот: вебхук установлен на $ADMIN_CURRENT_WEBHOOK_URL"
    else
        echo -e "  ${RED}❌ Админ-бот: вебхук НЕ установлен${NC}"
        HAS_ERROR=1
    fi
else
    echo -e "  ${YELLOW}⚠️  ADMIN_BOT_TOKEN не задан, пропускаем проверку вебхука админ-бота${NC}"
fi

# ----------------------------------------------------------------
# 8. Проверка внутреннего API (порт 8001)
# ----------------------------------------------------------------
echo -e "\n${GREEN}[8/10] Проверка внутреннего API (localhost:8001)...${NC}"
if [ "$IN_DOCKER" = true ]; then
    # внутри контейнера localhost работает
    INT_API_CHECK=$(docker exec "$CONTAINER_NAME" curl -s -o /dev/null -w "%{http_code}" http://localhost:8001/activate -X POST -H "Content-Type: application/json" -d '{}' --connect-timeout 3 2>/dev/null || echo "000")
else
    INT_API_CHECK=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8001/activate -X POST -H "Content-Type: application/json" -d '{}' --connect-timeout 3 2>/dev/null || echo "000")
fi
if [ "$INT_API_CHECK" = "401" ] || [ "$INT_API_CHECK" = "400" ]; then
    # 401 - unauthorized (ожидаемо, так как без токена), 400 - bad request, но сервер отвечает
    echo -e "  ✅ Внутреннее API доступно (HTTP $INT_API_CHECK - ожидаемо без авторизации)"
elif [ "$INT_API_CHECK" = "200" ]; then
    echo -e "  ✅ Внутреннее API доступно"
else
    echo -e "  ${RED}❌ Внутреннее API не отвечает (HTTP $INT_API_CHECK)${NC}"
    HAS_ERROR=1
fi

# ----------------------------------------------------------------
# 9. Проверка логов на наличие ошибок за последние 5 минут
# ----------------------------------------------------------------
echo -e "\n${GREEN}[9/10] Проверка логов на ошибки за последние 5 минут...${NC}"
if [ "$IN_DOCKER" = true ]; then
    LOG_ERRORS=$(docker logs --tail 500 "$CONTAINER_NAME" 2>&1 | grep -i -E "error|exception|traceback|critical" | tail -10)
else
    if [ -f logs/bot.log ]; then
        LOG_ERRORS=$(tail -500 logs/bot.log | grep -i -E "error|exception|traceback|critical" | tail -10)
    else
        LOG_ERRORS=""
    fi
fi

if [ -z "$LOG_ERRORS" ]; then
    echo -e "  ✅ Свежих ошибок в логах не обнаружено"
else
    echo -e "  ${YELLOW}⚠️  Найдены ошибки в логах (последние 10):${NC}"
    echo "$LOG_ERRORS" | sed 's/^/    /'
    # Не считаем за фатальную ошибку, но предупреждаем
fi

# ----------------------------------------------------------------
# 10. Опционально: отправка тестового сообщения боту (если указан TEST_CHAT_ID)
# ----------------------------------------------------------------
if [ -n "$TEST_CHAT_ID" ] && [ -n "$BOT_TOKEN" ]; then
    echo -e "\n${GREEN}[10/10] Отправка тестового сообщения боту...${NC}"
    SEND_RESULT=$(curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
        -d "chat_id=${TEST_CHAT_ID}" \
        -d "text=✅ Healthcheck: бот работает, $(date '+%Y-%m-%d %H:%M:%S')" \
        -d "parse_mode=HTML")
    if echo "$SEND_RESULT" | grep -q '"ok":true'; then
        echo -e "  ✅ Тестовое сообщение отправлено в чат $TEST_CHAT_ID"
    else
        echo -e "  ${RED}❌ Не удалось отправить сообщение боту. Проверьте BOT_TOKEN и TEST_CHAT_ID${NC}"
        echo "     Ответ: $SEND_RESULT"
        HAS_ERROR=1
    fi
elif [ -n "$TEST_CHAT_ID" ] && [ -z "$BOT_TOKEN" ]; then
    echo -e "\n${GREEN}[10/10] Отправка тестового сообщения...${NC}"
    echo -e "  ${YELLOW}⚠️  TEST_CHAT_ID указан, но BOT_TOKEN не задан. Пропускаем.${NC}"
else
    echo -e "\n${GREEN}[10/10] Отправка тестового сообщения...${NC}"
    echo -e "  ${YELLOW}⚠️  TEST_CHAT_ID не задан. Пропускаем отправку.${NC}"
fi

# ----------------------------------------------------------------
# ИТОГ
# ----------------------------------------------------------------
echo ""
echo "============================================================"
if [ $HAS_ERROR -eq 0 ]; then
    echo -e "${GREEN}✅✅✅ ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ УСПЕШНО ✅✅✅${NC}"
    echo -e "${GREEN}   Проект работает полностью и готов к деплою.${NC}"
    exit 0
else
    echo -e "${RED}❌❌❌ ОБНАРУЖЕНЫ ПРОБЛЕМЫ ❌❌❌${NC}"
    echo -e "${RED}   Проверьте вывод выше и устраните ошибки.${NC}"
    exit 1
fi