#!/bin/bash

echo "🛑 Stopping old bot process..."
pkill -f "python run_all.py" 2>/dev/null
sleep 1

echo "🔓 Freeing port 5001 (if occupied)..."
fuser -k 5001/tcp 2>/dev/null
lsof -t -i:5001 | xargs kill -9 2>/dev/null
sleep 1

source .venv/bin/activate

echo "🚀 Starting bot..."
python run_all.py &
BOT_PID=$!
echo "Bot PID: $BOT_PID"

# Ждём инициализации (опционально)
sleep 2
echo "✅ Bot started. Logs appear in the terminal. Press Ctrl+C to stop."

# Ждём завершения бота
wait $BOT_PID