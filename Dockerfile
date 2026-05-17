FROM python:3.11-slim

WORKDIR /app

# Установка системных зависимостей (для bcrypt, cryptography и др.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Копируем requirements и устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь проект
COPY . .

# Открываем порты: 8000 (веб), 8001 (внутренний API)
EXPOSE 8000 8001

# Запуск единой точки входа (бота + веб + internal API)
CMD ["python", "run_all.py"]