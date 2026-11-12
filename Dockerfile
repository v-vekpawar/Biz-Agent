FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application, migrations and the bundled frontend (served by the API at /app)
COPY backend/alembic.ini ./backend/alembic.ini
COPY backend/alembic ./backend/alembic
COPY backend/app ./backend/app
COPY frontend ./frontend

WORKDIR /srv/backend
RUN useradd --create-home appuser && mkdir -p /data && chown -R appuser /data
USER appuser

# SQLite lives on a mounted volume by default; set DATABASE_URL for Postgres.
ENV DATABASE_URL=sqlite:////data/bizagent.db \
    BIZAGENT_ENV=production \
    BIZAGENT_UPLOADS_DIR=/data/uploads \
    PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os,urllib.request as u; u.urlopen('http://localhost:%s/health' % os.environ.get('PORT','8000'))" || exit 1

# Migrations run at startup (BIZAGENT_AUTO_MIGRATE=1 by default).
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
