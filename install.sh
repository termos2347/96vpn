#!/usr/bin/env bash
# install.sh — создаёт .venv и ставит зависимости
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON_BIN:-}"
if [ -z "$PYTHON" ]; then
    if [ -x /usr/bin/python3 ]; then PYTHON=/usr/bin/python3; else PYTHON=python3; fi
fi

if ! "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
    echo "❌ Требуется Python 3.10+, найден $("$PYTHON" --version 2>&1)" >&2
    exit 1
fi
echo "Python: $("$PYTHON" --version 2>&1) ($(command -v "$PYTHON"))"

[ -d .venv ] || "$PYTHON" -m venv .venv
source .venv/bin/activate

pip install --upgrade pip >/dev/null
pip install -r requirements.txt

echo "✅ Готово. Запуск: ./start.sh"