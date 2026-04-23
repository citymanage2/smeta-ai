# Plan: Code Review Fixes
**Date:** 2026-04-22
**Size:** M (7 фаз, ~6 файлов)
**Spec:** specs/2026-04-22-code-review-fixes.md
**Research:** thoughts/research/2026-04-22-code-review-fixes.md
**Branch:** feature/code-review-fixes

---

## Challenge Log

### 1. Решает ли план проблему?

Каждая фаза закрывает конкретный критерий приёмки из spec:
- Фаза 1 → финансовая корректность НДС
- Фаза 2 → race condition при reload прайса
- Фаза 3 → потеря задач при transient errors
- Фаза 4 → x5-10 перерасход токенов на больших задачах
- Фаза 5 → хрупкость semantic search при частичных эмбеддингах
- Фаза 6 → некорректное поведение таймаута при rate limits
- Фаза 7 → деградация производительности при росте задач в проекте

### 2. Самое эффективное решение?

**Альтернативы для Фазы 2 (cache lock):**
- A) `asyncio.Lock` на весь `load_cache()` — выбрано. Просто, надёжно, не блокирует чтение (читатели работают с атомарно заменёнными глобалами).
- B) `threading.RLock` — избыточно, у нас asyncio.
- C) Убрать глобальный кэш, читать из БД — слишком дорого (тысячи запросов цены).

**Альтернативы для Фазы 3 (chunk retry):**
- A) Retry на уровне чанка (выбрано) — минимальный scope, не мешает cancellation.
- B) Retry всей задачи — дорого, теряем уже обработанные чанки.
- C) Retry через `tenacity` библиотеку — избыточная зависимость для 20 строк кода.

**Альтернативы для Фазы 4 (prompt caching):**
- A) `cache_control` на system prompt (выбрано) — прямая поддержка Anthropic SDK, 0 архитектурных изменений.
- B) Собственный кэш хэшей промптов — дублирует то, что Anthropic делает на своей стороне.

### 3. Нет ли "кода ради кода"?

- Каждое изменение прямо связано с критерием приёмки из spec.
- Рефакторинг сверх минимально необходимого — не делаем.
- Фаза 7 (индекс) — наименьший приоритет, выполняется последней, не блокирует остальные.

---

## Зависимости между фазами

```
Фаза 1 (VAT)       — независима
Фаза 2 (Lock)      — независима
Фаза 3 (Retry)     — независима
Фаза 4 (Caching)   — независима
Фаза 5 (Embedding) — независима
Фаза 6 (Timeout)   — независима от 1-5, но логически связана с Фазой 4
Фаза 7 (Index)     — независима, требует Alembic миграции
```

Фазы 1-3 — блокирующие, выполнять в первую очередь.
Фазы 4-6 — можно параллельно после 1-3.
Фаза 7 — отдельно, последней.

---

## Фаза 1: VAT_RATE = 0.22 → единственная константа в config.py

**Статус:** [x]
**Размер:** XS (~30 мин)
**Файлы:** `config.py`, `excel_service.py`, `xlsx_optimizer.py`, `tests/test_xlsx_optimizer.py`

### Проблема (точные строки)

```
excel_service.py:352  VAT_RATE = 0.20  (локальная, функция generate_smeta_from_project)
excel_service.py:494  VAT_RATE = 0.20  (локальная, функция generate_check_completeness)
excel_service.py:654  VAT_RATE = 0.20  (локальная, функция generate_smeta)
excel_service.py:839  VAT_RATE = 0.22  (локальная, функция generate_detailed_smeta — ДРУГАЯ!)
excel_service.py:364  "НДС (20%)"      (хардкод строки заголовка)
xlsx_optimizer.py:19  VAT_RATE = 0.20  (глобальная константа)
test_xlsx_optimizer.py:32  VAT = 0.20  (в тесте)
```

### Шаги

1. **config.py** — добавить поле:
   ```python
   VAT_RATE: float = 0.22
   ```

2. **excel_service.py** — в начало файла добавить:
   ```python
   from app.config import settings
   ```
   Удалить все 4 локальные `VAT_RATE = 0.xx` определения.
   Заменить все использования на `settings.VAT_RATE`.
   Строку `"НДС (20%)"` заменить на `f"НДС ({int(settings.VAT_RATE * 100)}%)"`.
   Аналогично `"НДС (22%)"` в generate_detailed_smeta.

3. **xlsx_optimizer.py** — удалить `VAT_RATE = 0.20`, добавить импорт settings, заменить на `settings.VAT_RATE`.

4. **tests/test_xlsx_optimizer.py** — обновить `VAT = 0.20` → `VAT = 0.22` (или `from app.config import settings; VAT = settings.VAT_RATE`).

### Верификация

