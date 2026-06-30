#!/bin/bash

echo "Stopping old bot process..."
pkill -f "python run_all.py" 2>/dev/null
sleep 1

echo "Freeing port 5001 (if occupied)..."

# Попытка через fuser (без sudo)
if command -v fuser &> /dev/null; then
    fuser -k 5001/tcp 2>/dev/null
fi

# Если порт всё ещё занят — используем sudo lsof
if lsof -i:5001 >/dev/null 2>&1; then
    echo "Port still in use, trying with sudo..."
    # Находим PID процесса, слушающего порт, и убиваем
    sudo lsof -t -i:5001 | xargs sudo kill -9 2>/dev/null
fi

sleep 2

# Финальная проверка
if lsof -i:5001 >/dev/null 2>&1; then
    echo "Port 5001 is still occupied. Please free it manually."
    exit 1
else
    echo " Port 5001 is free."
fi

# Активация виртуального окружения
source .venv/bin/activate

echo "Starting bot..."
python run_all.py &
BOT_PID=$!
echo "Bot PID: $BOT_PID"

# Небольшая пауза для инициализации
sleep 2
echo "Bot started. Logs appear in the terminal. Press Ctrl+C to stop."

# Ожидание завершения бота
wait $BOT_PID