#!/bin/bash
# Простой запуск бота без туннеля

echo "🛑 Stopping old bot process..."
pkill -f "python run_all.py" 2>/dev/null
sleep 1

# Принудительно освобождаем порт 5001 (на случай, если висит)
echo "🔓 Freeing port 5001..."
fuser -k 5001/tcp 2>/dev/null
sleep 1

# Активируем виртуальное окружение
source .venv/bin/activate

# Запускаем бота в фоне
echo "🚀 Starting bot..."
python run_all.py &
BOT_PID=$!
echo "Bot PID: $BOT_PID"

# Небольшая пауза, чтобы бот успел инициализироваться
sleep 2
echo "✅ Bot started. Logs appear in the terminal. Press Ctrl+C to stop."

# Ожидаем завершения бота (позволяет Ctrl+C передать сигнал процессу)
wait $BOT_PID