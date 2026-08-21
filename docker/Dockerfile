FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# non-root
RUN groupadd -r tglink && useradd -r -g tglink -d /app tglink

COPY --chown=tglink:tglink pyproject.toml README.md ./
COPY --chown=tglink:tglink src ./src

RUN pip install .

# data dir for SQLite + cache (volume target)
RUN mkdir -p /app/data /app/secrets && chown -R tglink:tglink /app/data /app/secrets
VOLUME ["/app/data", "/app/secrets"]

USER tglink
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz')"

CMD ["uvicorn", "tglink.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]