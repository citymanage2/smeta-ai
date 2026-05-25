# Research: Вкладка "Дообучение" эмбеддингов

## Ключевые находки из кодовой базы

### Текущая embedding инфраструктура
- Хранение: JSONB в PostgreSQL, размерность **1024**, формат `list[float]`
- Поиск: numpy cosine similarity в памяти, порог **0.93**
- Таблицы с эмбеддингами: `price_works`, `price_materials`, `price_cache_works`, `price_cache_materials`
- Единственная точка генерации: `embedding_service.py` (clean интерфейс)
- Нормализация: `normalize_name()` — кириллизация, марки М100, lowercase

### Матчинг в task_processor
3 уровня: exact match → embedding similarity → Claude web search
Батч-вызов Cohere на все ненайденные позиции за 1 запрос

### Frontend паттерны
- FileUpload компонент — готов, поддерживает xlsx
- Polling: setInterval(3000ms) + visibilitychange handler
- Zustand stores: token в localStorage, isDirty флаги
- ProtectedRoute / requireAdmin для закрытых страниц

---

## Архитектурные решения

### 1. Хранение обучающих данных → PostgreSQL
Две новые таблицы:
- `training_pairs` (anchor_text, candidate_text, is_positive, source_file, created_at)
- `training_jobs` (status, pairs_count, progress_pct, model_path, started_at, finished_at)

### 2. Хранение дообученной модели
**Вариант A: Render Disk** (~$1/мес, 1GB)
- Персистентный, простой, синхронный доступ
- Минус: привязан к одному региону Render

**Вариант B: HuggingFace Hub** (бесплатно, private repo)
- Модель не теряется при деплоях
- Нужен HF_TOKEN в env
- При старте: скачать если есть новая версия
- Минус: ~500MB download при каждом холодном старте

**Вариант C: DB как BLOB** (для модели до 500MB — слишком тяжело)
→ Не подходит

**Рекомендация: Render Disk** — проще, синхронный доступ, $1/мес приемлемо.
Fallback: если нет диска — использовать базовую sentence-transformers модель.

### 3. Inference библиотека → FastEmbed
- +150MB зависимостей (vs +2GB для torch)
- Та же модель `intfloat/multilingual-e5-base`
- Размерность 768 (≠ 1024 у Cohere) → нужна перегенерация эмбеддингов

### 4. Training библиотека → sentence-transformers (только для training endpoint)
- Lazy import: `from sentence_transformers import ...` только внутри training функции
- torch устанавливается в requirements, но не загружается при обычной работе
- Время обучения на CPU: ~20-40 мин для 500 пар

### 5. Поток "игры"
```
Загрузка xlsx → парсинг позиций (существующий parse_estimate_excel)
→ для каждой позиции: текущая модель ищет top-3 кандидата
→ сохраняем в review_session (в памяти, не в БД)
→ пользователь оценивает ✅/❌ → сохраняем в training_pairs
→ при накоплении 200+ пар → кнопка "Обучить"
→ background task → обновление модели на Render Disk
→ перезагрузка модели без рестарта сервера
```

### 6. Обновление модели без рестарта
```python
# В embedding_service.py — singleton с возможностью reload
def reload_model(new_path: str):
    global _model
    with _model_lock:
        _model = SentenceTransformer(new_path)
```

### 7. Размерность после перехода
- multilingual-e5-base: **768** (≠ Cohere 1024)
- Нужна миграция ALTER COLUMN и перегенерация всех эмбеддингов
- Делаем в отдельной фазе, через кнопку в админке

---

## Scope фич

### В скоуп (MVP)
- Загрузка xlsx → автопарсинг позиций
- Игровой интерфейс да/нет для каждой пары
- Сохранение пар в БД
- Счётчик накопленных пар
- Запуск дообучения (фоновая задача + прогресс)
- Автоперезагрузка модели после обучения

### За скоупом (потом)
- Экспорт обучающих данных в JSON
- История версий модели
- A/B тест старой vs новой модели
- Автоматический сбор пар из истории матчинга
