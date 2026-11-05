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
    echo "   И заполните обязательные переменные (см. .env.example)." >&2
    exit 1
fi

# 1a. Проверяем, что ключевые переменные заданы.
_missing=()
for var in \
    BOT_TOKEN ADMIN_BOT_TOKEN ADMIN_CHAT_ID \
    ENCRYPTION_KEY INTERNAL_API_SECRET \
    DATABASE_URL \
    WEBHOOK_URL WEBHOOK_SECRET ADMIN_WEBHOOK_URL ADMIN_WEBHOOK_SECRET \
    YOOKASSA_SHOP_ID YOOKASSA_API_KEY YOOKASSA_TRUSTED_IPS \
    XUI_MASTER_URL XUI_API_TOKEN XUI_INBOUND_ID XUI_SUB_PORT; do
    if ! grep -qE "^${var}=.+" .env; then
        _missing+=("$var")
    fi
done
if [ ${#_missing[@]} -gt 0 ]; then
    echo "❌ В .env не заданы обязательные переменные:" >&2
    printf '   - %s\n' "${_missing[@]}" >&2
    exit 1
fi

# 1b. Порт берём из .env (INTERNAL_API_PORT), fallback — 5001
PORT=5001
_env_port=$(grep -E '^INTERNAL_API_PORT=' .env 2>/dev/null | head -n1 | cut -d'=' -f2- | tr -d ' "\r\n' || true)
if [ -n "${_env_port:-}" ]; then
    PORT="$_env_port"
fi

# 1c. PRE-FLIGHT: конфигурация YooKassa IP-фильтра и прокси.
_debug_val=$(grep -E '^DEBUG=' .env 2>/dev/null | head -n1 | cut -d'=' -f2- | tr -d ' "\r\n' | tr '[:upper:]' '[:lower:]' || true)
_debug_lc="${_debug_val:-false}"

_proxy_val=$(grep -E '^TRUSTED_PROXY_IPS=' .env 2>/dev/null | head -n1 | cut -d'=' -f2- || true)
_proxy_trim=$(printf '%s' "${_proxy_val:-}" | tr -d ' \t\r\n')

# _proxy_is_empty=true, если значение пустое или "[]".
_proxy_is_empty=false
if [ -z "$_proxy_trim" ]; then
    _proxy_is_empty=true
elif [ "$_proxy_trim" = "[]" ]; then
    _proxy_is_empty=true
fi

if [ "$_debug_lc" != "true" ] && [ "$_proxy_is_empty" = "true" ]; then
    echo "⚠️  ВНИМАНИЕ: TRUSTED_PROXY_IPS пуст при DEBUG=false." >&2
    echo "   Если перед ботом стоит reverse proxy (nginx/caddy) —" >&2
    echo "   X-Real-IP приниматься НЕ будет, и ВСЕ вебхуки ЮKassa" >&2
    echo "   получат 403. Добавьте CIDR прокси в TRUSTED_PROXY_IPS (.env)," >&2
    echo "   например:  TRUSTED_PROXY_IPS=[\"127.0.0.1/32\"]" >&2
    echo "" >&2
fi

if [ "$_debug_lc" != "true" ] && [ "$_proxy_is_empty" = "true" ]; then
    if [ -f "yookassa_ip.json" ] && grep -qE '"(::1|127\.[0-9]+\.[0-9]+\.[0-9]+)"' yookassa_ip.json 2>/dev/null; then
        echo "⚠️  ВНИМАНИЕ: yookassa_ip.json содержит loopback (127.0.0.1 / ::1)," >&2
        echo "   а TRUSTED_PROXY_IPS пуст при DEBUG=false." >&2
        echo "" >&2
        echo "   config.py при старте отфильтрует loopback из YOOKASSA_TRUSTED_IPS." >&2
        echo "   Если loopback — единственный IP в файле, бот НЕ СТАРТУЕТ." >&2
        echo "" >&2
        echo "   Варианты:" >&2
        echo "   1) Удалите loopback из yookassa_ip.json (продакшен)." >&2
        echo "   2) Задайте TRUSTED_PROXY_IPS (CIDR вашего nginx) в .env." >&2
        echo "   3) Для localtunnel-отладки выставьте DEBUG=true в .env." >&2
        echo "" >&2
    fi
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

# 4. Останавливаем старый процесс
PROC_PATTERN="python[0-9.]* .*${ENTRYPOINT}"
if pgrep -f "$PROC_PATTERN" >/dev/null 2>&1; then
    echo "⏹  Останавливаем старый процесс ($ENTRYPOINT)..."
    pkill -f "$PROC_PATTERN" 2>/dev/null || true
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        pgrep -f "$PROC_PATTERN" >/dev/null 2>&1 || break
        sleep 0.5
    done
    if pgrep -f "$PROC_PATTERN" >/dev/null 2>&1; then
        echo "⚠️  Процесс не завершился — SIGKILL..."
        pkill -9 -f "$PROC_PATTERN" 2>/dev/null || true
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
                if lsof -ti:"$PORT" >/dev/null 2>&1; then
                    echo "❌ Не удалось освободить порт $PORT (нужны права root)." >&2
                    echo "   Выполните вручную: sudo kill -9 $pids" >&2
                    exit 1
                fi
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