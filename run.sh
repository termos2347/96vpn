#!/bin/bash
# Останавливаем старые процессы
pkill -f "python run_all.py"   # убить старый бот, если есть
pkill -f "localtunnel"         # убить старый туннель, если есть
sleep 1

# Активируем виртуальное окружение
source .venv/bin/activate

# Запускаем бота в фоне и туннель (или в одном терминале)
python run_all.py &
npx localtunnel --port 5001 --subdomain my-testй