FROM python:3.12-slim-bookworm

ARG APP_VERSION=dev
ARG APP_COMMIT=unknown
ENV APP_VERSION=${APP_VERSION} \
    APP_COMMIT=${APP_COMMIT} \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp/optixjp-home \
    XDG_CACHE_HOME=/tmp/optixjp-cache

WORKDIR /app

COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

RUN groupadd --system app && useradd --system --gid app --home /tmp/optixjp-home app \
    && install -d -o app -g app -m 0700 /data

COPY backend/app /app/app
COPY config/personal.toml /app/config/personal.toml
COPY frontend /app/frontend

ENV FRONTEND_DIR=/app/frontend
USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3).status==200 else 1)"

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers", "--no-server-header"]
