# ``# syntax=docker/dockerfile:1`` + ``--mount=cache`` Docker Hub dan ``docker/dockerfile``
# yuklaydi — ba'zi VPS larda juda sekin. Oddiy Dockerfile.
FROM python:3.12-slim-bookworm

WORKDIR /app
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PIP_DEFAULT_TIMEOUT=600

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --retries 25 --timeout 600 \
        --trusted-host pypi.org --trusted-host files.pythonhosted.org \
        -r requirements.txt

COPY app app
COPY bot bot
COPY worker worker
COPY engine engine
COPY scripts scripts
COPY schema.sql schema.sql

RUN mkdir -p /app/sessions \
    && groupadd -r appuser \
    && useradd -r -g appuser -d /app -s /sbin/nologin appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
