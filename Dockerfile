FROM python:3.11-slim

# Установка системных зависимостей (curl для healthcheck, netcat для проверки БД)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем только requirements сначала (для кэширования слоёв)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь проект
COPY . .

# Создаём непривилегированного пользователя
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Команда запуска (используем run_all.py, который поднимает и бота, и веб)
CMD ["python", "run_all.py"]