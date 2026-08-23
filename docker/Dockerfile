FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# non-root
RUN groupadd -r anbar && useradd -r -g anbar -d /app anbar

COPY --chown=anbar:anbar pyproject.toml README.md ./
COPY --chown=anbar:anbar src ./src

RUN pip install .

# data dir for SQLite + cache (volume target)
RUN mkdir -p /app/data /app/secrets && chown -R anbar:anbar /app/data /app/secrets
VOLUME ["/app/data", "/app/secrets"]

USER anbar
EXPOSE 8567

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8567/healthz')"

CMD ["uvicorn", "anbar.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8567"]