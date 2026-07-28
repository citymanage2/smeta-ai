# План — уведомление о восстановлении баланса API

Дата: 2026-07-28
Spec: `specs/2026-07-28-balance-restored-notification.md`
Research: `thoughts/research/2026-07-28-balance-restored-notification.md`

## Challenge Log

**1. Решает ли проблему?**
Боль пользователя: «пополнила баланс — почему не возобновляется, и как понять, что
вообще происходит». Закрывается двумя сигналами: событие при успехе (AC5, AC10) и
видимая отметка проверки при неуспехе (AC3). Оба состояния теперь различимы без
похода в админку.

**2. Самое ли эффективное решение?**
Рассмотрены: WebSocket-push, событие в памяти воркера, вычисление на фронте,
e-mail/Telegram, учащение тика (детально — в research). Выбран half-open probe +
персистентное событие + курсорный поллинг: переиспользует готовый `api_ping()`,
не добавляет инфраструктуры, переживает рестарт воркера и закрытую вкладку.
Побочно убирает слепые перезапуски задач каждые 10 минут при пустом балансе.

**3. Нет ли кода ради кода?**
Каждый элемент привязан к AC. Отдельно проверено: рефакторинг `useGlobalTaskPoller`
не делаем (новый хук независим), «колокольчик» с историей уведомлений — не делаем
(нет в scope), формат текста паузы в `task_processor` не трогаем.

## Фаза 1 — Модель события + миграция `[x]`

- `backend/app/models/system_event.py`: `SystemEvent` (`system_events`):
  `id` BigInt PK autoincrement, `kind` String(40) not null, `payload` JSONB not null
  default dict, `created_at` timestamptz not null. Индекс `ix_system_events_id_kind`
  по (`kind`, `id`) — выборка «события вида X с id > N».
- Импорт модели в `app/models/__init__.py`.
- `backend/alembic/versions/040_add_system_events.py` — `CREATE TABLE IF NOT EXISTS`
  + `CREATE INDEX IF NOT EXISTS`, downgrade `DROP TABLE IF EXISTS`.

Гейт: `pytest backend/tests/test_migration_startup.py -q`.

## Фаза 2 — Гейт по api_ping + запись события `[x]`

`backend/app/services/resume_poller.py`:

- Сигнатура: `resume_paused_tasks(session_factory=..., runner=None, pinger=None)`;
  `pinger` по умолчанию → `claude_service.api_ping` (импорт внутри функции, чтобы
  не тянуть anthropic в тесты поллера).
- Порядок: найти кандидатов → если пусто, выйти БЕЗ ping (AC1) → ping →
  - не `ok`: `_mark_balance_check_failed(...)` для каждой paused-задачи, вернуть `[]`;
  - `ok`: существующая логика захвата, затем `_record_balance_restored(...)`.
- `_mark_balance_check_failed`: обновляет только `progress_message` (не
  `progress_log`, не `updated_at`), текст:
  `⏸ На паузе: баланс API исчерпан. Проверка в HH:MM (МСК): баланс всё ещё исчерпан
  (ответ API: <код> <текст>). Следующая проверка через 10 минут.`
  При не-балансовой ошибке — «API недоступен: <код> <текст>».
- `_record_balance_restored`: одна строка `SystemEvent(kind='balance_restored',
  payload={'resumed_task_ids': [...]})`; вызывается только если список непустой (AC6).

Гейт: `pytest backend/tests/test_resume_poller.py backend/tests/test_balance_pause*.py
backend/tests/test_paused_resume_dead_end.py -q`.

## Фаза 3 — Эндпоинт `GET /notifications/system` `[x]`

- `backend/app/routers/notifications.py`, префикс `/notifications`, зависимость
  `get_current_user`.
- Параметры: `since_id: int = 0`, `limit: int = 20` (макс. 50).
- Логика: выбрать события `id > since_id` по возрастанию → для каждого подтянуть
  задачи по `payload.resumed_task_ids` с `visibility_filter(Task, user)` → если
  пользователь не менеджер и видимых задач нет, событие пропускается (AC8).
- Ответ: `{cursor, events: [{id, kind, created_at, resumed_count, tasks: [{id, name}]}]}`,
  где `resumed_count` — число видимых пользователю задач (менеджеру — всех).
  Отклонение от плана: курсор вынесен в ответ отдельным полем — событие может
  быть скрыто по правам, и без явного курсора фронт запрашивал бы его вечно.
- Регистрация роутера в `backend/app/main.py`.

Гейт: `pytest backend/tests/test_system_notifications.py -q`.

## Фаза 4 — Фронт: хук + toast `[ ]`

- `frontend/src/api/notifications.ts`: тип `SystemNotification` + `getSystemNotifications(sinceId)`.
- `frontend/src/hooks/useSystemNotifications.ts`: self-scheduling поллинг раз в 30 с,
  пропуск при `document.hidden`, немедленный опрос по `visibilitychange`, курсор в
  `localStorage['systemEventCursor']`; при отсутствии курсора — молча выставить
  максимальный id (AC11).
- Toast: `toast.success('✓ Баланс API пополнен')` + description
  «Возобновлены задачи: N — <до 3 названий>», `playSuccess()`, браузерное
  уведомление при скрытой вкладке (переиспользовать подход `utils/notify.ts`).
- Подключить хук в `frontend/src/components/Layout.tsx` рядом с `useGlobalTaskPoller()`.

Гейт: `npx tsc --noEmit`, `npm run lint`, `npm test`.

## Фаза 5 — Тесты, гейты, ревью `[ ]`

- `backend/tests/test_resume_poller_balance_gate.py` — AC1-AC6.
- `backend/tests/test_system_notifications.py` — AC7-AC8.
- `frontend/src/__tests__/SystemNotifications.test.tsx` — AC10-AC14.
- Полный прогон: `pytest -q`, фронтовые гейты, ruff.

## Итог

В работе — статусы фаз обновляются по мере выполнения.
