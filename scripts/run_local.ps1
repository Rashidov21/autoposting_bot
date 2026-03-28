# Loyiha ildizida ishga tushiring. Har bir qatorni alohida PowerShell oynasida yoki Start-Process bilan ishga tushiring.
# Talab: .env, PostgreSQL, Redis, pip install -r requirements.txt, python -m scripts.init_db

Write-Host "1) API:    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
Write-Host "2) Worker: celery -A worker.celery_app:celery_app worker -l info"
Write-Host "3) Beat:   celery -A worker.celery_app:celery_app beat -l info"
Write-Host "4) Bot:    python -m bot.main"