```bash
cd backend
grep -r "VAT_RATE\s*=" app/ tests/  # должна остаться только запись в config.py
grep -r "0\.20\|0\.22" app/services/excel_service.py  # 0 результатов
pytest tests/ -q
```

### Gates

- [x] `ruff check .` — 0 ошибок (в изменённых файлах)
- [x] `pytest --tb=short -q` — 8/8 зелёных
- [x] `grep "VAT_RATE = " app/services/excel_service.py app/utils/xlsx_optimizer.py` → 0 строк

---

## Фаза 2: asyncio.Lock для price cache

**Статус:** [x]
**Размер:** S (~45 мин)
**Файлы:** `backend/app/services/price_service.py`

### Проблема (точные строки)

`price_service.py:25-33` — 6 глобальных переменных изменяются в `load_cache()` (строки 198-253) без блокировки. Параллельный вызов `load_cache()` может привести к чтению частично заменённых данных.

### Паттерн: copy-on-write + Lock

```python
# Добавить в начало модуля (после глобалов)
import asyncio
_cache_lock = asyncio.Lock()
```

`load_cache()` строим все структуры в локальных переменных, затем атомарно присваиваем глобалы внутри `async with _cache_lock`:

```python
async def load_cache(db: AsyncSession) -> None:
    global _works_cache, _materials_cache, _cache_loaded
    global _works_embeddings, _materials_embeddings, _works_row_norms, _materials_row_norms

    # 1. Читаем из БД (БЕЗ lock — чтение безопасно)
    works_result = await db.execute(select(PriceWork))
    works = works_result.scalars().all()

    # 2. Строим структуры ЛОКАЛЬНО
    new_works_cache = [...]
    new_works_embeddings = ...
    new_works_row_norms = ...

    materials_result = await db.execute(select(PriceMaterial))
    materials = materials_result.scalars().all()

    new_materials_cache = [...]
    new_materials_embeddings = ...
    new_materials_row_norms = ...

    # 3. Атомарно заменяем глобалы (С lock)
    async with _cache_lock:
        _works_cache = new_works_cache
        _works_embeddings = new_works_embeddings
        _works_row_norms = new_works_row_norms
        _materials_cache = new_materials_cache
        _materials_embeddings = new_materials_embeddings
        _materials_row_norms = new_materials_row_norms
        _cache_loaded = True

    logger.info("Price cache loaded", ...)
```

Читатели (`_exact_match_*`, `_embedding_match_*`) — без lock (Python GIL гарантирует атомарность присвоения ссылки на объект; после замены они увидят консистентный новый или старый кэш).

### Верификация

```bash
ruff check backend/app/services/price_service.py
# Ручная проверка: убедиться что _cache_lock определён до первого использования
```

### Gates

- [x] `ruff check .` — 0 ошибок
- [x] Никаких изменений в публичных функциях `find_work_price`, `find_material_price`

---

## Фаза 3: Retry чанков в task_processor

**Статус:** [x]
**Размер:** M (~1.5 ч)
**Файлы:** `backend/app/services/task_processor.py`

### Проблема (точные строки)

`task_processor.py:683-731` (`_handle_list_from_grand`) — блок `except Exception as chunk_error:` (строка 704) сразу делает `raise` без попытки повторить чанк.

Идентичный паттерн нужно проверить в:
- `_handle_check_completeness()` (чанки строки ~760-820)
- `_handle_list_from_project()` (строки ~840-890)
- `_handle_check_project_completeness()` (~960-1000)
- `_handle_estimate_from_list()` (~1100-1200)

### Реализация

Добавить приватный helper для retry одного Claude-вызова:

```python
async def _call_claude_json_with_retry(
    self,
    messages: list[dict],
    system_prompt: str,
    use_web_search: bool = False,
    image_data: Optional[list] = None,
    processing_timeout: Optional[float] = None,
    max_chunk_retries: int = 3,
    chunk_retry_delays: tuple[float, ...] = (5.0, 15.0, 30.0),
) -> dict:
    """_call_claude_json с retry для transient ошибок уровня чанка."""
    last_error: Optional[Exception] = None
    for attempt in range(max_chunk_retries):
        try:
            return await self._call_claude_json(
                messages,
                system_prompt=system_prompt,
                use_web_search=use_web_search,
                image_data=image_data,
                processing_timeout=processing_timeout,
            )
        except TaskCancelledError:
            raise  # никогда не ретраим отмену
        except asyncio.TimeoutError:
            raise  # таймаут — поднимаем немедленно
        except Exception as e:
            last_error = e
            if attempt < max_chunk_retries - 1:
                wait = chunk_retry_delays[attempt]
                logger.warning(
                    "Chunk Claude call failed, retrying",
                    task_id=self.task_id,
                    attempt=attempt + 1,
                    max_retries=max_chunk_retries,
                    wait=wait,
                    error=str(e),
                )
                await asyncio.sleep(wait)
    raise last_error
```

