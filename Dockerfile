FROM python:3.12-slim

WORKDIR /app
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# VPS da ba'zan PyPI/SSL yoki eski pip sabab ``from versions: none`` xatosi chiqadi.
RUN pip install --upgrade pip setuptools wheel \
    && pip install --no-cache-dir --retries 10 --timeout 120 \
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
