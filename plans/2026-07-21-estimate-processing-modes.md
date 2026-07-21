# План: Режимы обработки ESTIMATE_FROM_LIST — «быстро» (asyncio.gather) и «долго» (Batch API)

**Статус:** planning
**Дата:** 2026-07-21
**Тип задачи затронут:** `ESTIMATE_FROM_LIST` (и общие чанк-циклы `LIST_FROM_*`, `fix_empty_prices` в fast-режиме)

---

## Spec (WHAT & WHY)

**Проблема.** Ценообразование ненайденных позиций в `ESTIMATE_FROM_LIST` шлётся в Claude чанками **последовательно** ([task_processor.py:1884-1891](../backend/app/services/task_processor.py#L1884-L1891)), каждый чанк с web search и таймаутом до 20 мин. Смета с десятками ненайденных позиций считается десятки минут. При этом стоимость сметы ~$10, и её основная доля — токены web search (см. память проекта `project_estimate_token_economics`).

**Цель.** При создании задачи `ESTIMATE_FROM_LIST` пользователь выбирает режим:
- **«быстро» (`fast`)** — чанки идут параллельно через `asyncio.gather` с ограничением конкурентности. Минимизирует время ожидания.
- **«долго» (`batch`)** — все чанки уходят одной пачкой в Anthropic Message Batches API. **−50% стоимости** на все токены + устойчивость к рестартам (batch считается на серверах Anthropic).

**Acceptance Criteria.**
1. В форме создания задачи ([TaskCreate.tsx](../frontend/src/pages/TaskCreate.tsx)) для `ESTIMATE_FROM_LIST` есть переключатель fast/batch (по умолчанию `fast`).
2. `processing_mode` доезжает от фронта до `Task` и доступен в `TaskProcessor`.
3. **fast:** все последовательные чанк-циклы задачи выполняются параллельно с `Semaphore` (по умолчанию 4); результат по позициям идентичен последовательному прогону.
4. **batch:** чанки отправляются через Batch API; `ApiCallLog` для batch считает стоимость по **уполовиненным** тарифам; итоговая смета собирается корректно.
5. **batch устойчив к рестарту:** если процесс FastAPI перезапустился, пока batch считается, задача **не** помечается `failed`, а дочитывается отдельным поллером.
6. Отмена задачи в batch-режиме отменяет batch (`batches.cancel`).
7. Существующие задачи и другие типы задач не ломаются (регрессия зелёная).

**Non-Goals.**
- Не меняем логику матчинга по корпоративному прайсу (шаг 1) и сборку Excel (шаг 3).
- Не вводим Celery/внешнюю очередь — поллер живёт как asyncio-корутина в процессе FastAPI (как и вся текущая обработка).
- Batch-режим не добавляем для `ESTIMATE_OPTIMIZATION` и прочих типов в этой итерации (только `ESTIMATE_FROM_LIST`).

---

## Challenge Log

**Chosen solution.** Одно новое поле `Task.processing_mode`; ветвление режима в шаге 2 `ESTIMATE_FROM_LIST`; fast = `asyncio.gather` + `Semaphore`; batch = submit-and-defer + отдельный периодический поллер, дочитывающий результаты.

**Alternatives considered.**
1. *Batch-поллинг внутри той же корутины задачи + resume при старте* — отклонено (выбор пользователя): корутина висела бы до 24 ч, а resume-логика в `_recover_stuck_tasks` сложнее в поддержке. Отдельный поллер чище разделяет «submit» и «collect».
2. *Batch без отдельного поля, режим в `progress_data`* — отклонено: `progress_data` перезаписывается чекпоинтом в процессе обработки ([task_processor.py:1958](../backend/app/services/task_processor.py#L1958)), режим надо читать надёжно до старта. Типизированная колонка безопаснее.
3. *Только batch, без fast* — отклонено: batch не решает скорость (задержка до 1 ч непредсказуема). Для интерактивного ожидания нужен параллелизм. Два режима покрывают оба сценария.

**Почему выбранное лучше.** `Semaphore`-параллелизм даёт скорость без риска выбить rate-limit (существующая ретрай-обвязка [claude_service.py:265-321](../backend/app/services/claude_service.py#L265-L321) сохраняется). Отдельный поллер использует уже имеющийся чекпоинт-механизм (`progress_data._stage`, [task_processor.py:1568-1579](../backend/app/services/task_processor.py#L1568-L1579)) → batch переживает рестарт «бесплатно», без новой инфраструктуры очередей.

---

## Problems

| # | Проблема | Решение | Статус |
|---|---------|----------|--------|
| 1 | `progress_data` перезаписывается чекпоинтом — режим там хранить нельзя | Отдельная колонка `Task.processing_mode` (String(10), default `fast`) + миграция 029 | ✅ done |
| 2 | fast: `_call_claude_chunk` мутирует общий `claude_results` из нескольких корутин | Каждый чанк пишет по своим `id` (без пересечения ключей); asyncio однопоточный — гонок на dict между await нет. Проверить пост-мерджем | pending |
| 3 | fast: параллельные чанки могут выбить TPM/RPM | `asyncio.Semaphore(concurrency)`, дефолт 4, вынести в config; ретрай 429 уже есть | pending |
| 4 | batch: web_search в batch | `build_batch_request` переиспользует `_build_message_params` (web_search + кэш); `collect_claude_batch` ключует по custom_id | ✅ done (сервис); использование — Phase 4 |
| 5 | batch: стоимость логируется по полным тарифам sonnet | `_calc_cost(batch=True)` ×0.5 + `_log_api_call(batch=True)` | ✅ done |
| 6 | batch: `_recover_stuck_tasks` фейлит все `processing` при рестарте | `_recover_stuck_tasks` исключает `batch_pending` (`IS DISTINCT FROM`) | ✅ done |
| 7 | batch: шаг 3 (сборка Excel) сейчас вызывается сразу после шага 2 в одной корутине | Переиспользован существующий `pre_excel` resume: `resume_from_batch` собирает результаты → pre_excel-чекпоинт → `_run_estimate_step3` | ✅ done |
| 8 | batch: отмена задачи должна отменять batch | Поллер: при `status=='cancelled'` → `cancel_claude_batch` + `_stage=batch_cancelled` | ✅ done |

---

## Phases

### Phase 1: БД — поле `processing_mode` + миграция 029
- **Status:** ✅ completed (2026-07-21)
- **Files:** `backend/app/models/task.py`, `backend/alembic/versions/029_add_processing_mode_to_tasks.py`
- **Changes:**
  - В `Task` добавить: `processing_mode: Mapped[str] = mapped_column(String(10), default="fast", server_default="fast", nullable=False)` (по образцу `estimation_status`, [task.py:45-49](../backend/app/models/task.py#L45-L49)).
  - Миграция 029 (`revision="029"`, `down_revision="028"`), обязательно `IF NOT EXISTS` — образец [028_add_training_tables.py](../backend/alembic/versions/028_add_training_tables.py):
    ```python
    op.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS processing_mode VARCHAR(10) NOT NULL DEFAULT 'fast'")
    # downgrade: op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS processing_mode")
    ```
- **TDD:** тест: создание `Task` без `processing_mode` → значение `'fast'`; с `'batch'` → сохраняется.
- **Gates:** `python -m py_compile`, `pytest`, `ruff`. **Миграция создаётся ДО коммита** (правило CLAUDE.md).
- **Impact:** таблица `tasks` — аддитивно, обратно совместимо.

### Phase 2: Batch-инфраструктура в claude_service
- **Status:** ✅ completed (2026-07-21)
- **Files:** `backend/app/services/claude_service.py`
- **Changes:**
  - `async def submit_claude_batch(requests) -> batch_id` — обёртка `client.messages.batches.create(...)`; каждый `Request` с `custom_id`, `params=MessageCreateParamsNonStreaming(...)` (та же модель/tools/web_search/prompt-caching, что в `call_claude`).
  - `async def poll_claude_batch(batch_id) -> status`, `async def collect_claude_batch(batch_id) -> dict[custom_id, message]` — `retrieve` + `results`, обработка `succeeded/errored/expired/canceled`.
  - `async def cancel_claude_batch(batch_id)`.
  - Расчёт стоимости для batch: тарифы ×0.5, лог в `ApiCallLog` (переиспользовать текущий блок логирования [claude_service.py:237-257](../backend/app/services/claude_service.py#L237-L257)).
- **TDD:** unit-тесты с замоканным `AsyncAnthropic`: сборка requests с корректными custom_id; сбор результатов по custom_id при перемешанном порядке; halved-cost в логе; ветка `errored`.
- **Gates:** `py_compile`, `pytest`, `ruff`.
- **Impact:** новый код рядом с `call_claude`; существующий путь не трогаем.

### Phase 3: Fast-режим — параллелизация чанк-циклов
- **Status:** ✅ completed (2026-07-21) — ESTIMATE_FROM_LIST (3 цикла) + fix_empty_prices. **Согласованное сужение:** LIST_FROM_* оставлены последовательными (чекпоинт-resume + другие типы задач вне toggle).
- **Files:** `backend/app/services/task_processor.py`
- **Changes:**
  - Хелпер `_gather_chunks(coros, concurrency)` с `asyncio.Semaphore`; concurrency из config (дефолт 4).
  - Заменить последовательные циклы на `gather` под семафором:
    - основной цикл ненайденных [1884-1891](../backend/app/services/task_processor.py#L1884-L1891);
    - retry пропущенных id [1900-1906](../backend/app/services/task_processor.py#L1900-L1906);
    - retry null-цен [1928-1934](../backend/app/services/task_processor.py#L1928-L1934);
    - циклы `LIST_FROM_*` [1246](../backend/app/services/task_processor.py#L1246), [1496](../backend/app/services/task_processor.py#L1496);
    - `fix_empty_prices` [2295-2308](../backend/app/services/task_processor.py#L2295-L2308).
  - Ветвление по `task.processing_mode`: `fast` → gather; при `concurrency=1` поведение = старому последовательному (запасной путь).
  - Сохранить отмену: `_interruptible_claude_json_with_retry` уже проверяет отмену каждые 10с внутри каждого вызова — при gather отмена продолжает работать поштучно.
  - Прогресс: при gather `update_progress` по завершению каждой корутины (не в исходном порядке).
- **TDD:** тест — при замоканном Claude параллельный прогон даёт тот же `claude_results` по id, что и последовательный; семафор не превышает лимит; отмена в середине останавливает.
- **Gates:** `py_compile`, `pytest`, `ruff`.
- **Impact:** затрагивает несколько шагов и другие типы задач (`LIST_FROM_*`, `fix_empty_prices`) — **обязательна регрессия по всем типам** (Stage 7).

### Phase 4: Batch-режим — submit + сохранение состояния (re-entrant граница шаг2/шаг3)
- **Status:** ✅ completed (2026-07-21) — переиспользован существующий `pre_excel` resume; MVP без inline retry/null
- **Files:** `backend/app/services/task_processor.py`
- **Changes:**
  - Рефактор: выделить «подготовку чанков» и «сборку step3» так, чтобы step3 вызывался независимо, из состояния.
  - Для `processing_mode == "batch"`: после шага 0-1 (локальные, без Claude) собрать чанки, вызвать `submit_claude_batch`, записать в `progress_data`: `{_stage: "batch_pending", batch_id, custom_id_map, matched_state...}` (всё, что нужно step3), выставить `estimation_status`/статус «ожидает batch», **выйти** без step3.
  - Метод `resume_from_batch(task, batch_results)` — распарсить результаты в `claude_results`, выполнить retry null-цен (тоже batch или инлайн — решить: MVP инлайн), затем `_run_estimate_step3`.
- **TDD:** тест — batch-ветка сохраняет `batch_id` и полное состояние в `progress_data` и не вызывает step3; `resume_from_batch` из сохранённого состояния собирает корректную смету.
- **Gates:** `py_compile`, `pytest`, `ruff`.
- **Impact:** граница шаг2/шаг3 — риск для существующего fast/sequential пути; покрыть тестом, что fast по-прежнему идёт end-to-end в одной корутине.

### Phase 5: Периодический batch-поллер
- **Status:** ✅ completed (2026-07-21)
- **Files:** `backend/app/main.py`, (возм.) новый `backend/app/services/batch_poller.py`
- **Changes:**
  - Фоновая корутина, стартующая в lifespan `main.py` (рядом с текущими startup-хуками): каждые N сек (config, дефолт 60) выбирает задачи с `progress_data._stage == "batch_pending"`, для каждой `poll_claude_batch`; при `ended` → `collect_claude_batch` → `TaskProcessor(...).resume_from_batch(...)` → завершение.
  - Изменить `_recover_stuck_tasks` ([main.py:92-114](../backend/app/main.py#L92-L114)): **не** фейлить задачи с `batch_pending` — их подхватит поллер.
  - Отмена: обработчик отмены задачи вызывает `cancel_claude_batch(batch_id)`.
  - Ошибки batch (`errored`/`expired`) → пометить задачу `failed` с понятным сообщением.
- **TDD:** тест — поллер находит `batch_pending`, при `ended` дочитывает и завершает; при `errored` фейлит с сообщением; `_recover_stuck_tasks` не трогает `batch_pending`.
- **Gates:** `py_compile`, `pytest`, `ruff`.
- **Impact:** новый долгоживущий фоновый компонент; проверить, что он не гоняет БД вхолостую и корректно останавливается при shutdown.

### Phase 6: Роутер — приём `processing_mode`
- **Status:** ✅ completed (2026-07-22)
- **Files:** `backend/app/routers/tasks.py`
- **Changes:**
  - В `create_task` ([tasks.py:189-344](../backend/app/routers/tasks.py#L189-L344)) добавить `processing_mode: str = Form("fast")`; валидация `in {"fast","batch"}`; передать в конструктор `Task(...)` ([tasks.py:277-288](../backend/app/routers/tasks.py#L277-L288)).
  - batch разрешён только для `ESTIMATE_FROM_LIST` (иначе форсим `fast` + лог).
  - Отметить в плане второй путь создания — [workflow_cards.py:511](../backend/app/routers/workflow_cards.py#L511) (в этой итерации оставляем `fast`).
- **TDD:** тест эндпоинта — `processing_mode` сохраняется; невалидное значение → 422/дефолт; batch+не-ESTIMATE → fast.
- **Gates:** `py_compile`, `pytest`, `ruff`.
- **Impact:** контракт API (multipart) — аддитивно.

### Phase 7: Фронтенд — переключатель fast/batch
- **Status:** pending
- **Files:** `frontend/src/pages/TaskCreate.tsx`, `frontend/src/types/index.ts`
- **Changes:**
  - `const [processingMode, setProcessingMode] = useState<'fast'|'batch'>('fast')` (рядом с [TaskCreate.tsx:49-54](../frontend/src/pages/TaskCreate.tsx#L49-L54)).
  - Toggle-кнопки (шаблон Path-B toggle [457-486](../frontend/src/pages/TaskCreate.tsx#L457-L486)), показывать только при `taskType === 'ESTIMATE_FROM_LIST'`. Подписи: «Быстро» / «Долго (дешевле ~50%)» + короткая подсказка про задержку batch.
  - `formData.append('processing_mode', processingMode)` в `handleSubmit` (около [tasks.ts / TaskCreate.tsx:210](../frontend/src/pages/TaskCreate.tsx#L210)).
- **TDD:** тест компонента — toggle виден только для ESTIMATE_FROM_LIST; выбранный режим уходит в FormData.
- **Gates:** `tsc --noEmit`, `npm run lint`, `npm test`.
- **Impact:** UI формы; UX по brand-guidelines.

---

## Порядок и зависимости
- Phase 1 — первым (БД).
- Phase 2 — независим (batch-сервис).
- Phase 3 (fast) и Phase 4 (batch) зависят от Phase 1; Phase 4 зависит от Phase 2.
- Phase 5 зависит от Phase 4.
- Phase 6 зависит от Phase 1; Phase 7 зависит от контракта Phase 6.
Рекомендуемый линейный порядок: 1 → 2 → 3 → 4 → 5 → 6 → 7.

## Changelog

| Дата | Фаза | Изменения |
|------|------|-----------|
| 2026-07-21 | — | План создан |
| 2026-07-21 | Phase 1 | `Task.processing_mode` VARCHAR(10) default `fast` + миграция 029 (IF NOT EXISTS); 3 теста зелёные; регрессия чистая (baseline 132→135 passed). Ветка `feature/estimate-processing-modes`, коммит 9d73489 |
| 2026-07-21 | Phase 2 | `claude_service`: build/submit/poll/collect/cancel batch + `_calc_cost(batch=True)`; рефактор общих хелперов (`_build_message_params`/`_extract_result_text`/`_extract_usage`/`_log_api_call`), `call_claude` неизменен; 6 тестов; регрессия 135→141 passed. Коммит 4c82fa2 |
| 2026-07-21 | Phase 3a | Примитив `_run_chunks_parallel` (db-free воркеры + cancel-watcher); `_fetch_chunk`/`_apply_chunk_items`; 3 цикла ESTIMATE_FROM_LIST → `_process_chunks` (concurrency по `processing_mode`). 5 тестов; регрессия 141→146. Коммит 08d2b2f |
| 2026-07-21 | Phase 3b | `fix_empty_prices` → `_fetch_batch` + `_run_chunks_parallel`. Согласовано: LIST_FROM_* остаются последовательными. Регрессия 146 passed. Коммит 403fd66 |
| 2026-07-21 | Phase 4 | `_submit_estimate_batch` + `resume_from_batch` (через pre_excel resume) + диспетчеризация; общий `_cache_priced_item`. MVP без inline retry/null. 2 теста; регрессия 146→148. Коммит 6a0f850 |
| 2026-07-21 | Phase 5 | `batch_poller.py` (poll/resume/cancel) + job в scheduler (60s); `_recover_stuck_tasks` исключает batch_pending. 5 тестов; регрессия 148→153. Backend batch end-to-end. Коммит 88c40eb |
| 2026-07-22 | Phase 6 | `create_task`: Form `processing_mode` + `_resolve_processing_mode` (batch только для ESTIMATE_FROM_LIST); передача в `Task`. 5 тестов; регрессия 153→158. Коммит 0e2e49e |

---

## Итоговый блок
**Реализовано:** Phase 1-5 — backend полностью (БД, batch-инфраструктура, fast-режим, batch submit/resume, поллер). Batch работает end-to-end на бэкенде.
**Осталось:** Phase 6 (роутер — приём `processing_mode`), Phase 7 (фронтенд — toggle). Примечания: LIST_FROM_* последовательны (согласовано); batch MVP без inline retry/null (возможен Phase 4b). Открытых развилок нет — согласовано: batch-поллинг через **отдельный периодический поллер** (Phase 5); fast-режим параллелит **все** последовательные чанк-циклы задачи (Phase 3). Приоритетный риск — граница шаг2/шаг3 при batch (Phase 4) и регрессия по другим типам задач из-за параллелизации общих циклов (Phase 3).
