#!/bin/bash
set -e

REPO_URL="https://github.com/termos2347/96vpn.git"
BRANCH="no-site"
PROJECT_DIR="96vpn"

echo "=== 96VPN Bot (no-site branch) - Deployment with external DB ==="

# -------------------- 1. Получение кода --------------------
if [ -f "run_all.py" ] && [ -f ".env" ]; then
    echo "Already in project directory (run_all.py and .env found). Skipping clone."
else
    if [ -d "$PROJECT_DIR" ]; then
        echo "Directory $PROJECT_DIR exists. Pulling latest changes..."
        cd "$PROJECT_DIR"
        git pull origin "$BRANCH"
        cd ..
    else
        echo "Cloning repository (branch $BRANCH)..."
        git clone --branch "$BRANCH" "$REPO_URL"
    fi
    cd "$PROJECT_DIR"
fi

# -------------------- 2. Определение ОС --------------------
if [ -f /etc/fedora-release ]; then
    PKG_MANAGER="dnf"
elif [ -f /etc/redhat-release ]; then
    PKG_MANAGER="yum"
else
    echo "Unsupported OS. Only Fedora/RHEL are supported."
    exit 1
fi

# -------------------- 3. Установка системных зависимостей --------------------
echo "Installing system dependencies..."
sudo $PKG_MANAGER install -y python3 python3-pip python3-virtualenv libpq-devel gcc git

# -------------------- 4. (Опционально) Cloudflared для вебхуков --------------------
if ! command -v cloudflared &> /dev/null; then
    echo "Installing cloudflared..."
    sudo dnf install -y cloudflared || {
        sudo dnf copr enable -y medzik/cloudflared
        sudo dnf install -y cloudflared
    }
fi

# -------------------- 5. Виртуальное окружение и зависимости --------------------
echo "Creating virtual environment..."
virtualenv -p python3 .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

# -------------------- 6. Миграции (на внешней БД) --------------------
echo "Running Alembic migrations on external database..."
alembic upgrade head

# -------------------- 7. Systemd сервис --------------------
echo "Creating systemd service..."
USER=$(whoami)
WORKDIR=$(pwd)
cat > /tmp/vpn-bot.service <<EOF
[Unit]
Description=96VPN Bot (no-site, external DB)
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$WORKDIR
Environment="PATH=$WORKDIR/.venv/bin"
ExecStart=$WORKDIR/.venv/bin/python $WORKDIR/run_all.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
sudo mv /tmp/vpn-bot.service /etc/systemd/system/vpn-bot.service
sudo systemctl daemon-reload
sudo systemctl enable vpn-bot
sudo systemctl start vpn-bot

# -------------------- 8. Запуск туннеля (если нужен) --------------------
if ! grep -q "^WEBHOOK_URL=" .env || [ -z "$(grep "^WEBHOOK_URL=" .env | cut -d '=' -f2)" ]; then
    echo "WEBHOOK_URL not set. Starting cloudflared tunnel in background..."
    nohup cloudflared tunnel --url http://localhost:8001 > cloudflared.log 2>&1 &
    echo "Tunnel started. Check cloudflared.log for URL. Then update .env and restart bot."
fi

echo "=== Deployment finished ==="
echo "Bot is running as service. Check status: sudo systemctl status vpn-bot"
echo "Logs: journalctl -u vpn-bot -f"