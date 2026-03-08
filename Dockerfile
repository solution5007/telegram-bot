FROM python:3.12-slim

# Не буферизовать stdout/stderr — логи сразу попадают в docker logs
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /bot

# Сначала копируем requirements — кэшируем слой с зависимостями
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем исходники
COPY app/ app/

# Том для SQLite базы
VOLUME ["/data"]

CMD ["python", "-m", "app"]
