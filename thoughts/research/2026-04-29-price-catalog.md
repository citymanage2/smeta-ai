# Research: Каталог расценок (Price Catalog)

Date: 2026-04-29

## 1. Существующая модель данных

### PriceWork (`backend/app/models/price.py`)
- id, name (Text), unit (String50), prices (JSON dict contractor→price), min_price (float), embedding (JSONB 1024-dim), updated_at

### PriceMaterial (`backend/app/models/price.py`)
- id, name (Text), unit (String50), price (float), embedding (JSONB 1024-dim), updated_at

### PriceList (`backend/app/models/price_list.py`)
- id, type ("works"|"materials"), filename, mime_type, content (bytes), embedding_status ("pending"|"ready"|"failed"), updated_at

## 2. Существующий сервис прайсов

**Файл:** `backend/app/services/price_service.py`

Трёхступенчатый поиск:
1. **Exact match** — нормализованное сравнение имён O(n)
2. **Embedding match** — cosine similarity с Cohere (threshold 0.93)
3. **Web search** — Claude с веб-поиском

In-memory кэш: sparse matrix NumPy (только позиции с эмбеддингами).

## 3. Существующие API роуты

`backend/app/routers/admin.py`:
- GET `/admin/price-lists/info` — метаданные
- POST `/admin/price-lists/works` — загрузка прайса работ
- POST `/admin/price-lists/materials` — загрузка прайса материалов
- POST `/admin/price-lists/{type}/generate-embeddings` — генерация эмбеддингов

**Нет** CRUD по отдельным позициям — нужно создавать.

## 4. Embedding-сервис

**Файл:** `backend/app/services/embedding_service.py`
- Модель: `embed-multilingual-v3.0`, 1024-dim
- Batch limit: 96 текстов за вызов
- `generate_embedding(text, input_type)` — одна позиция
- `generate_embeddings_batch(texts, input_type)` — батч

## 5. Использование цен при расчёте сметы

**Файл:** `backend/app/services/task_processor.py`, метод `_handle_estimate_from_list`

Поток:
1. Парсинг позиций из Excel "Перечень"
2. Для каждой позиции: exact → embedding match в кэше
3. Несовпавшие → Claude с web search
4. Сборка финальных позиций → генерация xlsx

## 6. Frontend-архитектура

- **Сайдбар:** `frontend/src/components/ProjectsSidebar.tsx` — нужно добавить секцию выше `Корзины`
- **Роутер:** `frontend/src/App.tsx` — добавить `/catalog`
- **Иконки:** `lucide-react` (BookOpen / Tag / LayoutList)
- **Стили:** inline React.CSSProperties, цвет primary #2563eb, slate palette
- **Хранилище:** Zustand (локальный стейт страницы достаточен)
- **API-клиент:** `frontend/src/api/client.ts` + отдельный модуль `catalog.ts`
- **Паттерн таблицы:** react-data-grid (в EstimateGrid) или нативная таблица (проще для каталога)

## 7. Рекомендации по реализации

### Backend
Создать новый роутер `backend/app/routers/prices_catalog.py`:
- `GET /prices/catalog` — список с фильтрами, поиском, пагинацией, сортировкой
- `POST /prices/catalog/works` — создать работу
- `POST /prices/catalog/materials` — создать материал
- `PUT /prices/catalog/works/{id}` — редактировать
- `PUT /prices/catalog/materials/{id}` — редактировать
- `DELETE /prices/catalog/works/{id}` — удалить
- `DELETE /prices/catalog/materials/{id}` — удалить
- `GET /prices/catalog/export` — экспорт xlsx
- `GET /prices/catalog/template` — шаблон для импорта
- POST импорт уже есть в `/admin/price-lists/{type}` — переиспользовать

При создании/обновлении позиции → сразу генерировать эмбеддинг.
После изменений → вызывать `load_cache()` для обновления in-memory кэша.

### Frontend
Новая страница `frontend/src/pages/PriceCatalog.tsx`:
- Три вкладки: Все | Работы | Материалы
- Колонки "Все": #, Название, Тип, Ед.изм., Цена, Обновлено, Действия
- Колонки "Работы": #, Название, Ед.изм., Подрядчики, Мин.цена, Обновлено, Действия
- Колонки "Материалы": #, Название, Ед.изм., Цена, Обновлено, Действия
- Пагинация: 20/50/100 строк, дефолт 20
- Поиск по названию (debounce 300ms)
- Фильтр (по наличию цены, по ед.изм.)
- Сортировка: название А-Я (дефолт), название Я-А, цена ↑↓, дата ↑↓
- Импорт/Экспорт/Шаблон кнопки
- Добавить вручную (модальное окно)
- Редактирование inline или модально
- Удаление с подтверждением

## 8. Вывод: лучшее решение

Нативная HTML-таблица (не react-data-grid) — проще, достаточно для каталога.
Один backend роутер с параметрами type/search/sort/page.
Эмбеддинги генерируются сразу при POST/PUT.
Кэш перезагружается после каждого изменения.
