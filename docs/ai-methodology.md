# Методология использования ИИ в smeta-ai

Техническая документация: где, как, какими командами и в каком порядке сервис обращается к Claude API. Актуально на 2026-07-15.

---

## 1. Общая модель работы

Весь ИИ в сервисе — это **одна модель Anthropic Claude**, вызываемая через единственную низкоуровневую функцию `call_claude`. Всё остальное (13+ точек вызова) — обёртки над ней.

| Параметр | Значение | Где задано |
|---|---|---|
| Модель | `claude-sonnet-4-6` | `claude_service.py:14` (`CLAUDE_MODEL`) |
| Temperature | `0.1` (hardcoded, не конфигурируемо) | `claude_service.py:134` |
| max_tokens | `32000` по умолчанию, `64000` для перечня из проекта | `claude_service.py:115` |
| API-ключ | `ANTHROPIC_API_KEY` из `.env` | `config.py:7` |
| Web search tool | `web_search_20250305` | `claude_service.py:54-57` |
| Prompt caching | `ephemeral` (TTL 5 мин) на system-промпте и последнем изображении | `claude_service.py:138-144`, `84-90` |
| Таймаут HTTP | connect 10s, **read 300s**, write 30s | `claude_service.py:61-68` |

**Важно:** семантический поиск по прайсу (эмбеддинги) работает **локально** через FastEmbed (`intfloat/multilingual-e5-base`, 768-мерные векторы), а не в облаке. Комментарии в коде про Cohere/OpenAI устарели — этих вызовов нет. Единственный внешний ИИ-сервис — Claude.

Каждый вызов логируется в таблицу `ApiCallLog` с разбивкой токенов (input / output / cache_read / cache_creation) и стоимостью по тарифам sonnet-4-6 (input $3, output $15, cache_read $0.30, cache_creation $3.75 за 1M токенов).

---

## 2. Ядро: функция `call_claude`

Файл: `backend/app/services/claude_service.py:106`. Единственное место, где реально вызывается `_client.messages.create()` (строки 185 и 189).

Что делает по шагам:

1. **Сборка сообщений** (`_build_messages`, стр. 76). Если есть изображения — они добавляются блоками в начало первого user-сообщения, последний image-блок помечается `cache_control: ephemeral` (кеширование страниц PDF между чанками).
2. **Сборка kwargs**: модель, `max_tokens`, `temperature=0.1`, system-промпт как кешируемый блок, опционально `tools=[web_search]`.
3. **Вызов с ретраями** (цикл по `delays = [2, 8, 30, 60]`):
   - Учёт оставшегося времени `processing_timeout` (бюджет уменьшается с учётом sleep при rate-limit).
   - `asyncio.wait_for` вокруг `messages.create` — отмена корутины по оставшемуся бюджету.
4. **Проверка обрезки**: если `stop_reason == "max_tokens"` → `ValueError("Ответ слишком большой, разбейте выполнение на подэтапы")`.
5. **Извлечение ответа**: берётся **последний** текстовый блок, содержащий `{`. Это критично для web search — Claude выдаёт несколько блоков (промежуточные рассуждения + финальный JSON), и склеивать их нельзя.
6. **Логирование** токенов и стоимости в `ApiCallLog`.

**Политика ретраев:**
- **429 (rate limit)**: экспоненциальный backoff, минимумы `[60, 120, 240]` секунд, потолок 900с.
- **5xx / сетевые ошибки**: задержки 2 / 8 / 30 / 60с.
- **Невалидный JSON**: 1 повтор с явной инструкцией вернуть чистый JSON (уровень выше — см. `_call_claude_json`).
- **Нулевой баланс API**: понятное сообщение пользователю.

### Иерархия обёрток (в `task_processor.py`)

```
call_claude (claude_service)
 └─ _call_claude_json (707)                 ← парсит JSON, 1 повтор на не-JSON
     ├─ _call_claude_json_with_retry (744)  ← до 3 попыток, паузы 5/15/30с
     └─ _interruptible_claude_json (642)     ← оборачивает в asyncio.Task,
         └─ _interruptible_..._retry (788)      опрос отмены пользователем каждые 10с
```

`_interruptible_*` применяются в долгих задачах, где пользователь может нажать «Стоп» (проверка `status == "cancelled"` в БД каждые 10 секунд).

---

