.PHONY: help install setup run dev test clean lint docker-build docker-run deploy

help:
	@echo "Smeta AI - Помощь"
	@echo ""
	@echo "Команды:"
	@echo "  make install       - Установка зависимостей"
	@echo "  make setup         - Полная инициализация проекта"
	@echo "  make run           - Запуск сервера в production"
	@echo "  make dev           - Запуск сервера в dev режиме с hot-reload"
	@echo "  make db-init       - Инициализация базы данных"
	@echo "  make pricelists    - Создание примеров прайс-листов"
	@echo "  make clean         - Удаление временных файлов"
	@echo "  make test          - Запуск тестов"
	@echo "  make lint          - Проверка кода"
	@echo ""

install:
	pip install -r backend/requirements.txt

setup: install db-init pricelists
	@echo "✓ Проект инициализирован"

db-init:
	python backend/database.py

pricelists:
	python init_pricelists.py

run:
	cd backend && python -m uvicorn main:app --host 0.0.0.0 --port 8000

dev:
	cd backend && python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	rm -rf build dist *.egg-info
	rm -rf /tmp/smeta_ai_results

lint:
	flake8 backend --max-line-length=120

test:
	pytest tests/ -v

docker-build:
	docker build -t smeta-ai:latest .

docker-run:
	docker run -p 8000:8000 --env-file .env smeta-ai:latest

.DEFAULT_GOAL := help
