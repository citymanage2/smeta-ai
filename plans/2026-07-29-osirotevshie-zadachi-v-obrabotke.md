# Осиротевшие задачи в статусе «Обработка»

**Дата:** 2026-07-29
**Исследование:** `thoughts/research/2026-07-29-orphaned-processing-tasks.md`
**Размер:** M (backend, 4 файла + тесты)

## Проблема

Задача остаётся в `processing` навсегда, если её job ушла в терминальный `failed`
или потерялась: транспортный слой (`jobs`) и доменный (`tasks.status`) не связаны
на терминальных переходах. Пользователь видит вечно растущий таймер в «Активной
очереди», не получает ни результата, ни ошибки. Попытки ретрая расходуются на
рестарты контейнера при деплое, а не на реальные сбои.

Живой пример: `8a329d5e-9c69-439d-8cfe-959003e56b5f`, 954 минуты в «Обработке».

## Критерии приёмки

1. Терминальный `failed` у job → связанный `Task` получает `status='failed'` и
   человекочитаемый `error_message`. Работает и для `fail()`, и для ветки
   «превышены попытки» в `reclaim_stale()`.
2. Задача в `pending`/`processing` без живой job (`queued`/`running`) дольше
   `TASK_ORPHAN_GRACE_S` → помечается `failed`. Лечит уже накопленных сирот.
3. Sweep НЕ трогает: batch-задачи (`progress_data._stage == 'batch_pending'`),
   `paused`, удалённые (`deleted_at`), завершённые.
4. SIGTERM (плановый рестарт) не расходует попытку: недренированные job
   возвращаются в очередь с `attempts - 1`.
5. Requeue при shutdown не допускает двойного прогона: обработчики отменяются
   до возврата job в очередь; чужие job (`claimed_by != WORKER_ID`) не трогаются.
6. Все гейты зелёные: `pytest`, `ruff`, `py_compile`.

## Non-goals

- Не трогаем UI: «Ошибка» уже рендерится и в «Активной очереди», и в карточке.
- Не добавляем экран `/admin/queue-health` в админку (отдельная задача).
- Не меняем `JOB_MAX_ATTEMPTS` и не вводим автоперезапуск упавших задач.
- Никакого попутного рефакторинга `job_queue`/`worker` вне перечисленных критериев.

## Challenge Log

**1. Решает ли это проблему?**
Критерий 1 закрывает точную причину и мгновенную реакцию. Критерий 2 закрывает
случаи, до которых hook не дотянется (job-запись потеряна, сироты, накопленные
до этого фикса — включая текущую задачу). Критерий 4 убирает корневую причину.
Каждый критерий приёмки покрыт фазой; ни один не остался без реализации.

**2. Эффективнее ли это альтернатив?**

| Альтернатива | Минус | Вердикт |
|---|---|---|
| Только terminal-hook | Не лечит текущую сироту и потерю job-записи | Недостаточно |
| Только sweep | Лаг 30 мин, теряется точная причина (`last_error`) | Недостаточно |
| FK `jobs.task_id` + каскад | Миграция + job'ы ссылаются на разные сущности (`retrain` → training_job) | Дороже, ломает дизайн `kind`+`payload` |
| Поднять `JOB_MAX_ATTEMPTS` до 10 | Симптоматика: сирота всё равно возникнет, просто позже | Отклонено |
| Heartbeat из `TaskProcessor` в `tasks.updated_at` + порог | Уже есть heartbeat job'ы; дублирование механизма | Отклонено |

Выбранная связка — стандарт индустрии (Celery `on_failure` + Airflow zombie
detector + Sidekiq graceful requeue), см. раздел 4 исследования.

**3. Нет ли «кода ради кода»?**
`JOB_DRAIN_TIMEOUT_S` 25 → 20 — не косметика: без запаса на отмену+запись
критерий 5 физически невыполним в 30-секундном грейсе Timeweb.
Новых абстракций, слоёв и хелперов «на будущее» не вводится.

## Фазы

### [x] Фаза 1 — Синхронизация терминального падения job → Task

`backend/app/services/job_queue.py`:
- `_fail_linked_tasks(db, task_ids, error)` — guarded UPDATE
  `WHERE id IN (...) AND status IN ('pending','processing')`.
