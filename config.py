import os
from dotenv import load_dotenv

# Загружаем переменные из .env файла
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise ValueError("Не найден BOT_TOKEN в окружении. Укажите его в файле .env")
