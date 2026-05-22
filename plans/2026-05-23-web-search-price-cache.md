# Кеш цен из веб-поиска

**Цель:** устранить нестабильность цен между запусками.
Одна и та же позиция, не найденная в прайсе, сейчас при каждом запуске даёт новый web-поиск → разные источники → разные цены → расхождение 15–40%.

**Решение:** результаты web-поиска Claude сохранять в отдельные кеш-таблицы. При следующем поиске — сначала проверяем кеш, в Claude отправляем только то, что не нашли нигде. Срок жизни записи в кеше — 30 дней.

---

## Фазы реализации

### Фаза 1: База данных [x]

Создать миграцию `026_add_price_cache_tables.py`.

Две новые таблицы:

**price_cache_works**
```
id          UUID PK
name        TEXT NOT NULL
unit        TEXT
price       NUMERIC(12,2) NOT NULL     — средняя цена из 3 источников
sources     TEXT                        — 'Источник 1: X руб; Источник 2: Y руб; Источник 3: Z руб'
embedding   JSONB                       — вектор Cohere 1024d
created_at  TIMESTAMP NOT NULL DEFAULT now()
updated_at  TIMESTAMP NOT NULL DEFAULT now()
```

**price_cache_materials**
```
id          UUID PK
name        TEXT NOT NULL
unit        TEXT
price       NUMERIC(12,2) NOT NULL
sources     TEXT
embedding   JSONB
created_at  TIMESTAMP NOT NULL DEFAULT now()
updated_at  TIMESTAMP NOT NULL DEFAULT now()
```

Индексы: `updated_at` на обеих таблицах (для эффективного автоудаления).

Правило TTL: запись считается устаревшей если `updated_at < now() - 30 days`.
`updated_at` обновляется при:
- сохранении нового результата web-поиска
- ручном редактировании через UI

---

### Фаза 2: Модели SQLAlchemy [x]

Создать `backend/app/models/price_cache.py`:
- `PriceCacheWork` — ORM-модель для `price_cache_works`
- `PriceCacheMaterial` — ORM-модель для `price_cache_materials`

Структура аналогична `PriceWork` / `PriceMaterial` из `price.py`, но без `prices` (dict) и `min_price` — только одна цена.

---

### Фаза 3: Сервис — расширение price_service [ ]

В `backend/app/services/price_service.py` добавить:

**In-memory кеш для cache-таблиц (аналогично существующим `_works_cache` / `_materials_cache`):**
- `_cache_works_cache: list[dict]`
- `_cache_materials_cache: list[dict]`
- `_cache_works_embeddings`: numpy array
- `_cache_materials_embeddings`: numpy array

**Метод `load_cache(db)`** — расширить: дополнительно загружать записи из `price_cache_works` и `price_cache_materials` в память, исключая записи с `updated_at < now() - 30 days`.

**Методы поиска по кешу:**
- `_exact_match_cache_work(name) → dict | None`
- `_exact_match_cache_material(name) → float | None`
- `batch_embedding_match_cache_works(names) → list[dict | None]`
- `batch_embedding_match_cache_materials(names) → list[float | None]`

Механизм идентичен существующим методам для прайса (нормализация текста, cosine similarity, порог 0.93).

**Метод `save_to_cache(db, type, name, unit, price, sources)`:**
- Проверить: есть ли уже запись с таким `normalize(name)` в таблице.
- Если есть — обновить `price`, `sources`, `updated_at = now()`.
- Если нет — создать новую запись.
- После сохранения — запустить генерацию embedding для новой/обновлённой записи (асинхронно, не блокировать основной поток).
- Инвалидировать in-memory кеш для обновлённых записей.

---

### Фаза 4: Обновление порядка поиска цен в task_processor [ ]

В `ESTIMATE_FROM_LIST` поток поиска цены для каждой позиции изменить на 5 шагов:

```
1. Exact match → price_works / price_materials (существующий прайс)
2. Embedding match → price_works / price_materials (существующий прайс)
3. Exact match → price_cache_works / price_cache_materials (новый кеш)
4. Embedding match → price_cache_works / price_cache_materials (новый кеш)
5. Claude web search → сохранить результат в кеш через save_to_cache()
```

Шаги 3 и 4 добавляются между существующими шагами 2 и 3 (web search).
Только позиции, прошедшие все 4 шага без результата, уходят в Claude.

При получении результата от Claude (шаг 5) — в цикле `for result_item in data.get("items", []):`
```python
if result_item.get("price") is not None:
    await save_to_cache(db, type, name, unit, price, sources)
    logger.info("Saved to price cache", name=name)
# если price == None — ничего не сохраняем, следующий запуск снова пойдёт в Claude
```

**Решение:** если Claude не нашёл цену (`price = null`) — запись в кеш не сохраняется. Такая позиция при следующем запуске снова уйдёт в Claude. Это сознательный выбор: не фиксировать «пустышку» в кеше.

---

### Фаза 5: Автоудаление устаревших записей [ ]

Добавить зависимость: `apscheduler[asyncio]` в `backend/requirements.txt`.

