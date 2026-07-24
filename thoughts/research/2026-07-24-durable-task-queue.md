# Research: durable-очередь задач для мультиюзера

**Дата:** 2026-07-24
**Задача:** несколько пользователей (до 3 активных) ставят несколько задач (до 20 каждый) — задачи реально обрабатываются параллельно, не теряются при рестарте, не блокируют друг друга.
**Режим:** read-only research. Кода не меняем.

---

## 1. Что есть сейчас (карта кодовой базы)

### 1.1. Постановка задач — fire-and-forget, не durable
- Задача создаётся в БД со `status="pending"`, затем `background_tasks.add_task(_run_task_in_background, task_id)` — FastAPI in-process BackgroundTasks.
- **7 продьюсеров** зовут `_run_task_in_background`: `tasks.py:358,454,570,684,718,757`, `workflow_cards.py:616`.
- **+4 вспомогательных раннера** тоже через `add_task`: optimization (`tasks.py:1513`), fix_empty_prices (`tasks.py:1573`), version-steps (`estimate_versions.py:875,1200`), retraining (`retraining.py:144`).
- Раннер `_run_task_in_background` (`tasks.py:163`): открывает свою `AsyncSessionLocal`, зовёт `process_task` → `TaskProcessor.process()` (`task_processor.py:1060`), ретраит 3× только транзиентные обрывы коннекта.
- **Проблема:** BackgroundTasks живут в памяти web-процесса. Рестарт/редеплой/краш → всё «в полёте» теряется.

### 1.2. Состояние задачи УЖЕ персистентно в БД
- `Task.status` (свободная строка, не enum): `pending / processing / completed / failed / paused / cancelled`. (`models/task.py:29`)
- `Task.progress_data` (JSONB) — чекпоинты: `_stage` (`pre_excel/claude_partial/pass1/pass1_done/batch_pending/...`), `batch_id`, `chunks_done`, `ocr_pages`. `_stage`/`batch_id` спрятаны в JSON (не индексируются, фильтруются в Python). (`checkpoint.py`, `batch_poller.py:33-37`)
- Есть идемпотентный resume с чекпоинта (`resume_from_batch`, `has_resumable_checkpoint`).
- **Вывод:** durable-очередь может опираться на существующую модель Task. Отдельная таблица job не обязательна. В payload очереди достаточно `task_id` — всё состояние (включая входные файлы `Task.input_file_data`) уже в строке.

### 1.3. Три механизма «самодельной durability» — их надо перенести/заменить
1. `_recover_stuck_tasks` (`main.py:91`): на старте помечает все `processing` (кроме `batch_pending`) как `failed`. При durable-очереди заменяется на reclaim по visibility-timeout.
2. `poll_batch_tasks` (APScheduler, 60с, `max_instances=1`): дочитывает Anthropic Message Batches (`_stage=batch_pending`). **Оставить — внешнее состояние у Anthropic.**
3. `resume_paused_tasks` (APScheduler, 10 мин): авто-возобновляет `paused` (исчерпан баланс). **Оставить.** ⚠️ Внутри уже есть атомарный claim: `UPDATE ... WHERE id=? AND status='paused' SET status='pending'` + `rowcount==1` (`resume_poller.py:46-59`) — это готовый образец claim-паттерна для очереди.

### 1.4. CPU-bound работа, блокирующая event loop (морозит всех)
На loop в пути TaskProcessor (НЕ обёрнуто в executor):
1. `chunk_project_pdf` — рендеринг PNG всех страниц проектного PDF (`task_processor.py:1578`, PyMuPDF) — **самый тяжёлый**.
2. Генерация xlsx (openpyxl) — ~10 точек (`generate_list`, `generate_estimate_xlsx`, `task_processor.py:1133,1201,...,2691`).
3. `parse_file` (openpyxl + PIL downscale) — `task_processor.py:615`.
4. `parse_xlsx_grand`, `parse_xlsx_to_generic_rows`, `parse_list_sheet` — `task_processor.py:528,595,1173,1951`.
Уже off-loop (образец): OCR/`extract_single_page`, эмбеддинги, обучение — через `asyncio.to_thread`.
WeasyPrint PDF (`pdf_service.py:318`, `pdf_exporter.py:23`) и xlsx-экспорты в роутерах — тоже sync на loop, но это web-эндпоинты, не TaskProcessor.
**Вывод:** вынос обработки в отдельный worker-процесс решает это радикально — CPU worker'а не влияет на web. Внутри worker'а тяжёлые sync-вызовы всё равно стоит держать в `to_thread`, чтобы не морозить конкурентные задачи в самом worker'е.

