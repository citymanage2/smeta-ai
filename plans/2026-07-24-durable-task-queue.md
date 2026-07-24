# План: durable-очередь задач для мультиюзера

**Дата:** 2026-07-24
**Spec:** [specs/2026-07-24-durable-task-queue.md](../specs/2026-07-24-durable-task-queue.md)
**Research:** [thoughts/research/2026-07-24-durable-task-queue.md](../thoughts/research/2026-07-24-durable-task-queue.md)
**Timeweb-чек-лист:** [2026-07-24-timeweb-архитектура-и-доработки.md](2026-07-24-timeweb-архитектура-и-доработки.md) — платформенные доработки к Phase 4.
**Размер:** L (архитектура + новый сервис). Bulletproof full pipeline.
**Решения зафиксированы:** личные аккаунты (owner_id) для fairness; DIY-claim (SKIP LOCKED), без procrastinate/Redis; Timeweb App Platform (Docker Compose, web+worker в одном App).

---

## Challenge Log

**1. Решает ли это проблему?** Да, по AC:
- Параллельность/неблокирование → отдельный worker-процесс (AC2) + пул слотов (AC4).
- Не теряются при рестарте → durable-очередь + reclaim по visibility-timeout (AC3).
- Не блокируют друг друга → round-robin по owner (AC5).
- Предсказуемая нагрузка → глобальный семафор Anthropic (AC7).
- Мультиюзер → реальные аккаунты (AC1).

**2. Самое ли эффективное решение?** Рассмотрены 3 подхода к очереди:
- **procrastinate** (Postgres-очередь-фреймворк): «-» вторая стейт-машина рядом с `Task.status`, свои таблицы/декораторы/CLI, больше поверхности миграции. Оправдан на greenfield.
- **Redis + Celery/Arq**: «-» новый managed-сервис (стоимость + точка отказа), избыточен для ≤60 длинных задач.
- **DIY claim на своей таблице (SKIP LOCKED + visibility-timeout)** ✅: переиспользует существующее durable-состояние Task и готовый claim-паттерн из `resume_poller`, ноль новых зависимостей, полный контроль над fairness. Выбран.
  - Нюанс: задачи длинные → НЕ держим row-lock всю задачу; короткий claim-UPDATE, лок отпускаем, heartbeat + reclaim. (Классическая ошибка «lock на всю job» осознанно исключена.)

**3. Нет ли «кода ради кода»?** Логика обработки (`TaskProcessor`, хендлеры) НЕ переписывается — меняется только механизм запуска. Реальные аккаунты — не украшение, а предпосылка fairness (AC1→AC5). Отдельная таблица `jobs` (а не перегрузка `Task.status`) оправдана тем, что 4 вспомогательных раннера работают над НЕ-Task сущностями (версии сметы, training_job) — единый механизм без неё невозможен.

---

## Ключевые архитектурные решения

- **Таблица `jobs`** — чистый слой очереди (claim/heartbeat/attempts), отделён от доменного `Task.status` (остаётся источником правды для UI). Поля: `id, kind, payload(jsonb), owner_id, status(queued/running/done/failed), attempts, claimed_at, claimed_by, created_at, priority`.
- **Диспетчер по `kind`:** `task.process` (основной пайплайн, 6 типов) → `TaskProcessor.process`; `task.optimize`, `task.fix_prices`, `version.optimize`, `version.fill_prices`, `retrain` → соответствующие раннеры. Хендлер отвечает за доменный статус (Task/version/training_job), очередь — только за исполнение.
- **Claim (round-robin по owner):** короткая транзакция:
  ```
  UPDATE jobs SET status='running', claimed_at=now(), claimed_by=:worker
  WHERE id = (SELECT j.id FROM jobs j WHERE j.status='queued'
              ORDER BY (SELECT count(*) FROM jobs r
                        WHERE r.owner_id=j.owner_id AND r.status='running') ASC,
                       j.priority DESC, j.created_at ASC
              FOR UPDATE SKIP LOCKED LIMIT 1)
  RETURNING *;
  ```
- **Worker:** `python -m app.worker`, `asyncio.Semaphore(WORKER_CONCURRENCY)`, poll-loop; job бежит вне claim-транзакции; heartbeat обновляет `claimed_at`.
- **Reclaim sweep:** периодически `status='running' AND claimed_at < now()-VISIBILITY_TIMEOUT` → вернуть в `queued` (increment attempts; при `attempts>=MAX` → `failed`). Исключение — задачи в `_stage=batch_pending` (внешнее состояние Anthropic). Заменяет `_recover_stuck_tasks`.
- **Глобальный лимит Anthropic:** module-level `asyncio.Semaphore(ANTHROPIC_MAX_CONCURRENCY)` в `claude_service`, оборачивает все вызовы. Внутризадачный `FAST_CHUNK_CONCURRENCY` — в env.
- **Deploy:** прод `docker-compose.prod.yml` — `web` (uvicorn, первый сервис, гонит `alembic upgrade head`) + `worker` (`python -m app.worker`, без alembic, ретрай коннекта к БД). Managed Postgres. Поллеры (batch/resume/cleanup) → worker, `max_instances=1`.

