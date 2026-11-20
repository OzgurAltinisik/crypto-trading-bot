# One image for both the engine and the web dashboard.
#   docker compose up -d --build      (see docker-compose.yml)

# --- 1. build the React frontend -------------------------------------------
FROM node:22-slim AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# vite writes to ../cryptobot/web/dist
RUN npm run build

# --- 2. python runtime ------------------------------------------------------
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY cryptobot/ cryptobot/
COPY config/ config/
COPY --from=web /app/cryptobot/web/dist cryptobot/web/dist

# run as an unprivileged user; ./data on the host must be writable by uid 1000
RUN useradd --uid 1000 --create-home bot && mkdir -p data && chown bot:bot data
USER bot

VOLUME ["/app/data"]
CMD ["python", "-m", "cryptobot", "run"]
