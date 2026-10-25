FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config ./config
COPY backend ./backend

RUN useradd --create-home --uid 10001 stormhaven \
    && mkdir -p /app/data/processed /app/logs \
    && chown -R stormhaven:stormhaven /app

USER stormhaven

EXPOSE 8000

CMD ["sh", "-c", "python -m app.startup && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