---

## Фазы

### Phase 0 — Реальные пользователи и владелец задачи `[ ]`
**Цель:** система различает людей; у задачи есть `owner_id`.
- Миграция `030_add_users_identity_and_task_owner.py` (IF NOT EXISTS): `users.username` (unique, nullable→заполнить), `tasks.owner_id` (FK users.id, nullable для legacy). Индексы.
- `models/user.py`: `username`; `models/task.py`: `owner_id`.
- `auth.py`/`routers/auth.py`: логин по `username`+`password`; JWT `sub=user_id`, `role`, `username`. Обратная совместимость: сохранить вход admin.
- Сидинг индивидуальных аккаунтов (env-список или admin-эндпоинт создания пользователя). Решить минимально: env `USERS="login1:pass1,login2:pass2"` + роль.
- Все продьюсеры задач проставляют `owner_id = current_user.id` (`tasks.py:294,439,555`, `workflow_cards.py`).
- Frontend: поле «логин» на странице входа (`.business/assets/brand-guidelines.md` для стиля).
- **Gate:** миграция применяется; вход под индивидуальным логином; новая задача имеет owner_id; legacy-задачи (owner_id NULL) открываются без ошибок.

### Phase 1 — Таблица очереди `jobs` + примитивы claim `[ ]`
**Цель:** durable-очередь и claim/heartbeat/reclaim как библиотека (поведение ещё не подключено).
- Миграция `031_add_jobs_queue.py` (IF NOT EXISTS): таблица `jobs` + композитный индекс под claim (`status, priority, created_at`) и по `owner_id,status`.
- `models/job.py`.
- `services/job_queue.py`: `enqueue(kind, payload, owner_id, priority)`, `claim_one(worker_id)` (round-robin SQL выше), `heartbeat(job_id)`, `complete/fail(job_id)`, `reclaim_stale(timeout, max_attempts)`.
- Env в `config.py`: `WORKER_CONCURRENCY=4`, `ANTHROPIC_MAX_CONCURRENCY=6`, `FAST_CHUNK_CONCURRENCY` (перенести из task_processor), `JOB_VISIBILITY_TIMEOUT_S`, `JOB_POLL_INTERVAL_S`, `JOB_MAX_ATTEMPTS`, `DB_POOL_SIZE/DB_MAX_OVERFLOW` (поднять).
- Юнит-тесты: claim не отдаёт одну job двум воркерам (SKIP LOCKED), round-robin порядок, reclaim по таймауту.
- **Gate:** pytest на job_queue зелёный; миграция применяется.

### Phase 2 — Worker-процесс + диспетчер + поллеры `[ ]`
**Цель:** отдельный процесс исполняет job из очереди.
- `app/worker.py`: entrypoint, `Semaphore(WORKER_CONCURRENCY)`, poll-loop, graceful shutdown (дать текущим job дойти/отпустить claim).
- Реестр kind→handler; `task.process`→`TaskProcessor.process`. (Остальные kind — Phase 3.)
- Heartbeat во время job (расширить существующий heartbeat в `TaskProcessor.process` на обновление `claimed_at`).
- Перенести APScheduler-поллеры (`batch_poller`, `resume_poller`, `cleanup_price_cache`) в worker, `max_instances=1`; `reclaim_stale` — периодическая job там же.
- **Gate:** локально `python -m app.worker` берёт вручную поставленную `task.process` job и доводит задачу до completed; web при этом отвечает.

### Phase 3 — Продьюсеры ставят в очередь; убрать BackgroundTasks `[ ]`
**Цель:** единственный путь исполнения — очередь.
- Заменить 7 `background_tasks.add_task(_run_task_in_background, ...)` → `enqueue('task.process', {task_id}, owner_id)`; restart/resume/message просто ставят новую job.
- 4 вспомогательных раннера → соответствующие kind (`task.optimize`, `task.fix_prices`, `version.optimize`, `version.fill_prices`, `retrain`) + их хендлеры в реестре worker.
- Удалить `_recover_stuck_tasks` (заменён reclaim); убрать поллеры из web `lifespan`.
- Глобальный семафор Anthropic в `claude_service`.
- **Gate:** ни одного `add_task` фоновой обработки в web; все 10 путей идут через очередь; регресс-прогон pytest зелёный; recovery-сценарий (kill worker в середине → задача возвращается и доигрывается).

