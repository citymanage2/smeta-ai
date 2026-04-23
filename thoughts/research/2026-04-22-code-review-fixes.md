# Research: Code Review Fixes — smeta-ai
**Date:** 2026-04-22
**Scope:** 7 конкретных проблем, найденных в ревью по принципам review-sm-smeta

---

## Обнаруженные проблемы (проверено по коду)

### P1. VAT_RATE — 5 дублей с расхождением 0.20 vs 0.22 [BLOCKING]

**Файлы:**
- `excel_service.py:352` — `VAT_RATE = 0.20` (локальная переменная)
- `excel_service.py:494` — `VAT_RATE = 0.20` (локальная переменная)
- `excel_service.py:654` — `VAT_RATE = 0.20` (локальная переменная)
- `excel_service.py:839` — `VAT_RATE = 0.22` (локальная переменная — другое значение!)
- `xlsx_optimizer.py:19` — `VAT_RATE = 0.20` (глобальная константа)
- `excel_service.py:364` — хардкод строки `"НДС (20%)"` в заголовке листа

**Итого 5 определений + 1 хардкод строки. Три функции выдают НДС 20%, одна — 22%.**
Пользователь подтвердил: корректная ставка — **0.22 (22%)**.

**Решение:** Одна константа `VAT_RATE: float = 0.22` в `config.py` → `settings.VAT_RATE`.
Все 5 мест заменяют `VAT_RATE = ...` на `from app.config import settings` + `settings.VAT_RATE`.
Заголовок `"НДС (20%)"` → `f"НДС ({int(settings.VAT_RATE * 100)}%)"`.

---

### P2. Price cache не защищён asyncio.Lock [BLOCKING]

**Файл:** `price_service.py:25-33, 198-253`

Глобальные переменные `_works_cache`, `_materials_cache`, `_works_embeddings`, `_works_row_norms`, `_materials_embeddings`, `_materials_row_norms` изменяются в `load_cache()` без блокировки.

**Сценарий гонки:** Фоновая задача читает `_works_embeddings[best_idx]` → параллельно `/api/admin/reload-price` вызывает `load_cache()` → `_works_embeddings = None` → IndexError или матч по старой матрице с новым кэшем.

**Решение:** Один `asyncio.Lock _cache_lock` на уровне модуля. `load_cache()` захватывает lock при записи. Функции-читатели (`_exact_match_*`, `_embedding_match_*`) читают без lock (read-only), но матрица и кэш атомарно заменяются через локальные переменные + одно присваивание глобала.

**Паттерн:** copy-on-write — строим новые объекты локально, присваиваем глобалы одной операцией внутри `async with _cache_lock`.

---

### P3. Падение чанка роняет всю задачу без retry [BLOCKING]

**Файл:** `task_processor.py:683-731`

В `_handle_list_from_grand()` блок `except Exception as chunk_error` (строки 704-731) сохраняет частичный результат и сразу делает `raise`. Нет попытки повторить чанк.

**Сценарий:** Transient 500 от Anthropic на 7-м чанке из 10 → задача падает → пользователь перезапускает вручную → теряет время + платит за повтор уже сделанных чанков.

**Решение:** Внутри цикла для каждого чанка — локальный retry (3 попытки, backoff 5/15/30 сек) перед тем как поднять исключение наружу. `TaskCancelledError` не ретраится — всегда пробрасывается немедленно.

Аналогичный паттерн нужен в `_handle_check_completeness()` и других методах с чанками.

---

### P4. Cumulative timeout не учитывает время rate-limit sleeps [IMPORTANT]

**Файл:** `claude_service.py:119-126`

`processing_timeout` передаётся в каждый retry-вызов как одинаковое значение. После `asyncio.sleep(60)` на rate-limit следующий вызов получает тот же таймаут — не уменьшенный.

**Пример:** `processing_timeout=1200`. Попал в 429, sleep 60s. Следующий вызов: `timeout=1200`. Фактически задача работает 1200 + 60 = 1260s вместо 1200s.

**Решение:** Замерять `call_start = asyncio.get_event_loop().time()` перед первым вызовом. Перед каждым retry: `remaining = processing_timeout - (now - call_start)`. Если `remaining <= 0` — поднять `asyncio.TimeoutError` немедленно.

---

### P5. Нет prompt caching → x5-10 лишних input tokens на больших задачах [IMPORTANT]

**Файл:** `claude_service.py:90-99`

Системный промпт и user-контент передаются без `cache_control`. Claude Anthropic API поддерживает `cache_control: {type: "ephemeral"}` для кэширования до 5 минут.

**Где применимо:**
- `kwargs["system"]` — всегда статический промпт → кэшировать
- Большие image_data блоки (контент PDF) при многопроходной обработке
- `SYSTEM_BASE` в task_processor — одинаковый для всех чанков задачи

**Формат cache_control в SDK:**
```python
# system с кэшированием
kwargs["system"] = [
    {"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}
]
# image block с кэшированием
image_block["cache_control"] = {"type": "ephemeral"}
```

**Ограничение:** cache_control доступен только в `messages.create`, не в streaming. Кэш — TTL 5 минут. При обработке 10 чанков с одним system prompt: экономия ~90% input tokens системного промпта.

---

### P6. Embedding matrix требует 100% строк с эмбеддингами [IMPORTANT]

**Файл:** `price_service.py:217, 238`

```python
if _numpy_available and works and all(w.embedding for w in works):
```

Если 1 строка из 500 без эмбеддинга → вся матрица не строится → semantic search недоступен.

**Случаи когда это происходит:**
- Новая запись добавлена вручную без запуска embedding
- Ошибка Cohere при генерации эмбеддинга для одной строки
- Импорт прайса частично завершился

**Решение:** Строить матрицу только из строк с непустым embedding. Хранить `_works_index_map: list[int]` — маппинг `matrix_row → cache_idx`. При матче: `cache_idx = _works_index_map[best_idx]` → `_works_cache[cache_idx]`.

---

### P7. Составной индекс (project_id, estimation_status) отсутствует [FUTURE]

**Файл:** `models/task.py:34-38`

`index=True` только на `project_id`. Запросы `_aggregate()` в projects.py фильтруют по `project_id` + читают `estimation_status`, `cost`. На 1000+ задач — seq scan по estimation_status.

**Решение:** Добавить `Index("ix_tasks_project_estimation", "project_id", "estimation_status")` в модель + миграцию Alembic.

---

### Закрытые пункты (уже исправлено)

- **SQL aggregation** в `projects.py:100-127` — уже реализована через `func.count/sum` + `case()`. В памяти ничего не считается.

---

## Рекомендуемый порядок реализации

1. VAT_RATE (XS, устраняет финансовую ошибку)
2. Price cache Lock (S, устраняет race condition)
3. Chunk retry (M, устраняет потерю задач при transient errors)
4. Prompt caching (M, снижает стоимость в 5-10x на больших задачах)
5. Sparse embedding matrix (S, делает semantic search устойчивым к частичным данным)
6. Cumulative timeout (S, корректирует поведение при rate limits)
7. Составной индекс (XS + миграция, оптимизация на будущее)
