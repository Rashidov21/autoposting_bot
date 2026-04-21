# Loyiha ildizidan ishga tushiring (Windowsda Git Bash / WSL yoki qo'lda buyruqlar)

.PHONY: install init-db test run-api run-worker run-worker-aux run-beat run-bot docker-up docker-down docker-logs

install:
	pip install -r requirements.txt

init-db:
	python -m scripts.init_db

test:
	pytest -q

run-api:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Docker dagi ``worker_campaign`` bilan bir xil navbat (campaign)
run-worker:
	celery -A worker.celery_app:celery_app worker -l info -Q campaign -c 2 --prefetch-multiplier=1 --max-tasks-per-child=30 --max-memory-per-child=450000

run-worker-aux:
	celery -A worker.celery_app:celery_app worker -l info -Q default,scheduler -c 1 --prefetch-multiplier=1 --max-tasks-per-child=30 --max-memory-per-child=450000

run-beat:
	celery -A worker.celery_app:celery_app beat -l info

run-bot:
	python -m bot.main

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f