## 3. Системный промпт (общий для всех задач)

`SYSTEM_BASE` — `task_processor.py:35-45`:

> «Возвращай ТОЛЬКО чистый JSON без markdown/backticks. Ты — эксперт по строительному сметному делу в России. Используй актуальные нормы ФЕР/ТЕР/ГЭСН. При указании цен ссылайся на источник.»

Передаётся как кешируемый блок при каждом вызове. Задачи ценообразования и оптимизации имеют дополнительные локальные system-промпты.

---

## 4. Типы задач и порядок применения ИИ

Тип хранится строкой в `Task.task_type`. Канонический список — `constants.py:6-13`. Диспетчеризация — `TaskProcessor.process()` (`task_processor.py:856-871`).

| task_type | Название | ИИ | Web search | Vision |
|---|---|---|---|---|
| `LIST_FROM_GRAND` | Перечень из Гранд-сметы | да | нет | нет |
| `LIST_FROM_PROJECT` | Перечень из проекта | да | нет | **да** |
| `CHECK_LIST_COMPLETENESS` | Проверка полноты перечня | да | нет | нет |
| `CHECK_PROJECT_COMPLETENESS` | Проверка полноты (по проекту) | да | нет | нет |
| `ESTIMATE_FROM_LIST` | Смета из перечня | да | **да** | нет |
| `ESTIMATE_OPTIMIZATION` | Оптимизация сметы | да | да (часть шагов) | **да** |

Стадии воркфлоу проекта: `list → completeness → estimate → optimization` (маппинг `TASK_TYPE_TO_STAGE`, `constants.py:32`).

---

### 4.1. LIST_FROM_GRAND — Перечень из Гранд-сметы

Хендлер: `_handle_list_from_grand` (`task_processor.py:900`). Разветвляется на xlsx/pdf (оба сразу запрещены).

**Вход:** один файл `.xlsx` **или** `.pdf` (скан).

**Ветка XLSX** (`_handle_list_from_grand_xlsx:924`):
1. Парсинг `parse_xlsx_grand` (`file_parser.py:137`) — умное определение колонок «Наименование / Ед.изм. / Кол-во», отбрасывание служебных строк (итоги, НР/СП/ФОТ, шифры расценок, заголовки).
2. Разбивка на чанки по 250 строк с откатом границы к началу работы (`chunk_rows`).
3. **ИИ по каждому чанку**: промпт `PROMPT_LIST_FROM_GRAND` (стр. 51), web_search=False. Задача — извлечь позиции «как есть», порядок «Работа → её материалы».
   Выход JSON: `{"items":[{type, name, unit, quantity, notes}]}`.
4. Аккумуляция → `normalize_items` → `generate_list` (xlsx из 4 листов) → `_create_initial_generic_version` (версия V0).

**Ветка PDF** (`_handle_list_from_grand_pdf:1052`):
1. **Постраничный OCR** (`extract_single_page`): сначала embedded-текст PyMuPDF, иначе Tesseract `rus+eng` (dpi 150). Прогресс сохраняется постранично → resume после рестарта.
2. Чанки по 8 страниц.
3. **ИИ**: промпт `PROMPT_LIST_FROM_GRAND_PDF` (стр. 89) — с поправкой на артефакты OCR.

**Устойчивость:** чекпоинты `progress_data` после каждого чанка/страницы; при «Стоп»/ошибке — частичный xlsx (слот `partial_N`). `items` сохраняются в `progress_data` (нужны следующим стадиям).

---

### 4.2. LIST_FROM_PROJECT — Перечень из проекта (Vision, 2 прохода)

Хендлер: `_handle_list_from_project` (`task_processor.py:1306`). Единственная задача-перечень, где ИИ **смотрит на чертежи**.

**Вход:** PDF проектной документации.

Порядок:
1. `chunk_project_pdf` (`pdf_text_extractor.py`): страницы с ≥30 слов текста → текст; чертежи/сканы → PNG image-блоки (dpi 200, ≤7500px). Чертежи вкладываются в **каждый** текстовый чанк — нужны для расчёта объёмов.
2. **Проход 1** (стр. 1342): по каждому чанку — Claude Vision, промпт `PROMPT_LIST_FROM_PROJECT` (стр. 152), `max_tokens=64000`, `processing_timeout=1200s`. Извлекает работы+материалы, объёмы по приоритету: явные из спецификации → рассчитанные по чертежу (с формулой в notes) → `null`. Дедупликация по (name, type).
3. **Проход 2** (стр. 1402): только для позиций с `quantity=null`. Чанки по 15, промпт `PROMPT_LIST_FROM_PROJECT_PASS2` (стр. 201) — «открой указанный лист и посчитай». Строгий запрет придумывать числа. Успешно посчитанные помечаются `_calculated=True`.
4. `normalize_items` → `generate_list` → xlsx → V0.

