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

# Валидация XUI настроек
XUI_BASE_URL = os.getenv("XUI_BASE_URL")
XUI_USERNAME = os.getenv("XUI_USERNAME")
XUI_PASSWORD = os.getenv("XUI_PASSWORD")
XUI_INBOUND_ID = os.getenv("XUI_INBOUND_ID")
XUI_SUB_PORT = os.getenv("XUI_SUB_PORT")

if not all([XUI_BASE_URL, XUI_USERNAME, XUI_PASSWORD, XUI_INBOUND_ID, XUI_SUB_PORT]):
    raise ValueError("Не все переменные XUI настроены в .env файле")

try:
    XUI_INBOUND_ID = int(XUI_INBOUND_ID)
    XUI_SUB_PORT = int(XUI_SUB_PORT)
except ValueError:
    raise ValueError("XUI_INBOUND_ID и XUI_SUB_PORT должны быть числами")

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