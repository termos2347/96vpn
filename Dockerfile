FROM python:3.11-slim

WORKDIR /app

# Установка системных зависимотей (gcc, libpq-dev, curl для healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Копируем зависимости и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь проект
COPY . .

# Создаём папку для логов
RUN mkdir -p /app/logs

# Переменная для вывода логов без буферизации
ENV PYTHONUNBUFFERED=1

# Команда по умолчанию (запуск основного приложения)
CMD ["python", "run_all.py"]