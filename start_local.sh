#!/bin/bash
# start_local.sh - запуск проекта локально (разработка)
set -e

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}🚀 Запуск NeuroPrompt Premium в локальном режиме...${NC}"

# Проверяем наличие .env
if [ ! -f .env ]; then
    echo -e "${RED}❌ Файл .env не найден. Скопируйте .env.example и настройте переменные.${NC}"
    exit 1
fi

# Проверяем, что docker и docker-compose установлены
if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ Docker не установлен. Установите Docker Desktop.${NC}"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo -e "${RED}❌ docker-compose не найден. Установите Docker Compose.${NC}"
    exit 1
fi

# Останавливаем старые контейнеры, если есть
docker-compose down --remove-orphans 2>/dev/null || true

# Собираем и запускаем
echo -e "${GREEN}🐳 Сборка и запуск контейнеров...${NC}"
docker-compose up -d --build

echo -e "${GREEN}✅ Локальный запуск выполнен.${NC}"
echo -e "   🌐 Сайт: http://localhost:8000"
echo -e "   🤖 Бот будет работать только если настроен публичный вебхук (ngrok или реальный домен)."
echo -e "   📋 Логи: docker-compose logs -f app"