# ─────────────────────────────────────────────────────────────────────────────
# Stage 1: dependency builder
# Install packages into a prefix so the runtime image stays minimal.
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /install

COPY requirements.txt .

RUN pip install --no-cache-dir --prefix=/install/pkgs -r requirements.txt


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2: production runtime
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

LABEL org.opencontainers.image.title="Intelligent Observability & Event Watchdog" \
      org.opencontainers.image.description="Python/FastAPI log monitoring with anomaly detection" \
      org.opencontainers.image.version="1.0.0"

# ── Security: non-root user ──────────────────────────────────────────────────
RUN groupadd -r watchdog && \
    useradd  -r -g watchdog -d /app -s /sbin/nologin watchdog

# ── Runtime env ─────────────────────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PATH="/install/pkgs/bin:$PATH" \
    DB_PATH=/app/watchdog_data/watchdog.db \
    DATA_DIR=/app/data \
    LOG_LEVEL=INFO \
    PORT=8000 \
    WORKERS=1

WORKDIR /app

# ── Copy installed packages from builder ────────────────────────────────────
COPY --from=builder /install/pkgs /usr/local

# ── Copy application source ──────────────────────────────────────────────────
COPY --chown=watchdog:watchdog . .

# ── Create runtime directories ───────────────────────────────────────────────
RUN mkdir -p watchdog_data data static && \
    chown -R watchdog:watchdog /app

# ── Drop privileges ──────────────────────────────────────────────────────────
USER watchdog

EXPOSE 8000

# ── Health check ─────────────────────────────────────────────────────────────
# Uses only stdlib — no curl/wget needed in slim image.
HEALTHCHECK --interval=30s --timeout=10s --start-period=25s --retries=3 \
    CMD python -c \
        "import urllib.request, sys; \
         r = urllib.request.urlopen('http://localhost:8000/health', timeout=8); \
         sys.exit(0 if r.status == 200 else 1)" \
    || exit 1

# ── Entrypoint ────────────────────────────────────────────────────────────────
# Production: gunicorn manages the process lifecycle; uvicorn worker handles async.
# WORKERS=1 is intentional — SQLite WAL supports concurrent reads but serialises
# writes; a single worker avoids write-locking contention on the shared .db file.
CMD ["sh", "-c", \
     "gunicorn main:app \
      -k uvicorn.workers.UvicornWorker \
      -w ${WORKERS} \
      -b 0.0.0.0:${PORT} \
      --timeout 120 \
      --graceful-timeout 30 \
      --keep-alive 5 \
      --access-logfile - \
      --error-logfile - \
      --log-level ${LOG_LEVEL}"]
