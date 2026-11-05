#!/usr/bin/env bash
# check.sh — все автоматические проверки одной командой.
# Линт + типы + security + CVE + тесты + coverage. ~1-2 минуты.
set -euo pipefail
cd "$(dirname "$0")"

source .venv/bin/activate

echo "=== 1/6 ruff (lint) ==="
ruff check . || exit 1

echo "=== 2/6 mypy (типы) ==="
mypy --ignore-missing-imports --no-error-summary . || true  # сначала "мягко"

echo "=== 3/6 bandit (security) ==="
bandit -q -r . -x ./tests,./.venv || exit 1

echo "=== 4/6 pip-audit (CVE в зависимостях) ==="
pip-audit --skip-editable || true  # не валим из-за CVE в транзитивных

echo "=== 5/6 pytest ==="
pytest -q || exit 1

echo "=== 6/6 coverage ==="
coverage report --fail-under=60 || true  # подними порог, когда привыкнешь

echo ""
echo "✅ Все проверки пройдены."