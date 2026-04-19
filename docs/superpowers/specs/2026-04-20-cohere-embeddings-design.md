# Дизайн: замена OpenAI → Cohere для embedding-поиска

**Дата:** 2026-04-20  
**Статус:** утверждён

## Контекст

Проект использует embedding-поиск для семантического матчинга позиций прайс-листа. Текущая реализация основана на OpenAI `text-embedding-3-small` (1536 мер). OpenAI недоступен, требуется замена на Cohere `embed-multilingual-v3.0`.

## Выбранное решение

**Cohere `embed-multilingual-v3.0`** — многоязычная модель, размерность 1024, бесплатный тир 5М токенов/месяц. Лучшее качество для русскоязычных строк прайса.

## Область изменений

Меняется **только `backend/app/services/embedding_service.py`**. Всё остальное остаётся без изменений:
- `price_service.py` — вызывает `generate_embedding` / `generate_embeddings_batch` через тот же интерфейс
- `admin.py` — вызывает `generate_embeddings_batch` при загрузке прайса
- Модели БД — JSONB-столбцы хранят списки float произвольной длины, DDL не меняется
- Фронтенд — без изменений

## Детали реализации

### embedding_service.py

| Параметр | Было (OpenAI) | Станет (Cohere) |
|---|---|---|
| Библиотека | `openai>=1.0.0` | `cohere>=5.0.0` |
| Модель | `text-embedding-3-small` | `embed-multilingual-v3.0` |
| Размерность | 1536 | 1024 |
| Ключ | `OPENAI_API_KEY` | `COHERE_API_KEY` |
| Ошибка | `EmbeddingUnavailableError` | та же (переименовываем причину) |

**Важно: `input_type` в Cohere API**

Cohere различает два режима:
- `input_type="search_document"` — при индексации прайса (генерация векторов для хранения)
- `input_type="search_query"` — при поиске запроса из сметы

Сигнатура `generate_embeddings_batch` расширяется параметром:
```python
def generate_embeddings_batch(texts: list[str], input_type: str = "search_document") -> list[list[float]]
```

В `price_service._embedding_match_work/material` вызов меняется на:
```python
query_vec = await asyncio.to_thread(generate_embedding, normalized, input_type="search_query")
```

### config.py

Добавляем: `COHERE_API_KEY: str = ""`  
Оставляем: `OPENAI_API_KEY: str = ""` (не удаляем — могут быть другие вызовы)

### requirements.txt

Убираем: `openai>=1.0.0`  
Добавляем: `cohere>=5.0.0`

### Миграция существующих данных

Старые OpenAI-векторы (1536 мер) в БД несовместимы с Cohere (1024 мер). Требуется:

1. Alembic-миграция: сброс `embedding_status = 'pending'` для всех `price_lists` — сигнализирует что векторы устарели
2. Старые данные в `price_works.embedding` / `price_materials.embedding` не чистим — они перезапишутся при перегенерации
3. После деплоя: нажать «Перегенерировать векторы» в Admin

DDL-изменений нет — столбцы остаются `JSONB`.

### render.yaml

Добавить `COHERE_API_KEY` в секреты окружения.

## Критерии успеха

- Семантический поиск по прайсу работает без OpenAI
- `normalize_name()` применяется одинаково при индексации и поиске
- При отсутствии `COHERE_API_KEY` бросается `EmbeddingUnavailableError`, прайс сохраняется со статусом `failed`, поиск деградирует до веб-поиска
- Все существующие тесты проходят (с моком Cohere вместо OpenAI)