---

### 4.3. CHECK_LIST_COMPLETENESS / CHECK_PROJECT_COMPLETENESS — Проверка полноты

Хендлеры: `_handle_check_completeness` (`:1223`) и `_handle_check_project_completeness` (`:1473`).

**Вход:** не файл, а `user_prompt` = ID исходной задачи-перечня; `items` берутся из её `progress_data`.

Порядок:
1. Разбивка по границам «Работа», max 25 позиций (`_chunk_by_work_boundaries`).
2. **ИИ**: промпт `PROMPT_CHECK_COMPLETENESS` (стр. 118) / `PROMPT_CHECK_PROJECT_COMPLETENESS` (стр. 241). Задача — сверить материалы с нормативной базой ГЭСН-2017/ФСНБ-2022: добавить недостающие, скорректировать объёмы по нормам, обосновать в `notes`. web_search=False, `processing_timeout=1200s`, прерываемые вызовы.
   Выход: `{"items":[...], "changes_summary":"..."}`.
3. `generate_list(..., changes_summary=...)` — xlsx, где резюме изменений попадает на лист «Пояснительная записка».

Разница между двумя типами — только источник (перечень из Гранд-сметы vs из проекта) и промпт.

---

### 4.4. ESTIMATE_FROM_LIST — Смета из перечня (ключевой, дорогой)

Хендлер: `_handle_estimate_from_list` (`task_processor.py:1556`). **Единственная** задача с реальным web search как основным механизмом. Стоимость ~$10 за смету, ~68% — cache_creation от web search.

**Вход (2 пути):**
- **Path A**: `.xlsx` с листом «Перечень» → `parse_list_sheet`.
- **Path B**: `user_prompt` = JSON `{path:"B", source_task_id, source_stage}` → items из другой задачи.

**Порядок — 3 шага + чекпоинт:**

**Шаг 1. Поиск цен по прайсу БЕЗ ИИ** (стр. 1639-1807). Для каждой позиции последовательно:
1. exact-match по корпоративному прайсу;
2. батч-эмбеддинг (локальный FastEmbed) по прайсу;
3. exact-match по `price_cache` (кеш прошлых задач);
4. батч-эмбеддинг по `price_cache`.
Источник фиксируется: «Прайс» / «Кеш».

**Шаг 2. Claude для ненайденных** (стр. 1809). Чанки по границам «Работа» (max 10). Промпт `PROMPT_ESTIMATE_FROM_LIST` (стр. 274), **web_search=True**, `processing_timeout=1200s`:
- найти 3 рыночные цены по Екатеринбургу, взять среднюю;
- цены **без НДС** (делить на 1.22);
- вернуть результат для каждого `id` (пропуски запрещены), null/0 запрещены.
Затем ретраи: пропущенные id (батчи по 5) и позиции с null/0 (батчи по 5). Найденные цены сохраняются в `price_cache`. Источник = «Интернет».

**Чекпоинт** `_stage="pre_excel"` в отдельной сессии (resume сразу на шаг 3).

**Шаг 3. Сборка** (`_run_estimate_step3:1972`): items в исходном порядке (Прайс / Кеш / Интернет / «Цена не определена»), `generate_estimate_xlsx` → лист «Смета» с итогами (работы + накладные 3% + материалы + транспорт 3% = ИТОГО). `Task.cost = grand_total`, `estimation_status="estimated"`.

**Доп. операция `fix_empty_prices`** (`_fix_empty_prices:2257`): фоновый дозаполнитель пустых цен — батчи по 5 через тот же промпт + web search, пересборка xlsx.

---

### 4.5. ESTIMATE_OPTIMIZATION — Оптимизация сметы

Загрузка: `_handle_estimate_optimization` (`task_processor.py:2126`). Сама оптимизация — в роутере `estimate_versions.py` (веб-редактор), запускается пользователем пошагово.