### 1.5. Инфраструктура
- `database.py`: **asyncpg**, пул `pool_size=5, max_overflow=10, pool_pre_ping, pool_recycle=1800`. ⚠️ Пул 5+10 — узкое место при росте конкурентных задач; при N воркерах поднять.
- `Dockerfile` CMD: `alembic upgrade head && uvicorn ...`. Миграции гонятся ещё и в `main.py:125` lifespan. ⚠️ При отдельном worker — гонка миграций, мигрировать должен один сервис.
- Concurrency-константы захардкожены в `task_processor.py:40` (`FAST_CHUNK_CONCURRENCY=4`), `:43` (`ESTIMATE_MAIN_CHECKPOINT_GROUP=8`). ⚠️ Вынести в Settings/env.
- Alembic: линейная цепочка `NNN_slug.py`, head = **029**. Следующая — `030_`.
- requirements: fastapi, uvicorn, sqlalchemy[asyncio]==2.0.36, asyncpg==0.30, alembic, apscheduler. **Ничего для очередей нет** (ни celery/arq/procrastinate/redis).

### 1.6. 🚩 БЛОКЕР: нет идентификации по пользователю
- Таблица `users` = только `id, role('user'/'admin'), password_hash`. **Нет индивидуальных пользователей.** `_initialize_users` создаёт ровно 2 записи из env `USER_PASSWORD`/`ADMIN_PASSWORD` (`main.py:64`).
- Логин по паролю → JWT с `sub=role, role=role` (`auth.py`). **`sub` = роль, а не человек.**
- `Task` имеет `user_role: String(10)`, но **нет `owner_id`/`created_by`**.
- **Следствие:** «честность по пользователям» (round-robin, чтобы юзер с 20 задачами не блокировал других) **сейчас невозможна** — система не различает трёх людей, вошедших под одним паролем `user`. Это надо решить ДО реализации fairness.

---

## 2. Внешние решения (best-practice)

### 2.1. Технология очереди на Postgres: procrastinate vs DIY SKIP LOCKED
- **SKIP LOCKED** — нативный движковый паттерн Postgres для очередей: воркеры конкурентно берут строки, не блокируя друг друга; **краш воркера → транзакция откатывается → job возвращается в pending автоматически**. Требует композитный индекс под claim-запрос и КОРОТКУЮ транзакцию (иначе тормозит vacuum).
  - ⚠️ Важно для нас: наши задачи длинные (минуты–час). **Нельзя** держать row-lock всю задачу. Правильно: короткий атомарный claim (`UPDATE ... SET status=processing, worker_id, claimed_at WHERE id=(SELECT ... WHERE status=pending ORDER BY <fairness> FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING`), лок отпускается сразу, задача бежит вне транзакции, зависшие возвращаются по visibility-timeout (`claimed_at` + heartbeat). Это ровно паттерн, уже применённый в `resume_poller._claim`.
  - ⚠️ SKIP LOCKED сам НЕ обеспечивает «не больше N одновременно» и fairness — это делается на уровне приложения (число слотов воркера + `ORDER BY` в claim).
- **procrastinate** — зрелая Postgres-очередь (SKIP LOCKED + LISTEN/NOTIFY), sync/async, периодические задачи, ретраи, локи. Но: своя таблица job + декораторы + свой worker CLI = **второй источник правды** рядом с существующим `Task.status`; больше поверхности миграции; нет дашборда.

