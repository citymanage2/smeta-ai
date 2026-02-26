# Локальное развертывание с Docker Compose

Быстрое развертывание Smeta AI в локальной среде с помощью Docker Compose.

## 📋 Требования

- Docker Desktop (https://www.docker.com/products/docker-desktop)
- Docker Compose (обычно идет с Docker Desktop)

## 🚀 Быстрый старт

### 1. Клонирование репозитория

```bash
git clone https://github.com/YOUR_USERNAME/smeta-ai.git
cd smeta-ai
```

### 2. Создание .env файла

```bash
cp .env.example .env
```

Отредактируйте `.env` и добавьте ваш `CLAUDE_API_KEY`:

```env
CLAUDE_API_KEY=sk-XXXXXXXXXXXXXXXXXXXXXXXXXXXX
USER_PASSWORD=user123
ADMIN_PASSWORD=admin123
JWT_SECRET=your-very-secret-key-change-this
```

### 3. Запуск Docker Compose

```bash
docker-compose up -d
```

**Флаги:**
- `-d` - запуск в фоне (background)

### 4. Инициализация базы данных

Docker Compose автоматически будет инициализирует БД при первом запуске.

Проверить статус можно командой:

```bash
docker-compose ps
```

Оба сервиса должны иметь статус **Up** и **healthy**:

```
CONTAINER ID        IMAGE                    STATUS
xxxxx               postgres:15-alpine       Up 2 minutes (healthy)
xxxxx               smeta-ai:latest          Up 2 minutes (healthy)
```

### 5. Открытие приложения

Приложение доступно по адресу: **http://localhost:8000**

## 📚 Основные команды

### Запуск сервисов

```bash
# Запуск в фоне
docker-compose up -d

# Запуск с выводом логов
docker-compose up
```

### Остановка сервисов

```bash
docker-compose down
```

### Просмотр логов

```bash
# Логи всех сервисов
docker-compose logs -f

# Логи конкретного сервиса
docker-compose logs -f backend
docker-compose logs -f db
```

### Перестройка образов

```bash
# Если вы изменили код
docker-compose up -d --build

# Полностью перестроить
docker-compose build --no-cache
docker-compose up -d
```

### Удаление контейнеров и томов

```bash
# Удалить контейнеры (но сохранить данные БД)
docker-compose down

# Удалить всё включая БД
docker-compose down -v
```

## 🔧 Подключение к базе данных

### Из контейнера

```bash
docker-compose exec db psql -U smeta_ai_user -d smeta_ai
```

### С локальной машины

Используя любой клиент PostgreSQL:
- **Host**: localhost
- **Port**: 5432
- **User**: smeta_ai_user
- **Password**: smeta_ai_password
- **Database**: smeta_ai

**Пример с psql:**
```bash
psql postgresql://smeta_ai_user:smeta_ai_password@localhost:5432/smeta_ai
```

## 📁 Файловая структура томов

```
/app/
  backend/          - Исходный код (mounted)
  frontend/         - Фронтенд (mounted)
  pricelists/       - Прайс-листы
  
pgdata/             - Данные PostgreSQL (named volume)
```

## 🔄 Обновление кода

Если вы внесли изменения в код:

```bash
# Перестроить для backend
docker-compose up -d --build backend

# Или просто перезагрузить
docker-compose restart backend
```

## 🐛 Отладка

### Проверка состояния

```bash
# Статус всех сервисов
docker-compose ps

# Проверить логи backend
docker-compose logs backend | tail -50

# Проверить logи БД
docker-compose logs db | tail -50
```

### Проверка подключения к БД

```bash
# Из контейнера backend
docker-compose exec backend python -c "
from backend.database import engine
try:
    with engine.connect() as conn:
        print('✓ Database connected successfully')
except Exception as e:
    print(f'✗ Database error: {e}')
"
```

### Проверка API

```bash
# Health check
curl http://localhost:8000/api/health

# Должен вернуть:
# {"status":"ok","service":"Smeta AI"}
```

## 🌍 Переменные окружения

### Для backend

```env
DATABASE_URL=postgresql://...  # Автоматически установлена
CLAUDE_API_KEY=sk-...          # Ваш Claude API ключ
USER_PASSWORD=...              # Пароль для пользователей
ADMIN_PASSWORD=...             # Пароль для администраторов
JWT_SECRET=...                 # Секрет для JWT токенов
CLAUDE_MODEL=claude-opus-4-5   # Модель Claude для использования
PORT=8000                      # Порт приложения
```

### Для базы данных

```env
POSTGRES_USER=smeta_ai_user
POSTGRES_PASSWORD=smeta_ai_password
POSTGRES_DB=smeta_ai
```

## 💡 Полезные советы

### Отключение cache при разработке

Отредактируйте `docker-compose.yml`:

```yaml
backend:
  build:
    context: .
    cache_from: []  # Отключить кеш
```

### Увеличение лимита памяти

В `docker-compose.yml`:

```yaml
backend:
  deploy:
    resources:
      limits:
        memory: 1G
```

### Использование различных версий Python

В `Dockerfile` измените:

```dockerfile
FROM python:3.11-slim  # На 3.9, 3.10, 3.12 как нужно
```

## 🔒 Безопасность для разработки

**Внимание:** Конфиг в `docker-compose.yml` используется только для разработки!

Для production используйте Render.com или другой облачный сервис с правильной конфигурацией безопасности.

## 🆘 Часто встречающиеся проблемы

### "Address already in use"

Порт 8000 или 5432 уже используется:

```bash
# Найти процесс на порту
lsof -i :8000

# Или используйте другой порт в docker-compose.yml
ports:
  - "8001:8000"  # Внешний порт:внутренний порт
```

### "Cannot connect to Docker daemon"

Docker не запущен:
- На Windows/Mac запустите Docker Desktop
- На Linux: `sudo systemctl start docker`

### "permission denied while trying to connect"

На Linux:
```bash
sudo usermod -aG docker $USER
# Выйдите и снова войдите
```

### Медленная работа на Windows/Mac

Docker может быть медленным. Это нормально при использовании WSL 2 или VirtualBox.

Оптимизируйте:
```bash
# Используйте выделенный диск для Docker
# В Docker Desktop Settings > Resources
```

## 📝 Дополнительно

### Резервная копия БД

```bash
docker-compose exec db pg_dump -U smeta_ai_user smeta_ai > backup.sql
```

### Восстановление БД

```bash
docker-compose exec -T db psql -U smeta_ai_user smeta_ai < backup.sql
```

### Просмотр переменных окружения

```bash
docker-compose config
```

## 📚 Ссылки

- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [Docker Best Practices](https://docs.docker.com/develop/dev-best-practices/)
- [PostgreSQL in Docker](https://hub.docker.com/_/postgres)

---

**Готово!** Теперь у вас есть полностью функциональный Smeta AI локально.