**Вход:** основная смета (xlsx) + опционально файлы заказчика (Смета / Проект / ТЗ / Другое).

Порядок при загрузке:
1. `parse_estimate_excel` — определение типа строки (work/material/section), связка материалов с работами.
2. **ИИ-обогащение нормами** `_enrich_rows_with_gesn_norms` (стр. 2079): промпт `PROMPT_ENRICH_NORMS` (стр. 331), чанки по 25, web_search=False, `processing_timeout=120s`. Добавляет `qty_per_work_unit` и `norm_reference`. Ошибки ИИ **не блокируют** импорт.
3. Создаётся `EstimateVersion` V0 «Исходная смета» (+ «Смета заказчика»). `estimation_status="optimized"`.

**ИИ-оптимизация — 4 шага** (`_run_optimization_step`, `estimate_versions.py:637`), каждый рождает новую версию сметы:

| Эндпоинт | Версия | Что делает | Web search |
|---|---|---|---|
| `.../optimize/completeness` | V1 «Полнота» | проверка по ГЭСН, добавление недостающего | нет |
| `.../optimize/redundancy` | V2 «Лишнее» | дубли, нормативное включение, позиции вне проекта | нет |
| `.../optimize/technology` | V3 «Технологии» | ABC-анализ (группа А ≈80% суммы), техзамены | нет |
| `.../optimize/materials` | V4 «Материалы» | ABC-анализ материалов, замена/закупочная оптимизация | нет |

Все шаги: `processing_timeout=180s`, формат `{proposals:[{proposal_type, economy_rub, confidence, ...}]}`, авто-применение предложений, учёт контекста файлов заказчика через Vision (`_load_client_context:566` — Проект/ТЗ как image/document-блоки).

Дополнительно:
- `.../optimize/fill-prices` (`_run_fill_prices_step:956`) — проставить цены, **web search**, свой system-промпт `_FILL_PRICES_SYSTEM`.
- `.../optimize/custom` (`optimize_custom:1216`) — кастомная оптимизация выбранных строк, web search.

---

## 5. Прочие точки вызова ИИ (вне основного диспетчера)

| Где | Что делает | Web search |
|---|---|---|
| `tasks.py:1657` `reprice_estimate_item` | переоценка одной позиции сметы (синхронно) | да |
| `price_service.py:451` `_web_search_work_price` | web-поиск цены работы (легаси-путь оптимизации) | да |
| `price_service.py:489` `_web_search_material_price` | web-поиск цены материала | да |

---

## 6. Промпты: где хранятся

**Промпты задач** — строковые константы в шапке `task_processor.py`:

| Константа | Строки | Назначение |
|---|---|---|
| `SYSTEM_BASE` | 35 | Базовый system-промпт |
| `PROMPT_LIST_FROM_GRAND` | 51 | Извлечь позиции из xlsx |
| `PROMPT_LIST_FROM_GRAND_PDF` | 89 | То же из OCR-текста |
| `PROMPT_CHECK_COMPLETENESS` | 118 | Проверка полноты (перечень) |
| `PROMPT_LIST_FROM_PROJECT` | 152 | Перечень из проекта (Vision) |
| `PROMPT_LIST_FROM_PROJECT_PASS2` | 201 | Дозаполнение объёмов |
| `PROMPT_CHECK_PROJECT_COMPLETENESS` | 241 | Проверка полноты (проект) |
| `PROMPT_ESTIMATE_FROM_LIST` | 274 | Рыночные цены (web search); подставляются `{current_date}`, `{unmatched_items_json}` |
| `PROMPT_ENRICH_NORMS` | 331 | Нормы расхода ГЭСН |

**Промпты оптимизации** — внутри функций `estimate_versions.py`: `RESPONSE_FORMAT` (654), `step_prompts` (669: completeness/redundancy/technology/materials), `_PROMPT_FILL_PRICES` (912) + `_FILL_PRICES_SYSTEM` (946), инлайн-промпт `optimize_custom` (1235).

**Прочие инлайн-промпты**: `tasks.py:1637` (reprice), `price_service.py:435/474` (web-поиск цен).

---

## 7. Сквозной пайплайн (поток данных)

