#!/bin/bash
# Скрипт для быстрого старта Smeta AI в локальной среде

set -e

echo "🚀 Smeta AI - Скрипт быстрого старта"
echo "======================================"
echo ""

# Цвета для вывода
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Проверка Python
echo -e "${BLUE}→ Проверка Python...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${YELLOW}⚠ Python 3 не найден. Пожалуйста, установите Python 3.9+${NC}"
    exit 1
fi
PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
echo -e "${GREEN}✓ Python ${PYTHON_VERSION} найден${NC}"
echo ""

# Проверка pip
echo -e "${BLUE}→ Проверка pip...${NC}"
if ! command -v pip3 &> /dev/null; then
    echo -e "${YELLOW}⚠ pip3 не найден${NC}"
    exit 1
fi
echo -e "${GREEN}✓ pip3 найден${NC}"
echo ""

# Создание виртуального окружения (опционально)
if [ ! -d "venv" ]; then
    echo -e "${BLUE}→ Создание виртуального окружения...${NC}"
    python3 -m venv venv
    echo -e "${GREEN}✓ Виртуальное окружение создано${NC}"
    echo ""
fi

# Активация виртуального окружения
echo -e "${BLUE}→ Активация виртуального окружения...${NC}"
source venv/bin/activate 2>/dev/null || . venv/Scripts/activate 2>/dev/null || true
echo -e "${GREEN}✓ Виртуальное окружение активировано${NC}"
echo ""

# Создание .env файла если он не существует
if [ ! -f ".env" ]; then
    echo -e "${BLUE}→ Создание .env файла...${NC}"
    cp .env.example .env
    echo -e "${YELLOW}⚠ Отредактируйте .env и добавьте CLAUDE_API_KEY${NC}"
    echo ""
fi

# Установка зависимостей
echo -e "${BLUE}→ Установка зависимостей Python...${NC}"
pip install --upgrade pip setuptools wheel > /dev/null 2>&1
pip install -r backend/requirements.txt
echo -e "${GREEN}✓ Зависимости установлены${NC}"
echo ""

# Проверка PostgreSQL (если используется локально)
if command -v psql &> /dev/null; then
    echo -e "${BLUE}→ Обнаружена PostgreSQL${NC}"
    if psql -U postgres -d postgres -c "SELECT 1" > /dev/null 2>&1; then
        echo -e "${GREEN}✓ PostgreSQL доступна${NC}"
    else
        echo -e "${YELLOW}⚠ PostgreSQL не доступна, используйте SQLite для разработки${NC}"
    fi
else
    echo -e "${YELLOW}⚠ PostgreSQL не установлена, используется SQLite${NC}"
    export DATABASE_URL="sqlite:///./test.db"
fi
echo ""

# Инициализация прайс-листов
echo -e "${BLUE}→ Инициализация прайс-листов...${NC}"
python init_pricelists.py
echo ""

# Вывод статуса
echo -e "${GREEN}✓ Установка завершена!${NC}"
echo ""
echo -e "${YELLOW}Следующие шаги:${NC}"
echo "1. Отредактируйте .env и добавьте CLAUDE_API_KEY:"
echo "   nano .env"
echo ""
echo "2. Запустите сервер:"
echo "   python -m uvicorn backend.main:app --reload"
echo ""
echo "3. Откройте в браузере:"
echo "   http://localhost:8000"
echo ""
echo -e "${BLUE}Или используйте Docker:${NC}"
echo "   docker-compose up -d"
echo ""
echo -e "${BLUE}Дополнительно:${NC}"
echo "• README.md - Полная документация"
echo "• DEPLOYMENT.md - Развертывание на Render.com"
echo "• DOCKER_LOCAL.md - Docker инструкции"
echo ""