- `fail()` — после пометки job читает `payload['task_id']` и вызывает хелпер.
- `reclaim_stale()` — до bulk-UPDATE выбирает id протухших job с
  `attempts >= max_attempts`, после UPDATE помечает их задачи.

Текст ошибки: понятный менеджеру, не стектрейс.

Тесты: `tests/test_job_queue.py` — задача помечается failed; задача в `completed`
не трогается; job без `task_id` (`retrain`) не ломает вызов.

### [x] Фаза 2 — Sweep осиротевших задач

`backend/app/services/job_queue.py::sweep_orphaned_tasks(db, grace_s)`:
кандидаты (`pending`/`processing`, `updated_at < cutoff`, `deleted_at IS NULL`)
минус `_stage == 'batch_pending'` минус те, у кого есть job в `queued`/`running`.
Фильтрация payload — на стороне Python (DB-agnostic, как `batch_poller`).

`backend/app/worker.py`: задание планировщика раз в 5 минут.
`backend/app/config.py`: `TASK_ORPHAN_GRACE_S = 1800`.

Тесты: `tests/test_orphaned_tasks.py` — сирота → failed; batch_pending не тронут;
задача с живой job не тронута; свежая (внутри grace) не тронута; `paused` не тронут.

### [x] Фаза 3 — SIGTERM не сжигает попытку

`backend/app/worker.py`:
- `_inflight_job_ids: set[int]` — наполняется при claim, чистится при завершении.
- `requeue_after_shutdown(db, job_ids, worker_id)` в `job_queue`: guarded UPDATE
  `WHERE id IN (...) AND status='running' AND claimed_by=:worker AND attempts > 0`
  → `queued`, `claimed_by=NULL`, `claimed_at=NULL`, `attempts = attempts - 1`.
- В `main()` finally: дренаж → при таймауте отменить оставшиеся таски → дождаться
  отмены → requeue.
- `JOB_DRAIN_TIMEOUT_S`: 25 → 20.
- `docker-compose.yml`: `stop_grace_period: 30s` у сервиса `worker`.
  Найдено при ревью: дефолт Docker — **10 с**, то есть SIGKILL прилетал посреди
  дренажа и вся ветка отмены+requeue была бы мёртвым кодом на проде.
  Бюджет: 20 с дренаж + 3 с отмена + запись < 30 с.

Тесты: `tests/test_orphaned_tasks.py` — attempts уменьшается, статус `queued`;
чужая job (другой `claimed_by`) не трогается; `done`-job не воскресает.

### [x] Фаза 4 — Гейты и импакт-анализ

`pytest`, `ruff check`, `py_compile`; проверка, что не сломаны
`test_job_queue`, `test_batch_poller`, `test_balance_pause`, `test_admin_queue_health`.

## Итог

Реализован целиком, все 6 критериев приёмки выполнены.

Гейты: `ruff` по изменённым файлам чистый, `py_compile` ок, полный прогон —
**411 passed / 18 failed**, где эти 18 — ровно тот же набор, что падает на
базовом коммите (391 passed / 18 failed): локальное окружение Python 3.9 и
патч ленивого синглтона `claude_service._client`. Регрессий ноль, +20 новых тестов.

Миграции не требуются — новых полей БД нет.

Что дало ревью сверх плана:
- отказ от `UPDATE..RETURNING` в `reclaim_stale` (состав RETURNING у ORM-enabled
  UPDATE зависит от диалекта и стратегии `synchronize_session` — на PostgreSQL
  могло вернуться не то, а тест на SQLite этого бы не поймал);
- `stop_grace_period: 30s` — без него Фаза 3 не работала бы на проде вовсе;
- autouse-фикстура уборки в тестах: они коммитят, а фикстура сессии делает только
  rollback — утёкшие строки роняли `test_admin_queue_health` при другом порядке.

Осталось за рамками (сознательно, см. Non-goals): экран `/admin/queue-health`
в админке — при следующем зависании диагностика по-прежнему требует доступа
к эндпоинту с Bearer-токеном.

Найдено попутно, НЕ чинилось (отдельная задача, вне scope):
`ruff` показывает `F821 Undefined name '_date'` в
`backend/app/services/task_processor.py:1186` — ветка досчёта batch-задачи
упадёт с `NameError`, если в `progress_data` нет `current_date`.