В `backend/app/main.py` настроить `AsyncIOScheduler` из `apscheduler`:

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()
scheduler.add_job(cleanup_price_cache, "interval", hours=24)
```

В lifespan:
- Запустить `cleanup_price_cache()` один раз при старте (после `load_cache`).
- Запустить `scheduler.start()`.
- В shutdown: `scheduler.shutdown()`.

**Почему apscheduler, а не `asyncio.sleep`:** Render.com перезапускает контейнер несколько раз в сутки, при этом `asyncio.sleep(86400)` сбрасывается и cleanup фактически никогда не срабатывает по расписанию. `apscheduler` хранит состояние независимо от этого и гарантирует запуск раз в 24 часа даже при частых рестартах.

**Что делает `cleanup_price_cache()`:**
```sql
DELETE FROM price_cache_works WHERE updated_at < now() - interval '30 days';
DELETE FROM price_cache_materials WHERE updated_at < now() - interval '30 days';
```
После удаления — перегрузить in-memory кеш (`price_service.load_cache(db)`).
Логировать: сколько записей удалено.

---

### Фаза 6: API эндпоинты для управления кешем [ ]

В `backend/app/routers/admin.py` добавить (только для admin):

```
GET  /admin/price-cache/works              — список с пагинацией и поиском по name
GET  /admin/price-cache/materials          — список с пагинацией и поиском по name
POST /admin/price-cache/works              — создать запись вручную
POST /admin/price-cache/materials          — создать запись вручную
PATCH /admin/price-cache/works/{id}        — редактировать name, unit, price, sources (обновляет updated_at)
PATCH /admin/price-cache/materials/{id}    — то же
DELETE /admin/price-cache/works/{id}       — удалить запись
DELETE /admin/price-cache/materials/{id}   — удалить запись
```

Ответ на GET-запросы:
```json
{
  "items": [
    {
      "id": "uuid",
      "name": "Монтаж трубы ПВХ Ø50",
      "unit": "м.п.",
      "price": 450.00,
      "sources": "stroimaterial.ru: 420 руб; petrovich.ru: 460 руб; leroymerlin.ru: 470 руб",
      "updated_at": "2026-05-23T10:00:00Z",
      "expires_in_days": 28
    }
  ],
  "total": 142,
  "page": 1,
  "page_size": 20
}
```

Поле `expires_in_days` = `30 - (now - updated_at).days`. Если < 0 — запись уже устарела (на случай, если cleanup ещё не сработал).

---

### Фаза 7: UI — вкладки кеша в каталоге расценок [ ]

В `frontend/src/pages/PriceCatalog.tsx` добавить две вкладки рядом с существующими «Работы» / «Материалы»:
- **Кеш работ**
- **Кеш материалов**

Таблица для каждой вкладки:

| № | Наименование | Ед. изм | Цена, руб | Источник | Обновлено | Истекает | — |
|---|---|---|---|---|---|---|---|
| 1 | Монтаж трубы ПВХ Ø50 | м.п. | 450,00 | stroimaterial.ru: 420; ... | 23.05.2026 | 28 дн. | ✏️ ✕ |

Колонка «Источник» — текст, при наведении полный текст в tooltip (т.к. длинная строка с 3 источниками).
Колонка «Истекает» — `expires_in_days` дней. Если ≤ 7 — подсветка оранжевым. Если < 0 — красным «Устарело».

Кнопка **✏️ (редактировать)** — открывает модальное окно с полями `Наименование`, `Ед. изм`, `Цена`, `Источник`. При сохранении — PATCH запрос, `updated_at` обновляется.

Кнопка **✕ (удалить)** — DELETE запрос с подтверждением.

Поиск и пагинация — аналогично существующим вкладкам прайса.

---

## Итог реализации

| Компонент | Что меняется |
|---|---|
| БД | +2 таблицы: `price_cache_works`, `price_cache_materials` |
| Миграция | `026_add_price_cache_tables.py` |
| Модели | `backend/app/models/price_cache.py` |
| Сервис | `price_service.py` — 4 новых метода поиска + `save_to_cache()` + расширение `load_cache()` |
| Процессор | `task_processor.py` — 2 новых шага в цепочке поиска цен; позиции без цены от Claude в кеш не сохраняются |
| Зависимости | `requirements.txt` — добавить `apscheduler[asyncio]` |
| Main | `main.py` — `AsyncIOScheduler`, задача `cleanup_price_cache()` раз в 24 часа |
| API | `admin.py` — 8 новых эндпоинтов |
| Frontend | `PriceCatalog.tsx` — 2 новые вкладки |

**Ожидаемый результат:** при повторной обработке того же перечня через 1–29 дней — цены берутся из кеша, не из Claude. Расхождение между запусками ≤ 1% (только округление).

**Принятые решения:**
- Если Claude не нашёл цену → в кеш не сохраняем, при следующем запуске снова ищем.
- Cleanup по расписанию через `apscheduler` (не `asyncio.sleep`) — надёжно работает при частых рестартах Render.
- UI для управления кешем входит в эту задачу (фазы 6–7).
