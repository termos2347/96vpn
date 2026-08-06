#!/bin/bash

echo "Stopping old bot process..."
pkill -f "python run_all.py" 2>/dev/null
sleep 1

echo "Freeing port 5001 (if occupied)..."

if command -v fuser &> /dev/null; then
    fuser -k 5001/tcp 2>/dev/null
fi

if lsof -i:5001 >/dev/null 2>&1; then
    echo "Port still in use, trying with sudo..."
    sudo lsof -t -i:5001 | xargs sudo kill -9 2>/dev/null
fi

sleep 2

if lsof -i:5001 >/dev/null 2>&1; then
    echo "Port 5001 is still occupied. Please free it manually."
    exit 1
else
    echo "Port 5001 is free."
fi

source .venv/bin/activate

echo "Starting bot..."
exec python run_all.py