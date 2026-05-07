# ── Whispy CDN Server ────────────────────────────────────────────────────────
# Multi-stage build: keeps final image lean (~120 MB).
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.12-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim

LABEL org.opencontainers.image.title="Whispy CDN Server"
LABEL org.opencontainers.image.description="PyPI package streaming CDN"
LABEL org.opencontainers.image.source="https://github.com/Dark-Avenger-Reborn/Whispy"
LABEL org.opencontainers.image.licenses="MIT"

# Non-root user for security
RUN groupadd -r whispy && useradd -r -g whispy -d /app whispy

WORKDIR /app

# Copy deps from builder
COPY --from=builder /install /usr/local

# Copy app
COPY app.py .

# Cache directory — mount a volume here in production
RUN mkdir -p /app/cache && chown -R whispy:whispy /app

USER whispy

# Environment defaults (override via docker run -e or compose)
ENV WHISPY_CACHE_DIR=/app/cache \
    WHISPY_MAX_CACHE_MB=4096 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# Gunicorn: 4 workers, 2 threads each, 120s timeout (package downloads can be slow)
CMD ["gunicorn", "app:app", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "4", \
     "--threads", "2", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--log-level", "info"]
