# Админ-эндпоинт queue-health

**Дата:** 2026-07-28
**Размер:** S (1 эндпоинт, read-only)
**Проблема:** при «задача виснет в Ожидании» диагностика требует SQL по проду
(managed PG) — долго и неудобно. Нужен быстрый способ увидеть состояние durable-
очереди прямо по HTTP. См. `.business/история/2026-07-28-виснет-задача-в-ожидании-worker-ssl.md`.

## Цель / acceptance criteria

`GET /admin/queue-health` (только админ, `get_admin_user`) возвращает:
- [x] `counts` — число job по статусам (queued/running/done/failed) из таблицы `jobs`.
- [x] `queued.oldest_age_s` — возраст самой старой queued-job (сек), null если нет.
- [x] `running.oldest_claimed_age_s` — возраст самого старого claimed_at среди running.
- [x] `running.stale_count` — running-job с claimed_at старше `JOB_VISIBILITY_TIMEOUT_S`
      (кандидаты на reclaim — признак зависшего/мёртвого worker).
- [x] `verdict` — `ok` / `busy` / `stalled` / `idle` + человекочитаемый `hint`.
      `stalled` = есть queued, самая старая старше порога, и НЕТ живых running
      (0 running или все stale) → worker не разбирает очередь (главный алярм).
- [x] Гард: не-админ → 403, без токена → 401/403.

## Не-цели

- Фронтенд-страница (отдельный follow-up). Сейчас только HTTP (админ дергает URL/curl).
- Изменения схемы БД (только чтение существующей таблицы `jobs`).
- Liveness worker'а «наверняка» — из таблицы jobs это эвристика; отдаём сырые
  сигналы + verdict, честно документируем.

## Подход

Добавить в существующий `app/routers/admin.py` (роутер уже с prefix `/admin` и
`get_admin_user`). 2 aggregate-запроса по `jobs` (индекс `ix_jobs_claim` покрывает
`status`). Возраст считаем в Python от `datetime.now(timezone.utc)`; naive-даты из
SQLite нормализуем как UTC (tz-safe хелпер).

Порог `stalled`: `QUEUE_STALL_THRESHOLD_S = 120` (2 мин) — queued-job не должна
столько ждать при живом свободном worker'е; при этом `stale running` считаем по
принципиальному `JOB_VISIBILITY_TIMEOUT_S`.

## Фазы

- [x] **Фаза 1 — эндпоинт + pydantic-модели в admin.py, тесты, гейты.**

## Гейты

- [x] py_compile admin.py
- [x] ruff check (изменённые файлы)
- [x] pytest: новый `tests/test_admin_queue_health.py` + без регрессий в test_admin/test_job_queue

## Итог

Реализовано целиком (Фаза 1). Эндпоинт `GET /admin/queue-health` отдаёт счётчики,
возрасты и verdict со `stalled`-детекцией. Follow-up (опц.): кнопка/виджет во
фронт-админке, дергающая этот эндпоинт.