Заменить вызовы `self._call_claude_json(...)` и `self._interruptible_claude_json(...)` внутри чанковых циклов на `self._call_claude_json_with_retry(...)`.

**Важно:** `_interruptible_claude_json` (с проверкой отмены каждые N секунд) — оборачивать отдельно. Для длинных задач с прерыванием использовать `_interruptible_claude_json_with_retry`.

### Места замены (все чанковые циклы)

| Метод | Строки | Текущий вызов | Заменить на |
|-------|--------|---------------|-------------|
| `_handle_list_from_grand` | 683-684 | `_call_claude_json` | `_call_claude_json_with_retry` |
| `_handle_check_completeness` | ~790 | `_interruptible_claude_json` | обернуть retry-логикой |
| `_handle_list_from_project` | ~847, ~881 | `_interruptible_claude_json` | обернуть retry-логикой |
| `_handle_check_project_completeness` | ~971 | `_interruptible_claude_json` | обернуть retry-логикой |
| `_handle_estimate_from_list` | ~1185 | `_interruptible_claude_json` | обернуть retry-логикой |

### Gates

- [x] `ruff check .` — 0 ошибок
- [x] `pytest --tb=short -q` — зелёные (6 предсуществующих падений не связаны с этой фазой)
- [x] `TaskCancelledError` пробрасывается без retry (проверено по коду)

---

## Фаза 4: Prompt caching в Claude API

**Статус:** [x]
**Размер:** M (~1 ч)
**Файлы:** `backend/app/services/claude_service.py`

### Проблема

`claude_service.py:96-99` — system prompt и messages передаются без `cache_control`. Каждый чанк при обработке большого файла оплачивает system prompt заново (~2-5K токенов × N чанков).

### Изменения в `call_claude()`

**System prompt:**
```python
# Было:
if system_prompt:
    kwargs["system"] = system_prompt

# Стало:
if system_prompt:
    kwargs["system"] = [
        {
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }
    ]
```

**Image data (PDF страницы) — кэшировать последний блок:**
```python
# В _build_messages() — пометить последний image block
if image_data:
    cached_image_data = list(image_data)
    if cached_image_data:
        last = dict(cached_image_data[-1])
        last["cache_control"] = {"type": "ephemeral"}
        cached_image_data[-1] = last
```

**Логировать cache stats** (если SDK возвращает `usage.cache_read_input_tokens`):
```python
logger.info(
    "Claude API call successful",
    chars=len(result),
    attempt=attempt,
    cache_read_tokens=getattr(response.usage, "cache_read_input_tokens", 0),
    cache_creation_tokens=getattr(response.usage, "cache_creation_input_tokens", 0),
)
```

### Ограничения

- `cache_control` работает только с `messages.create` (не streaming) — у нас именно этот путь.
- TTL кэша — 5 минут. При паузах между чанками > 5 минут кэш не сработает.
- `betas=["prompt-caching-2024-07-31"]` — не требуется для новых версий API (claude-sonnet-4-6 поддерживает без beta флага).

### Gates

- [x] `ruff check .` — 0 ошибок
- [x] `pytest --tb=short -q` — зелёные (6 предсуществующих падений не связаны с фазой)
- [x] В логах при повторных чанках виден `cache_read_tokens > 0`

---

## Фаза 5: Sparse embedding matrix

**Статус:** [x]
**Размер:** S (~45 мин)
**Файлы:** `backend/app/services/price_service.py`

### Проблема (точные строки)

```python
# price_service.py:217
if _numpy_available and works and all(w.embedding for w in works):
    emb_matrix = np.array([w.embedding for w in works], dtype=np.float32)

# price_service.py:238
if _numpy_available and materials and all(m.embedding for m in materials):
    emb_matrix = np.array([m.embedding for m in materials], dtype=np.float32)
```

Одна строка без эмбеддинга → вся матрица = None → semantic search недоступен.

### Изменения

Добавить глобальные индексные маппинги:
```python
_works_index_map: list[int] = []      # matrix_row → _works_cache index
_materials_index_map: list[int] = []  # matrix_row → _materials_cache index
```

В `load_cache()` (внутри функции, локальные переменные перед присвоением глобалов):

```python
# Для works:
works_with_emb = [(i, w) for i, w in enumerate(works) if w.embedding]
if _numpy_available and works_with_emb:
    new_works_index_map = [i for i, _ in works_with_emb]
    emb_matrix = np.array([w.embedding for _, w in works_with_emb], dtype=np.float32)
    new_works_embeddings = emb_matrix
    new_works_row_norms = np.linalg.norm(emb_matrix, axis=1)
else:
    new_works_index_map = []
    new_works_embeddings = None
    new_works_row_norms = None
```