```
[Пользователь] → POST-эндпоинт (routers/tasks.py)
   → создаётся Task + файлы в TaskInputFile
   → BackgroundTasks.add_task(_run_task_in_background)

_run_task_in_background (tasks.py:163)  ← своя DB-сессия, до 3 ретраев на обрыв
   → process_task → TaskProcessor.process() (833)
        → status="processing", heartbeat каждые 30с
        → диспетчер по task_type (856)

   Общий конвейер каждого типа:
     1. Загрузка входа   — _load_input_files (из TaskInputFile)
     2. Парсинг          — parse_xlsx_grand / OCR / chunk_project_pdf / parse_list_sheet
     3. Чанкинг          — chunk_rows / chunk_pdf_pages / _chunk_by_work_boundaries
     4. [ESTIMATE] поиск по прайсу+кешу (exact + локальный эмбеддинг) — БЕЗ ИИ
     5. Вызов Claude по чанкам (web search / vision по типу), чекпоинты в progress_data
     6. Постобработка    — normalize_items, дедуп, retry пустых/пропущенных цен
     7. Генерация файла  — generate_list / generate_estimate_xlsx
     8. save_result (TaskResult) + EstimateVersion V0

   → _auto_fill_estimate_slot (541): result → estimate, извлечение cost
   → status="completed"
```

**Эндпоинты, запускающие ИИ** (`routers/tasks.py`):
- `POST ""` — создание задачи
- `POST /check-completeness`, `POST /check-project-completeness`
- `POST /{id}/resume`, `POST /{id}/restart`, `POST /{id}/message`
- `POST /{id}/optimize/run` (легаси), `.../fix-empty-prices`, `.../reprice`
- `POST /{id}/optimize/analyze` — **без ИИ** (только ABC-парсинг)

**Эндпоинты редактора** (`routers/estimate_versions.py`): `.../optimize/{completeness|redundancy|technology|materials|fill-prices|custom}`.

---

## 8. Модели БД, связанные с ИИ

- **`Task`** — `task_type`, `status` (pending→processing→completed/failed/cancelled), `progress_data` (JSONB: чекпоинты, накопленные items, `_stage`), `estimation_status`, `cost`, `user_prompt` (перегружен: ID исходной задачи / JSON-мета Path B / client_files).
- **`TaskInputFile`** — бинарные входные файлы.
- **`TaskResult`** — выходные файлы, слоты `result` / `estimate` / `partial_N` / `source` / `optimized`.
- **`EstimateVersion`** — версии сметы для редактора/оптимизации (`rows`, `optimization_proposals`, проценты накладных/транспорта).
- **`PriceCacheWork` / `PriceCacheMaterial`** — кеш найденных ИИ рыночных цен (переиспользуется в ESTIMATE_FROM_LIST, хранит эмбеддинг).
- **`ApiCallLog`** — лог каждого вызова Claude (токены + `cost_usd`).

---

## 9. Сквозные механизмы надёжности

- **Отменяемость**: `_check_cancelled` опрашивает `status=="cancelled"` каждые 10с в долгих вызовах.
- **Resume**: `progress_data` (chunks_done / items / OCR-страницы / `_stage`) — обработка продолжается с места остановки после рестарта инстанса; частичные результаты — `partial_N`.
- **Ретраи**: rate-limit backoff 60/120/240с (потолок 900с); сетевые 2/8/30/60с; невалидный JSON — 1 повтор; chunk-level — 3 попытки с паузами 5/15/30с.
- **Защита от обрезки**: `stop_reason == max_tokens` → явная ошибка «разбейте на подэтапы».
- **Кеширование**: system-промпт и последний image-блок помечаются `ephemeral` → экономия на повторных чанках в пределах 5-минутного окна.

---

## 10. Ключевые выводы

1. Одна модель `claude-sonnet-4-6`, `temperature=0.1` — зашито в коде, не настраивается.
2. Единственная точка API — `claude_service.call_claude`; всё остальное — обёртки.
3. Web search включается только в ценообразовании (ESTIMATE_FROM_LIST, fix_empty_prices, fill_prices, custom, reprice, легаси price_service).
4. Vision (чертежи) — в LIST_FROM_PROJECT (оба прохода) и в оптимизации (файлы заказчика).
5. Эмбеддинги — локальные (FastEmbed e5-base), облачных эмбеддинг-вызовов нет.
6. `max_tokens` = 32000 везде, кроме LIST_FROM_PROJECT (64000).
