FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

# The app runs as a non-root user; /data is the only writable place (SQLite when no DATABASE_URL is given).
# A named volume mounted on /data inherits this ownership on first use.
RUN useradd --create-home appuser && mkdir -p /data && chown appuser:appuser /data
ENV DATABASE_URL=sqlite:////data/mockmate.db
USER appuser

# Hosts such as Render set $PORT; locally it defaults to 8000. Migrations run on start-up.
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
