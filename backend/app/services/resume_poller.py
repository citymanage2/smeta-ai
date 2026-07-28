"""
Периодический поллер авто-возобновления задач на паузе (paused).

При исчерпании баланса Anthropic задача уходит в статус `paused` с сохранённым
чекпоинтом (см. Фаза 3). У Anthropic НЕТ API проверки баланса — узнать про
пополнение можно только пробным вызовом. Поэтому раз в N минут поллер берёт
paused-задачи, атомарно помечает их `pending` и запускает обработку заново с
точки прерывания.

Пробный вызов — ОДИН на тик (`api_ping`, max_tokens=1, доли цента), а не «пусть
каждая задача сама узнает». Раньше поллер перезапускал задачи вслепую: при пустом
балансе каждая заново стартовала, доходила до первого вызова Claude, падала и
возвращалась в `paused` — молча. Это стоило холостых запусков воркера каждые 10
минут и, главное, не оставляло в UI никакого следа: пользователь, пополнивший
счёт, видел тот же застывший текст паузы и не мог понять, дошли деньги или нет.
Теперь: ping не ok → задачи не трогаем, но у каждой обновляем `progress_message`
временем и причиной проверки; ping ok → возобновляем и пишем `SystemEvent`
(`balance_restored`), по которому фронт показывает уведомление.

Гард от двойного запуска: захват делается атомарным UPDATE со `WHERE status =
'paused'` — уже захваченная (переведённая в pending) задача повторно не берётся.
Плюс scheduler регистрирует job с max_instances=1.

Логика вынесена из main.py, чтобы не тянуть apscheduler в тесты (как batch_poller).
План: plans/2026-07-21-resume-and-balance-pause.md, Фаза 4;
      plans/2026-07-28-balance-restored-notification.md, Фаза 2.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, update

from app.database import AsyncSessionLocal
from app.models.system_event import KIND_BALANCE_RESTORED, SystemEvent
from app.models.task import Task
from app.services.checkpoint import has_resumable_checkpoint, is_batch_pending

logger = structlog.get_logger()

# Периодичность тика (worker.py: scheduler.add_job(..., minutes=10)) — только для
# текста «следующая проверка через N минут».
POLL_INTERVAL_MINUTES = 10

# Прод-сервер живёт в UTC, а пользователи — в Москве. Время в тексте показываем
# московское, иначе «проверка в 07:12» читается как трёхчасовое опоздание.
_MSK = timezone(timedelta(hours=3))

# Ссылки на fire-and-forget задачи, чтобы их не собрал GC до завершения.
_background_runs: set = set()

# Единый предикат возобновляемости — тот же, что в ручном resume-эндпоинте
# (app/routers/tasks.py: resume_task). Алиас сохранён для обратной совместимости.
_has_checkpoint = has_resumable_checkpoint


async def _find_resumable_paused_ids(db) -> list[str]:
    """ID ВСЕХ задач в статусе paused.

    Фаза 8: раньше здесь стоял фильтр «только с чекпоинтом», и задача, у которой
    баланс кончился до первого чекпоинта (первая группа чанков fast-режима или
    submit пачки в batch-режиме), не возобновлялась ни поллером, ни кнопкой —
    оставалась paused навсегда. Пауза ставится только по балансу, поэтому paused
    без чекпоинта безопасно перезапустить с нуля: терять нечего.
    """
    result = await db.execute(select(Task).where(Task.status == "paused"))
    return [t.id for t in result.scalars().all()]


async def _claim(db, task_id: str) -> bool:
    """Атомарно перевести задачу paused→pending. Возвращает True, если захвачена
    именно этим вызовом (не была уже перехвачена/изменена)."""
    res = await db.execute(
        update(Task)
        .where(Task.id == task_id, Task.status == "paused")
        .values(
            status="pending",
            error_message=None,
            updated_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()
    return res.rowcount == 1


async def _claim_batch_to_processing(db, task_id: str) -> bool:
    """Атомарно paused→processing для задачи с уже отправленной пачкой Batch API.

    Пачка оплачена и считается на серверах Anthropic — перезапускать обработку
    нельзя (заплатим второй раз). Достаточно вернуть задачу в `processing`:
    результаты доберёт batch_poller.
    """
    res = await db.execute(
        update(Task)
        .where(Task.id == task_id, Task.status == "paused")
        .values(
            status="processing",
            error_message=None,
            updated_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()
    return res.rowcount == 1


async def _claim_and_enqueue(db, task_id: str) -> bool:
    """Прод-путь авто-резюме: АТОМАРНО (одна транзакция) paused→pending + постановка
    durable-job `task.process`. Так задача не осиротеет в `pending` без Job, если
    воркер рестартует сразу после захвата (P1: раньше запускался прямой
    _run_task_in_background мимо очереди — reclaim его не подхватывал)."""
    from app.models.job import Job

    res = await db.execute(
        update(Task)
        .where(Task.id == task_id, Task.status == "paused")
        .values(status="pending", error_message=None, updated_at=datetime.now(timezone.utc))
    )
    if res.rowcount != 1:
        await db.rollback()
        return False
    task = await db.get(Task, task_id)
    db.add(
        Job(
            kind="task.process",
            payload={"task_id": task_id},
            owner_id=(task.owner_id if task else None),
            status="queued",
        )
    )
    await db.commit()
    return True


def _balance_check_message(ping: dict) -> str:
    """Текст для карточки задачи: когда проверяли баланс и что ответил API.

    Без этой строки «пауза» и «поллер мёртв» в UI неотличимы — оба выглядят как
    застывший текст. Ограничение 500 символов — размер Task.progress_message.
    """
    now = datetime.now(_MSK).strftime("%H:%M")
    if ping.get("is_balance_error"):
        reason = "баланс всё ещё исчерпан"
    else:
        code = ping.get("status_code") or "нет ответа"
        reason = f"API недоступен ({code})"
    detail = (ping.get("error") or "").strip()
    tail = f" Ответ API: {detail}" if detail else ""
    msg = (
        f"⏸ На паузе: баланс API исчерпан. Проверка в {now} (МСК): {reason}."
        f"{tail} Следующая проверка через {POLL_INTERVAL_MINUTES} мин."
    )
    return msg[:500]


async def _mark_balance_check_failed(session_factory, task_ids: list[str], ping: dict) -> None:
    """Отметить на карточках, что проверка была и деньги не пришли.

    Пишем ТОЛЬКО progress_message: `progress_log` — история шагов задачи, и
    строка «проверка баланса» каждые 10 минут превратила бы её в мусор. Поле
    `updated_at` тоже не трогаем — задача не менялась, менялась внешняя среда.
    """
    message = _balance_check_message(ping)
    async with session_factory() as db:
        await db.execute(
            update(Task)
            .where(Task.id.in_(task_ids), Task.status == "paused")
            .values(progress_message=message)
        )
        await db.commit()


async def _record_balance_restored(session_factory, task_ids: list[str]) -> None:
    """Зафиксировать переход «денег нет → деньги есть» как событие для фронта.

    Пишется только когда реально что-то возобновлено: событие без задач — шум.
    """
    async with session_factory() as db:
        db.add(
            SystemEvent(
                kind=KIND_BALANCE_RESTORED,
                payload={"resumed_task_ids": task_ids},
            )
        )
        await db.commit()
    logger.info("Balance restored event recorded", count=len(task_ids), task_ids=task_ids)


async def resume_paused_tasks(
    session_factory=AsyncSessionLocal, runner=None, pinger=None
) -> list[str]:
    """Один проход: захватить paused-задачи и переочередить их.

    Возвращает список ID реально захваченных (paused→pending) задач. Задачи с
    отправленной пачкой Batch API возвращаются в `processing` (их досчитает
    batch_poller) и в этот список не попадают — их не нужно обрабатывать заново.

    Прод (`runner is None`): захват и постановка durable-job атомарны
    (`_claim_and_enqueue`) — обработку доведёт worker из очереди, в рамках лимита
    WORKER_CONCURRENCY и с reclaim-подстраховкой.
    Тесты могут инъектировать `runner` — тогда используется старый путь
    (`_claim` + прямой вызов runner) для проверки оркестрации. Аналогично
    `pinger` подменяет пробный вызов API, чтобы тесты не ходили в сеть.
    """
    async with session_factory() as db:
        candidates = await _find_resumable_paused_ids(db)

    # Нет пауз — нечего проверять: ping не делаем вообще (нулевая стоимость тика).
    if not candidates:
        return []

    if pinger is None:
        from app.services.claude_service import api_ping

        pinger = api_ping
    ping = await pinger()
    if not ping.get("ok"):
        # Денег по-прежнему нет (или API недоступен). Перезапускать задачи
        # бессмысленно — они упадут на первом же вызове. Оставляем как есть и
        # только отмечаем факт проверки на карточках.
        logger.info(
            "Balance still exhausted — paused tasks left untouched",
            paused=len(candidates),
            status_code=ping.get("status_code"),
            is_balance_error=ping.get("is_balance_error"),
        )
        await _mark_balance_check_failed(session_factory, candidates, ping)
        return []

    claimed: list[str] = []
    batch_claimed: list[str] = []
    for task_id in candidates:
        async with session_factory() as db:
            task = await db.get(Task, task_id)
            # Пачка Batch API уже отправлена → возвращаем в processing (без job и
            # без runner): смету достроит batch_poller из готовых результатов.
            if task is not None and is_batch_pending(task.progress_data):
                if await _claim_batch_to_processing(db, task_id):
                    batch_claimed.append(task_id)
                continue
            ok = await (_claim(db, task_id) if runner is not None else _claim_and_enqueue(db, task_id))
            if ok:
                claimed.append(task_id)

    if batch_claimed:
        logger.info(
            "Paused batch tasks returned to polling",
            count=len(batch_claimed),
            task_ids=batch_claimed,
        )

    # Событие — про всё, что реально сдвинулось с паузы, включая batch-задачи:
    # для пользователя «возобновлено» одинаково и там, и там. Если захватить
    # ничего не удалось (параллельный тик перехватил) — события нет.
    resumed = claimed + batch_claimed
    if resumed:
        await _record_balance_restored(session_factory, resumed)

    if not claimed:
        return []

    logger.info("Auto-resuming paused tasks", count=len(claimed))
    # Прод-путь уже поставил job в очередь внутри _claim_and_enqueue. Прямой запуск —
    # только для инъектированного тестового runner.
    if runner is not None:
        for task_id in claimed:
            run = asyncio.create_task(runner(task_id))
            _background_runs.add(run)
            run.add_done_callback(_background_runs.discard)

    return claimed
