#!/bin/bash
# start_server.sh - автоматический деплой на продакшен-сервер
set -e

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}🚀 Автоматический деплой NeuroPrompt Premium на сервер${NC}"

# Проверка, что скрипт запущен с sudo/root
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}❌ Скрипт должен запускаться от root (используйте sudo).${NC}" 
   exit 1
fi

# Запрос домена
read -p "🔗 Введите ваш домен (например, api.example.com): " DOMAIN
if [[ -z "$DOMAIN" ]]; then
    echo -e "${RED}❌ Домен не может быть пустым.${NC}"
    exit 1
fi

# Проверка наличия .env
if [ ! -f .env ]; then
    echo -e "${RED}❌ Файл .env не найден в текущей папке.${NC}"
    echo -e "Создайте .env со следующими обязательными переменными:"
    echo -e "  BOT_TOKEN, ADMIN_BOT_TOKEN, ADMIN_CHAT_ID, SECRET_KEY, ENCRYPTION_KEY,"
    echo -e "  INTERNAL_API_SECRET, WEBHOOK_SECRET, ADMIN_WEBHOOK_SECRET,"
    echo -e "  YOOKASSA_SHOP_ID, YOOKASSA_API_KEY, DATABASE_URL"
    exit 1
fi

# Добавляем DOMAIN в .env, если его там нет
if ! grep -q "^DOMAIN=" .env; then
    echo "DOMAIN=${DOMAIN}" >> .env
else
    sed -i "s/^DOMAIN=.*/DOMAIN=${DOMAIN}/" .env
fi

# Устанавливаем Docker, если не установлен
if ! command -v docker &> /dev/null; then
    echo -e "${GREEN}📦 Установка Docker...${NC}"
    curl -fsSL https://get.docker.com -o get-docker.sh
    sh get-docker.sh
    systemctl enable docker
    rm get-docker.sh
fi

# Устанавливаем Docker Compose (плагин), если не установлен
if ! command -v docker-compose &> /dev/null; then
    echo -e "${GREEN}📦 Установка Docker Compose...${NC}"
    curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
fi

# Останавливаем старые контейнеры (если есть)
docker-compose -f docker-compose.prod.yml down --remove-orphans 2>/dev/null || true

# Запускаем сборку и контейнеры
echo -e "${GREEN}🐳 Сборка и запуск контейнеров (это займёт некоторое время)...${NC}"
docker-compose -f docker-compose.prod.yml up -d --build

# Ждём, пока acme-companion получит сертификат (до 90 секунд)
echo -e "${GREEN}⏳ Ожидание получения SSL-сертификата...${NC}"
for i in {1..18}; do
    if docker logs acme-companion 2>&1 | grep -q "Certificate obtained"; then
        echo -e "${GREEN}✅ SSL-сертификат успешно получен!${NC}"
        break
    fi
    sleep 5
done

# Устанавливаем вебхук для основного бота
BOT_TOKEN=$(grep -E '^BOT_TOKEN=' .env | cut -d '=' -f2-)
if [[ -n "$BOT_TOKEN" ]]; then
    echo -e "${GREEN}🔗 Установка вебхука для основного бота...${NC}"
    curl -s -F "url=https://${DOMAIN}/webhook" "https://api.telegram.org/bot${BOT_TOKEN}/setWebhook" | grep -q '"ok":true' && echo "   ✅ Вебхук установлен" || echo "   ⚠️ Ошибка установки вебхука"
fi

# Устанавливаем вебхук для админ-бота
ADMIN_BOT_TOKEN=$(grep -E '^ADMIN_BOT_TOKEN=' .env | cut -d '=' -f2-)
if [[ -n "$ADMIN_BOT_TOKEN" ]]; then
    echo -e "${GREEN}🔗 Установка вебхука для админ-бота...${NC}"
    curl -s -F "url=https://${DOMAIN}/webhook/admin" "https://api.telegram.org/bot${ADMIN_BOT_TOKEN}/setWebhook" | grep -q '"ok":true' && echo "   ✅ Вебхук установлен" || echo "   ⚠️ Ошибка установки вебхука"
fi

# Вывод информации
echo -e "${GREEN}✅ Деплой завершён!${NC}"
echo -e "   🌐 Сайт: https://${DOMAIN}"
echo -e "   🤖 Бот должен отвечать на команды."
echo -e "   📋 Логи: docker-compose -f docker-compose.prod.yml logs -f app"
echo -e "   🛑 Остановка: docker-compose -f docker-compose.prod.yml down"