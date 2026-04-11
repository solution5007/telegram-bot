FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Сделаем рабочую папку /app, чтобы не путаться с папкой бота
WORKDIR /app

# Копируем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем ВЕСЬ проект (включая папку app и файлы в корне)
COPY . .

# Создаем папку /bot, которую так хочет твой код для базы данных
RUN mkdir -p /bot

# Запускаем из корня /app
CMD ["python", "-m", "app"]