import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN не найден в .env файле")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL не найден в .env файле")

PROXY_URL = os.getenv("PROXY_URL")

ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(","))) if os.getenv("ADMIN_IDS") else []

# ---------- Цены на подписки ----------
# VPN: ключ - валюта, значение - словарь {период: цена}
VPN_PRICES = {
    "rub": {"1m": 300, "3m": 800, "6m": 1400},
    "stars": {"1m": 150, "3m": 400, "6m": 700},
    "usdt": {"1m": 3.5, "3m": 9.0, "6m": 16.0},
}
BYPASS_PRICES = {
    "rub": {"1m": 150, "3m": 400},
    "stars": {"1m": 75, "3m": 200},
    "usdt": {"1m": 2.0, "3m": 4.5},
}