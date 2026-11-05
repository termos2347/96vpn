#!/usr/bin/env bash
# start.sh — запускает проект: проверки, остановка старого процесса,
#            освобождение порта, активация venv, exec python
set -euo pipefail

cd "$(dirname "$0")"

ENTRYPOINT="run_all.py"

# 1. Проверяем .env
if [ ! -f ".env" ]; then
    echo "❌ Файл .env не найден." >&2
    echo "   Скопируйте шаблон:  cp .env.example .env" >&2
    echo "   И заполните SECRET_KEY и ADMIN_PASSWORD." >&2
    exit 1
fi

# 1b. Порт берём из .env (INTERNAL_API_PORT), fallback — 5001
PORT=5001
_env_port=$(grep -E '^INTERNAL_API_PORT=' .env 2>/dev/null | head -n1 | cut -d'=' -f2 | tr -d ' "\'" || true)
if [ -n "${_env_port:-}" ]; then
    PORT="$_env_port"
fi

# 2. Проверяем .venv
if [ ! -d ".venv" ] || [ ! -f ".venv/bin/activate" ]; then
    echo "❌ Виртуальное окружение .venv не найдено или повреждено." >&2
    echo "   Выполните: ./install.sh" >&2
    exit 1
fi

# 3. Проверяем точку входа
if [ ! -f "$ENTRYPOINT" ]; then
    echo "❌ Не найден $ENTRYPOINT в $(pwd)" >&2
    exit 1
fi

# 4. Останавливаем старый процесс (если запущен)
if pgrep -f "$ENTRYPOINT" >/dev/null 2>&1; then
    echo "⏹  Останавливаем старый процесс ($ENTRYPOINT)..."
    pkill -f "$ENTRYPOINT" 2>/dev/null || true
    for _ in {1..10}; do
        pgrep -f "$ENTRYPOINT" >/dev/null 2>&1 || break
        sleep 0.5
    done
    if pgrep -f "$ENTRYPOINT" >/dev/null 2>&1; then
        echo "⚠️  Процесс не завершился — SIGKILL..."
        pkill -9 -f "$ENTRYPOINT" 2>/dev/null || true
        sleep 0.5
    fi
fi

# 5. Освобождаем порт
if command -v lsof >/dev/null 2>&1; then
    if lsof -ti:"$PORT" >/dev/null 2>&1; then
        pids=$(lsof -ti:"$PORT" 2>/dev/null || true)
        if [ -n "$pids" ]; then
            echo "🔌 Освобождаем порт $PORT (PID: $pids)..."
            if ! echo "$pids" | xargs -r kill -9 2>/dev/null; then
                echo "❌ Не удалось освободить порт $PORT (нужны права root)." >&2
                echo "   Выполните вручную: sudo kill -9 $pids" >&2
                exit 1
            fi
            sleep 1
        fi
    fi

    if lsof -ti:"$PORT" >/dev/null 2>&1; then
        echo "❌ Порт $PORT всё ещё занят. Освободите его вручную:" >&2
        lsof -i:"$PORT" >&2 || true
        exit 1
    fi
else
    echo "⚠️  Утилита lsof не найдена — пропускаю проверку порта $PORT." >&2
    echo "   Если порт занят, бот упадёт на bind(). Установите lsof: apt install lsof" >&2
fi

# 6. Активируем venv
# shellcheck disable=SC1091
source .venv/bin/activate

# 7. Небольшая диагностика
echo "=== Запуск проекта ==="
echo "Python:  $(python --version 2>&1)  ($(command -v python))"
echo "Каталог: $(pwd)"
echo "Порт:    $PORT"
echo ""

# 8. exec — корректно передаёт сигналы (Ctrl+C, SIGTERM) приложению
exec python "$ENTRYPOINT"