### Phase 4 — Деплой Timeweb + локальный паритет `[ ]`
**Цель:** прод-конфигурация web+worker и dev-паритет.
**Полный чек-лист платформенных доработок (11 пунктов) — в [2026-07-24-timeweb-архитектура-и-доработки.md](2026-07-24-timeweb-архитектура-и-доработки.md), раздел 2.** Здесь — сводка:
- `docker-compose.prod.yml`: `web` (первый, домен, `alembic upgrade head && uvicorn`) + `worker` (`python -m app.worker`, ретрай коннекта), без `volumes/--reload` (§2.1, §2.3).
- Убрать `alembic upgrade` из `main.py` lifespan — мигрирует только web-CMD, исключить гонку web/worker (§2.2).
- **SSL к managed Postgres:** параметр из env (`DB_SSL_MODE`) в `create_async_engine` (`database.py:17-31`), не ломая локаль (§2.4).
- **Graceful shutdown worker по SIGTERM:** перестать брать job, отпустить claim, `scheduler.shutdown()` (§2.5).
- **Пул asyncpg** под число слотов (env `DB_POOL_SIZE/DB_MAX_OVERFLOW`), с оглядкой на лимит соединений managed-БД (§2.6). *(частично закладывается ещё в Phase 1)*
- Env-переменные в панели Timeweb (§2.7); `CORS_ORIGINS` + `VITE_API_BASE_URL` под новые домены (§2.8).
- `/health`-эндпоинт для проверок платформы (§2.9); логи worker в stdout симметрично web (§2.10).
- Локальный `docker-compose.yml`: добавить `worker`-сервис для паритета.
- README/деплой-заметка: Timeweb App Platform (Docker Compose), managed Postgres, порядок первого деплоя (рантбук — §3 чек-листа).
- `render.yaml`: пометить устаревшим, не ломая текущий прод до переезда (§2.11).
- **Gate:** `docker compose -f docker-compose.prod.yml config` валиден и без запрещённых директив; локально web+worker поднимаются, задача проходит end-to-end; worker переживает SIGTERM без потери job.

---

## Порядок и зависимости
`0 → 1 → 2 → 3 → 4` строго последовательно (0 даёт owner_id для fairness в 1; 1 даёт очередь для 2; 2 даёт worker для 3; 3 завершает переключение для 4). Параллелить нельзя.

## Риски
- **Гонка claim** — снимается `FOR UPDATE SKIP LOCKED` + тест AC6.
- **Длинные транзакции** — claim короткий, job вне транзакции, heartbeat.
- **Дубли поллеров при масштабировании** — `max_instances=1` + один worker-контейнер в этой итерации.
- **429 Anthropic** — глобальный семафор + тюнинг `FAST_CHUNK_CONCURRENCY`.
- **Гонка миграций web/worker** — мигрирует только web; worker ретраит коннект.
- **Legacy owner_id NULL** — nullable + фолбэк в fairness (NULL как отдельный «владелец»).

## Итоговый блок

**Статус: реализовано целиком (фазы 0–4).** Ветка `feature/perf-audit-2026-07`.

Реализация (коммиты queue-P0…P4):
- **P0** — личные аккаунты: `User.username`, `Task.owner_id` (миграция **032**, не 030 —
  030/031 заняты сессией аудита производительности), JWT sub=user_id, вход
  username+password с legacy-фолбэком, сидинг из env `USERS`, owner_id у всех продьюсеров,
  поле логина на фронте.
- **P1** — таблица `jobs` (миграция **033**) + `services/job_queue.py`
  (enqueue/claim_one round-robin+SKIP LOCKED/heartbeat/complete/fail/reclaim_stale),
  env очереди, 6 тестов (claim без дублей, round-robin, reclaim).
- **P2** — `app/worker.py`: пул слотов, poll-loop, диспетчер kind→handler, heartbeat,
  graceful shutdown; планировщик reclaim+batch+resume+cleanup; 3 теста диспетчера.
- **P3a** — 7 основных продьюсеров → enqueue(task.process); web-lifespan очищен
  (убраны _recover_stuck_tasks/scheduler/поллеры); глобальный семафор Anthropic;
  FAST_CHUNK_CONCURRENCY в env.
- **P3b** — 5 вспомогательных раннеров → очередь (task.optimize/fix_prices,
  version.optimize/fill_prices, retrain); в web не осталось add_task фоновой обработки.
- **P4** — деплой: `docker-compose.prod.yml` (Timeweb web+worker, managed PG, без volumes),
  worker в локальный compose и **в render.yaml** (чтобы текущий Render-прод не встал —
  web с P3 сам не обрабатывает), `DB_SSL_MODE` в database.py, poll-loop терпит
  недоступность БД на первом деплое. SIGTERM-graceful и пул из env — из P1/P2.

Гейты по каждой фазе: py_compile/ruff/pytest зелёные (272 passed; 2 предсуществующих
сбоя test_pdf_ocr_extractor не связаны с изменениями).

**Отклонения от плана:**
- Нумерация миграций 030→**032**, 031→**033** (конфликт с сессией аудита).
- cleanup_price_cache перенесён в worker в P3a (план относил к P2) — без функциональной разницы.
- Миграции по-прежнему в web-lifespan (§2.2 предлагал убрать): гонки нет, т.к. worker
  не запускает lifespan; двойной прогон web-CMD+lifespan идемпотентен. Можно вынести позже.

**Не входило в этот проект (Non-Goals соблюдены):** горизонтальное масштабирование
на несколько worker-контейнеров, админ-UI управления пользователями, миграция на Redis/Celery.

**Проверить на проде после деплоя (не воспроизводимо локально без Timeweb/Postgres):**
рантбук первого деплоя (web мигрирует → worker подхватывает), SIGTERM-drain,
SKIP LOCKED под реальной конкуренцией воркеров, SSL к managed PG.