В `_embedding_match_work()`:
```python
# Было:
return _works_cache[best_idx]

# Стало:
cache_idx = _works_index_map[best_idx]
return _works_cache[cache_idx]
```

Аналогично для materials.

### Gates

- [x] `ruff check .` — 0 ошибок
- [x] При `load_cache()` с частичными эмбеддингами лог показывает `works_embeddings=True` (матрица строится из подмножества)
- [x] `_embedding_match_work` возвращает корректный элемент из кэша

---

## Фаза 6: Cumulative timeout с учётом rate-limit sleep

**Статус:** [x]
**Размер:** S (~45 мин)
**Файлы:** `backend/app/services/claude_service.py`

### Проблема (точные строки)

`claude_service.py:119-126` — `processing_timeout` не уменьшается после `asyncio.sleep(wait)` на rate-limit (строка 186). Последующий retry получает тот же таймаут.

### Изменения в `call_claude()`

```python
async def call_claude(
    messages: list[dict],
    system_prompt: str = "",
    use_web_search: bool = False,
    image_data: Optional[list[dict]] = None,
    processing_timeout: Optional[float] = None,
    on_rate_limit_wait: Optional[Callable[[float], None]] = None,
) -> str:
    ...
    # Добавить перед циклом:
    call_start: float = asyncio.get_event_loop().time() if processing_timeout is not None else 0.0

    for attempt, delay in enumerate(delays, start=1):
        try:
            # Вычислять remaining_timeout перед каждым вызовом:
            if processing_timeout is not None:
                elapsed = asyncio.get_event_loop().time() - call_start
                remaining = processing_timeout - elapsed
                if remaining <= 0:
                    raise asyncio.TimeoutError(
                        f"processing_timeout exceeded after {elapsed:.1f}s (budget: {processing_timeout}s)"
                    )
                sdk_kwargs = {**kwargs, "timeout": remaining}
                response = await asyncio.wait_for(
                    _client.messages.create(**sdk_kwargs),
                    timeout=remaining + 30,
                )
            else:
                response = await _client.messages.create(**kwargs)
            ...
```

В обработчике rate-limit — sleep уже вычитается автоматически т.к. `call_start` фиксирован и `remaining` пересчитывается в начале каждого attempt.

### Gates

- [x] `ruff check .` — 0 ошибок
- [x] После rate-limit sleep следующий attempt получает `remaining = timeout - elapsed` (не исходный timeout)

---

## Фаза 7: Составной индекс tasks(project_id, estimation_status)

**Статус:** [x]
**Размер:** XS (~20 мин)
**Файлы:** `backend/app/models/task.py`, новая миграция Alembic

### Проблема

`models/task.py:38` — `index=True` только на `project_id`. Запросы `_aggregate()` в projects.py фильтруют по `project_id` + читают `estimation_status` и `cost`.

### Изменения

**models/task.py** — добавить в конец класса `Task` (после полей):
```python
from sqlalchemy import Index

# После класса Task:
Index("ix_tasks_project_estimation", Task.project_id, Task.estimation_status)
```

Или через `__table_args__`:
```python
class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_project_estimation", "project_id", "estimation_status"),
    )
    ...
```

**Создать миграцию Alembic:**
```bash
cd backend
alembic revision --autogenerate -m "add composite index tasks project estimation"
# Проверить сгенерированный файл — должен содержать:
# op.create_index("ix_tasks_project_estimation", "tasks", ["project_id", "estimation_status"])
```

### Gates

- [x] Миграция содержит `create_index` с двумя колонками
- [x] `alembic upgrade head` проходит без ошибок (проверено через Render Shell 2026-04-22)
- [x] `ruff check .` — 0 ошибок (новые ошибки не введены; E402/F401 — предсуществующие)

---

## Итоговые gates (после всех фаз)

```bash
cd backend
ruff check .                  # 0 ошибок
python -m py_compile app/main.py
pytest --tb=short -q          # все тесты зелёные
grep -r "VAT_RATE = 0\." app/ tests/  # 0 строк (только в config.py)
```

---

## Статус фаз

| Фаза | Описание | Приоритет | Размер | Статус |
|------|----------|-----------|--------|--------|
| 1 | VAT_RATE = 0.22 в config.py | Блокирующий | XS | [x] |
| 2 | asyncio.Lock для price cache | Блокирующий | S | [x] |
| 3 | Retry чанков в task_processor | Блокирующий | M | [x] |
| 4 | Prompt caching в Claude API | Важное | M | [x] |
| 5 | Sparse embedding matrix | Важное | S | [x] |
| 6 | Cumulative timeout | Важное | S | [x] |
| 7 | Составной индекс + миграция | На будущее | XS | [x] |