**Вывод по технологии:** для ЭТОГО кода выигрывает **DIY-claim на существующей таблице `tasks`** (атомарный UPDATE + visibility-timeout). Причины: (1) уже есть полноценная персистентная стейт-машина Task с чекпоинтами и готовым claim-паттерном; (2) ноль новых зависимостей; (3) нет дублирующей стейт-машины; (4) наш масштаб (≤60 задач, длинные job) тривиален для поллинга — throughput LISTEN/NOTIFY не нужен. procrastinate был бы оправдан на greenfield или высоком throughput.

### 2.2. Timeweb App Platform — деплой
- **App Platform поддерживает Docker Compose:** несколько контейнеров из одного `docker-compose.yml` в корне. **Проксирование (домен) — только у ПЕРВОГО сервиса**; остальные доступны по порту. Воркеру HTTP-прокси не нужен → web ставим первым, worker вторым.
- **Тарификация — за App (конфигурацию сервера) целиком**, не за контейнер. Значит **web + worker в одном compose = один App = один тариф**, а не два платных приложения. (Это дешевле, чем отдельные App на web и worker.)
- **Запрещены `volumes`, `privileged`, `network_mode: host` и др.** → контейнерный Postgres в compose нельзя (потеряет данные) → **обязательно managed PostgreSQL (DBaaS Timeweb)**.
- Итоговые платные единицы: **1 App (web+worker) + managed Postgres + static-фронтенд.**
- ⚠️ Нужен отдельный прод-`docker-compose.yml` без `volumes` и `--reload` (локальный использует и то, и другое).

---

## 3. РЕКОМЕНДАЦИЯ (вывод research)

> **Уточнение в плане:** research рекомендовал очередь прямо на таблице `tasks`, но план осознанно выбрал **отдельную таблицу `jobs`** (см. Challenge Log п.3) — потому что 4 вспомогательных раннера работают над НЕ-Task сущностями (версии сметы, training_job), и единый механизм без отдельной таблицы невозможен. Claim-паттерн (SKIP LOCKED + visibility-timeout) остаётся тем же.

**Архитектура:**
1. **Очередь = атомарный claim по SKIP LOCKED + visibility-timeout heartbeat.** Без новых зависимостей и брокеров. (Носитель — отдельная таблица `jobs`, см. уточнение выше.)
2. **Отдельный worker-процесс** (та же кодовая база/образ, другая команда запуска): цикл claim → `TaskProcessor.process` → done. Пул воркеров даёт реальный параллелизм; вся CPU-работа (xlsx/PDF/OCR) уходит с web.
3. **Web больше не обрабатывает** — продьюсеры только создают строку `pending` (убрать 7+4 `add_task`). Убрать `_recover_stuck_tasks`.
4. **Глобальный лимит 3–6** = число слотов воркера (env-настраиваемое). Внутризадачный `FAST_CHUNK_CONCURRENCY` вынести в env и, вероятно, снизить при множестве параллельных задач (защита от 429 Anthropic).
5. **Поллеры `batch`/`resume` + cleanup** переезжают в worker (или отдельный scheduler-слот) с `max_instances=1` — чтобы при масштабировании web не было дублей.
6. **Deploy Timeweb:** один App через Docker Compose (web-контейнер первый + worker-контейнер) + managed Postgres. Прод-compose без `volumes`. Миграции гонит один сервис (web на старте), из worker убрать.
7. **Поднять пул asyncpg** (5+10 → выше) под число воркеров.

**🚩 Требует решения пользователя (блокер fairness):**
Fairness «по пользователям» невозможна без идентификации людей. Варианты — см. вопрос в плане. Без этого решения п. «round-robin по юзерам» вырождается в FIFO или round-robin по роли.

---

## 4. Открытые вопросы для Stage 3 (план)
1. **Идентификация/fairness:** добавлять реальные per-user аккаунты (owner_id) или fairness по client-id / по роли / FIFO? (влияет на схему БД и scope)
2. Один worker-контейнер с N async-слотами или несколько worker-контейнеров? (для ≤60 задач и I/O-bound — вероятно 1 контейнер, N слотов; CPU-пики через to_thread)
3. Что делать с 4 вспомогательными раннерами (optimization/fix-prices/version-steps/retraining) — гнать через ту же очередь или оставить как есть?
4. Нужен ли приоритет batch vs fast, или общий FIFO с fairness достаточно?
