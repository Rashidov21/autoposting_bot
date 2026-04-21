# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
# Sekan VPS larda PyPI dan o'qish vaqt tugashi
ENV PIP_DEFAULT_TIMEOUT=600

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# ``pip upgrade`` qo'shilmaydi — sekan kanalda qo'shimcha yuklash vaqt tugashiga olib keladi.
# BuildKit keshi qayta ``docker compose build`` da yuklashni tezlashtiradi.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --retries 25 --timeout 600 \
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
