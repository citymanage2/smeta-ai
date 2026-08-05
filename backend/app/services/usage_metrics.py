"""Затраты и тайминги задачи — единственная точка расчёта.

План: `plans/2026-08-06-metriki-zatrat-po-stadiyam.md`, Фаза 3.

Одна смета обходится примерно в $10, и до сих пор эта цифра нигде рядом со
сметой не показывалась. Здесь она собирается из журнала вызовов ИИ
(`api_call_log`) и таймингов задачи — отдельной таблицы метрик нет и не нужно:
второй источник правды о деньгах немедленно разошёлся бы с админским дашбордом.

Два правила, которые легко нарушить:

1. **Один запрос на список задач, а не по задаче.** Список карточек проекта
   поллится каждые 5 секунд; N+1 здесь превращается в сотни запросов в минуту.
2. **Токены суммируются за все прогоны задачи, время — за последний.**
   Перезапуск переставляет `started_at`/`finished_at`, но потраченные деньги
   никуда не деваются. Разное поведение намеренное, объясняется в подсказке UI.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_call_log import ApiCallLog
from app.models.task import Task

# Статусы, в которых задача ещё движется: у них счётчики времени растут.
ACTIVE_STATUSES = frozenset({"pending", "processing"})


def _coarse(seconds: float) -> float:
    """Растущий счётчик — с точностью до минуты.

    Список карточек отдаётся с ETag и поллится каждые 5 секунд. Счётчик,
    меняющийся посекундно, менял бы тело на каждом опросе, и 304 не случался
    бы никогда. Ровно поэтому прогноз ETA тоже округлён до минуты. На
    завершённые значения это не распространяется: они не меняются вовсе.
    """
    return float(int(seconds // 60) * 60)


@dataclass(frozen=True)
class TaskUsage:
    """Во что обошлась одна задача и сколько она шла."""

    tokens: int = 0
    cost_usd: float = 0.0
    extra_tokens: int = 0
    extra_cost_usd: float = 0.0
    queue_seconds: Optional[float] = None
    work_seconds: Optional[float] = None
    # Счётчик ещё растёт — фронт может подписать «идёт» вместо готового числа.
    queue_running: bool = False
    work_running: bool = False


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    """SQLite отдаёт наивные datetime, PostgreSQL — с зоной. Считаем в UTC."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def timings_for_task(
    task: Task, now: Optional[datetime] = None
) -> tuple[Optional[float], Optional[float], bool, bool]:
    """(время в очереди, время работы, очередь идёт, работа идёт) в секундах.

    Очередь — от постановки до старта обработки. Работа — от старта до финиша.
    Задача ещё ждёт → очередь считается до «сейчас». Задача идёт → работа
    считается до «сейчас». Не начатая и не активная (например, отменённая до
    старта) отдаёт None: показывать ноль было бы неправдой.
    """
    now = now or datetime.now(timezone.utc)
    created = _aware(task.created_at)
    started = _aware(task.started_at)
    finished = _aware(task.finished_at)
    is_active = task.status in ACTIVE_STATUSES

    if started is not None:
        queue_seconds = max((started - created).total_seconds(), 0.0) if created else None
        queue_running = False
    elif is_active and created is not None:
        queue_seconds = _coarse(max((now - created).total_seconds(), 0.0))
        queue_running = True
    else:
        queue_seconds = None
        queue_running = False

    if started is None:
        work_seconds, work_running = None, False
    elif finished is not None:
        work_seconds = max((finished - started).total_seconds(), 0.0)
        work_running = False
    elif is_active:
        work_seconds = _coarse(max((now - started).total_seconds(), 0.0))
        work_running = True
    else:
        # Стартовала, но финиша нет и задача не активна — оборвалась на рестарте.
        # Дорисовывать время «до сейчас» нельзя: она давно ничего не делает.
        work_seconds, work_running = None, False

    return queue_seconds, work_seconds, queue_running, work_running


async def usage_for_tasks(
    db: AsyncSession, tasks: Iterable[Task], now: Optional[datetime] = None
) -> dict[str, TaskUsage]:
    """Метрики по задачам: один SQL на весь список, ключ — id задачи.

    Задача без единого вызова ИИ (файл загружен вручную) в ответе есть, но с
    нулевыми деньгами — фронт отличает «не тратили» от «нет данных» по наличию
    ключа, а прочерк рисует по нулю.
    """
    tasks = [t for t in tasks if t is not None]
    if not tasks:
        return {}

    task_ids = [str(t.id) for t in tasks]

    tokens = (
        ApiCallLog.input_tokens
        + ApiCallLog.output_tokens
        + ApiCallLog.cache_read_tokens
        + ApiCallLog.cache_creation_tokens
    )
    # case вместо FILTER: на SQLite (тесты) FILTER не поддерживается, а
    # расхождение диалектов в формуле денег — ровно то, что нельзя допускать.
    main_only = case((ApiCallLog.is_extra.is_(True), 0), else_=1)
    extra_only = case((ApiCallLog.is_extra.is_(True), 1), else_=0)

    rows = await db.execute(
        select(
            ApiCallLog.task_id,
            func.coalesce(func.sum(tokens * main_only), 0),
            func.coalesce(func.sum(ApiCallLog.cost_usd * main_only), 0),
            func.coalesce(func.sum(tokens * extra_only), 0),
            func.coalesce(func.sum(ApiCallLog.cost_usd * extra_only), 0),
        )
        .where(ApiCallLog.task_id.in_(task_ids))
        .group_by(ApiCallLog.task_id)
    )
    by_task = {
        str(task_id): (int(main_tok), float(main_cost), int(extra_tok), float(extra_cost))
        for task_id, main_tok, main_cost, extra_tok, extra_cost in rows.all()
    }

    now = now or datetime.now(timezone.utc)
    result: dict[str, TaskUsage] = {}
    for task in tasks:
        key = str(task.id)
        main_tok, main_cost, extra_tok, extra_cost = by_task.get(key, (0, 0.0, 0, 0.0))
        queue_s, work_s, queue_running, work_running = timings_for_task(task, now)
        result[key] = TaskUsage(
            tokens=main_tok,
            cost_usd=round(main_cost, 6),
            extra_tokens=extra_tok,
            extra_cost_usd=round(extra_cost, 6),
            queue_seconds=queue_s,
            work_seconds=work_s,
            queue_running=queue_running,
            work_running=work_running,
        )
    return result
