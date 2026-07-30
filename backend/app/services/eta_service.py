"""Прогноз: когда задача стартует и когда будет результат.

Модель простая и намеренно объяснимая:

    длительность = база(тип) + ставка(тип, единица) × объём
    ожидание     = симуляция очереди по WORKER_CONCURRENCY слотам

Ставка калибруется по фактическим длительностям завершённых задач (медиана —
одна шестичасовая аномалия не должна ломать прогноз всем остальным). Пока
наблюдений мало, берётся значение по умолчанию, а прогноз помечается как грубый:
показать грубую оценку с оговоркой полезнее, чем прочерк.

Чего модель НЕ знает и знать не пытается: точного порядка round-robin по
владельцам, пауз по балансу API, ретраев и рестартов воркера. Поэтому наружу
число уходит только как «≈».
"""
import heapq
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Iterable, Optional, Sequence, Union

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.task import Task
from app.schemas.eta import TaskEta
from app.services.checkpoint import is_batch_pending
from app.utils.volume_probe import (
    UNIT_ITEMS,
    UNIT_PAGES,
    UNIT_ROWS,
    probe_files_units,
    probe_items_units,
)

logger = structlog.get_logger()

ACTIVE_STATUSES = ("pending", "processing")

# --- Значения по умолчанию, пока нет истории -------------------------------
# Постоянные накладные расходы типа: чтение файла, OCR-пролог, сборка Excel.
_DEFAULT_BASE_S: dict[str, float] = {
    "LIST_FROM_GRAND": 120,
    "LIST_FROM_PROJECT": 180,
    "CHECK_LIST_COMPLETENESS": 120,
    "CHECK_PROJECT_COMPLETENESS": 120,
    "ESTIMATE_FROM_LIST": 240,
    "ESTIMATE_OPTIMIZATION": 180,
}
_FALLBACK_BASE_S = 120.0

# Секунд на единицу объёма. Стартовые значения — из наблюдений на проде:
# смета из перечня на ~1200 позиций считалась около шести часов ⇒ ~18 с/позиция.
_DEFAULT_RATE_S: dict[tuple[str, str], float] = {
    ("LIST_FROM_GRAND", UNIT_ROWS): 2.5,
    ("LIST_FROM_GRAND", UNIT_PAGES): 30.0,
    ("LIST_FROM_PROJECT", UNIT_PAGES): 40.0,
    ("CHECK_LIST_COMPLETENESS", UNIT_ITEMS): 2.5,
    ("CHECK_PROJECT_COMPLETENESS", UNIT_ITEMS): 2.5,
    ("ESTIMATE_FROM_LIST", UNIT_ITEMS): 18.0,
    ("ESTIMATE_FROM_LIST", UNIT_ROWS): 18.0,
    ("ESTIMATE_OPTIMIZATION", UNIT_ITEMS): 6.0,
    ("ESTIMATE_OPTIMIZATION", UNIT_ROWS): 6.0,
}
_FALLBACK_RATE_BY_UNIT: dict[str, float] = {
    UNIT_PAGES: 35.0,
    UNIT_ROWS: 3.0,
    UNIT_ITEMS: 10.0,
}

# Длительность, когда объём померить не удалось: прогноз идёт «по типу целиком».
_DEFAULT_FLAT_S: dict[str, float] = {
    "LIST_FROM_GRAND": 900,
    "LIST_FROM_PROJECT": 2400,
    "CHECK_LIST_COMPLETENESS": 900,
    "CHECK_PROJECT_COMPLETENESS": 900,
    "ESTIMATE_FROM_LIST": 7200,
    "ESTIMATE_OPTIMIZATION": 1800,
}
_FALLBACK_FLAT_S = 1800.0

# --- Параметры калибровки ---------------------------------------------------
MIN_SAMPLES = 3               # меньше — статистики нет, живём на дефолтах
CALIBRATION_WINDOW_DAYS = 30  # старше — другие промпты, другая модель, другая цена
CALIBRATION_LIMIT = 300       # потолок строк на один запрос
_MAX_PLAUSIBLE_S = 24 * 3600  # длительность больше суток — след сбоя, не работы
_RATE_CLAMP = (0.2, 5.0)      # калиброванная ставка не улетает от дефолта дальше
_MIN_REMAINING_S = 60.0       # «вот-вот закончит» — не ноль и не отрицательное
# Доля выполненного, начиная с которой экстраполяция по факту честнее модели.
_PROGRESS_TRUST_FRACTION = 0.15
_PROGRESS_MIN_ELAPSED_S = 60.0


@dataclass(frozen=True)
class TaskSnapshot:
    """То немногое из задачи, что нужно прогнозу.

    Прогноз считается по ВСЕЙ активной очереди на каждый опрос статуса (раз в
    3 с на открытую карточку). Тянуть ради этого полные строки задач нельзя:
    в `progress_data` лежат позиции сметы и OCR-текст страниц — мегабайты на
    задачу. Поэтому из JSON достаём только четыре скаляра.
    """

    id: str
    task_type: str
    status: str
    processing_mode: str
    volume_units: Optional[int]
    volume_kind: Optional[str]
    created_at: Optional[datetime]
    started_at: Optional[datetime]
    batch_pending: bool
    chunks_done: Optional[int]
    chunks_total: Optional[int]

    @classmethod
    def from_task(cls, task: Task) -> "TaskSnapshot":
        pd = task.progress_data or {}
        total = pd.get("total_chunks")
        if not isinstance(total, int) or isinstance(total, bool):
            total = pd.get("chunks_total")
        done = pd.get("chunks_done")
        return cls(
            id=str(task.id),
            task_type=task.task_type,
            status=task.status,
            processing_mode=_mode(task),
            volume_units=task.volume_units,
            volume_kind=task.volume_kind,
            created_at=task.created_at,
            started_at=task.started_at,
            batch_pending=is_batch_pending(task.progress_data),
            chunks_done=done if isinstance(done, int) and not isinstance(done, bool) else None,
            chunks_total=total if isinstance(total, int) and not isinstance(total, bool) else None,
        )


@dataclass(frozen=True)
class Rates:
    """Калиброванные ставки. Пустой объект = «истории нет, всё по умолчанию»."""

    per_unit: dict[tuple[str, str, str], float] = field(default_factory=dict)
    flat: dict[tuple[str, str], float] = field(default_factory=dict)

    def rate_for(self, task_type: str, mode: str, unit_kind: str) -> tuple[float, bool]:
        """(секунд на единицу, откалибровано ли)."""
        calibrated = self.per_unit.get((task_type, mode, unit_kind))
        if calibrated is not None:
            return calibrated, True
        return _default_rate(task_type, unit_kind), False

    def flat_for(self, task_type: str, mode: str) -> tuple[float, bool]:
        calibrated = self.flat.get((task_type, mode))
        if calibrated is not None:
            return calibrated, True
        return _DEFAULT_FLAT_S.get(task_type, _FALLBACK_FLAT_S), False


def _default_rate(task_type: str, unit_kind: str) -> float:
    explicit = _DEFAULT_RATE_S.get((task_type, unit_kind))
    if explicit is not None:
        return explicit
    return _FALLBACK_RATE_BY_UNIT.get(unit_kind, 10.0)


def _base_s(task_type: str) -> float:
    return _DEFAULT_BASE_S.get(task_type, _FALLBACK_BASE_S)


def _mode(task: Task) -> str:
    """Batch-режим считается на серверах Anthropic и живёт по своим таймингам —
    смешивать его тайминги с обычными в одной ставке нельзя."""
    return (getattr(task, "processing_mode", None) or "fast").lower()


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """SQLite отдаёт naive-даты; трактуем их как UTC (так их и писали)."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Замер объёма при создании задачи
# ---------------------------------------------------------------------------

async def measure_task_volume(
    db: AsyncSession,
    *,
    files: Sequence[tuple[str, str, bytes]] = (),
    source_task_id: Optional[str] = None,
) -> tuple[Optional[int], Optional[str]]:
    """Сколько работы в задаче: (объём, единица). Никогда не бросает.

    Приоритет у исходной задачи: если смета строится по готовому перечню, число
    позиций точнее, чем строки в исходном файле.
    """
    import asyncio

    try:
        if source_task_id:
            progress_data = (
                await db.execute(
                    select(Task.progress_data).where(Task.id == source_task_id)
                )
            ).scalar_one_or_none()
            units, kind = probe_items_units(progress_data)
            if units:
                return units, kind
        if files:
            # openpyxl/fitz — синхронные и на больших файлах заметные: уводим в
            # поток, чтобы создание задачи не подвешивало событийный цикл.
            return await asyncio.to_thread(probe_files_units, list(files))
    except Exception as e:  # noqa: BLE001 — замер не вправе ломать создание задачи
        logger.info("Volume measurement failed", error=str(e))
    return None, None


# ---------------------------------------------------------------------------
# Калибровка по истории
# ---------------------------------------------------------------------------

async def load_rates(db: AsyncSession, now: Optional[datetime] = None) -> Rates:
    """Ставки по фактам последних завершённых задач. Один запрос."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=CALIBRATION_WINDOW_DAYS)

    rows = (
        await db.execute(
            select(
                Task.task_type,
                Task.processing_mode,
                Task.volume_units,
                Task.volume_kind,
                Task.started_at,
                Task.finished_at,
            )
            .where(
                Task.status == "completed",
                Task.started_at.isnot(None),
                Task.finished_at.isnot(None),
                Task.finished_at >= cutoff,
            )
            .order_by(Task.finished_at.desc())
            .limit(CALIBRATION_LIMIT)
        )
    ).all()

    rate_samples: dict[tuple[str, str, str], list[float]] = {}
    flat_samples: dict[tuple[str, str], list[float]] = {}

    for task_type, mode, units, unit_kind, started_at, finished_at in rows:
        started, finished = _as_utc(started_at), _as_utc(finished_at)
        duration = (finished - started).total_seconds()
        if duration <= 0 or duration > _MAX_PLAUSIBLE_S:
            continue  # след сбоя или кривых часов, а не работы
        mode = (mode or "fast").lower()
        flat_samples.setdefault((task_type, mode), []).append(duration)
        if units and units > 0 and unit_kind:
            # База вычитается: она не масштабируется объёмом.
            per_unit = max(duration - _base_s(task_type), 0.0) / units
            if per_unit > 0:
                rate_samples.setdefault((task_type, mode, unit_kind), []).append(per_unit)

    per_unit_rates: dict[tuple[str, str, str], float] = {}
    for key, samples in rate_samples.items():
        if len(samples) < MIN_SAMPLES:
            continue
        task_type, _mode_key, unit_kind = key
        default = _default_rate(task_type, unit_kind)
        lo, hi = default * _RATE_CLAMP[0], default * _RATE_CLAMP[1]
        # Клампим относительно дефолта: пара мусорных наблюдений (объём померен
        # неверно, задача возобновлялась) не должна утроить прогноз всем.
        per_unit_rates[key] = min(max(median(samples), lo), hi)

    flat_rates: dict[tuple[str, str], float] = {
        key: min(max(median(samples), 60.0), _MAX_PLAUSIBLE_S)
        for key, samples in flat_samples.items()
        if len(samples) >= MIN_SAMPLES
    }

    return Rates(per_unit=per_unit_rates, flat=flat_rates)


# ---------------------------------------------------------------------------
# Длительность одной задачи
# ---------------------------------------------------------------------------

def estimate_duration_s(task: Union[Task, TaskSnapshot], rates: Rates) -> tuple[float, bool]:
    """(сколько секунд считать задачу, грубая ли оценка)."""
    task_type = (task.task_type or "").upper()
    mode = _mode(task)
    units = task.volume_units
    unit_kind = task.volume_kind

    if units and units > 0 and unit_kind:
        rate, calibrated = rates.rate_for(task_type, mode, unit_kind)
        return _base_s(task_type) + rate * units, not calibrated

    flat, _calibrated = rates.flat_for(task_type, mode)
    # Объёма нет — масштабировать нечем, честно помечаем оценку грубой.
    return flat, True


def _progress_fraction(done: Optional[int], total: Optional[int]) -> Optional[float]:
    """Доля сделанного по счётчику чанков, если он есть и осмыслен."""
    if not done or not total or total <= 0 or done <= 0:
        return None
    return min(done / total, 1.0)


def remaining_s(task: TaskSnapshot, total_s: float, now: datetime) -> tuple[float, bool]:
    """Сколько осталось считающейся задаче: (секунды, «оценка исчерпана»).

    Если задача успела отчитаться о заметной доле чанков, экстраполируем по
    ФАКТУ её собственного темпа — это измерение, а не модель, и оно точнее.
    """
    started = _as_utc(task.started_at)
    elapsed = max((now - started).total_seconds(), 0.0) if started else 0.0

    fraction = _progress_fraction(task.chunks_done, task.chunks_total)
    if (
        fraction is not None
        and fraction >= _PROGRESS_TRUST_FRACTION
        and elapsed >= _PROGRESS_MIN_ELAPSED_S
    ):
        remaining = elapsed * (1.0 - fraction) / fraction
    else:
        remaining = total_s - elapsed

    if remaining < _MIN_REMAINING_S:
        return _MIN_REMAINING_S, True
    return remaining, False


# ---------------------------------------------------------------------------
# Симуляция очереди
# ---------------------------------------------------------------------------

def simulate_queue(
    tasks: Iterable[Union[Task, TaskSnapshot]],
    rates: Rates,
    now: datetime,
    slots: Optional[int] = None,
) -> dict[str, TaskEta]:
    """Прогноз для всех активных задач разом.

    Раскладываем очередь по слотам воркера (list-scheduling): бегущие задачи
    держат слоты своим остатком, ожидающие занимают ближайший освободившийся.
    Порядок ожидающих — по created_at; настоящий round-robin по владельцам
    воспроизвести нельзя, отсюда «≈» в интерфейсе.

    Принимает и ORM-задачи (у вызывающего они уже загружены), и лёгкие снимки.
    """
    slots = max(1, slots if slots is not None else settings.WORKER_CONCURRENCY)
    tasks = [t if isinstance(t, TaskSnapshot) else TaskSnapshot.from_task(t) for t in tasks]

    running = [t for t in tasks if t.status == "processing"]
    pending = sorted(
        (t for t in tasks if t.status == "pending"),
        key=lambda t: (_as_utc(t.created_at) or now),
    )

    result: dict[str, TaskEta] = {}
    busy_until: list[float] = []

    for task in running:
        total_s, rough = estimate_duration_s(task, rates)
        remaining, finishing = remaining_s(task, total_s, now)
        result[task.id] = _build_eta(
            task, now, starts_in=0.0, ready_in=remaining, rough=rough, finishing=finishing
        )
        # Batch-задача ждёт ответа Anthropic и слот воркера НЕ занимает —
        # иначе очередь выглядела бы забитой, когда воркер на самом деле свободен.
        if not task.batch_pending:
            busy_until.append(remaining)

    # Занятых больше, чем слотов (перезапуск, чужие job, batch-хвосты) — держим
    # самые поздние: пусть прогноз будет осторожным, а не оптимистичным.
    busy_until.sort()
    if len(busy_until) > slots:
        busy_until = busy_until[len(busy_until) - slots:]
    while len(busy_until) < slots:
        busy_until.append(0.0)
    heapq.heapify(busy_until)

    for task in pending:
        total_s, rough = estimate_duration_s(task, rates)
        starts_in = heapq.heappop(busy_until)
        ready_in = starts_in + total_s
        heapq.heappush(busy_until, ready_in)
        result[task.id] = _build_eta(
            task, now, starts_in=starts_in, ready_in=ready_in, rough=rough, finishing=False
        )

    return result


def _to_minutes(seconds: float) -> int:
    """Округление до минуты — и честность, и практика.

    Честность: секундная точность у оценки, которая может ошибиться на часы, —
    ложная. Практика: канбан-доска поллится раз в 5 с с ETag, и посекундный
    прогноз ломал бы 304-ответы на каждом опросе.
    """
    return int(round(seconds / 60.0)) * 60


def _build_eta(
    task: TaskSnapshot,
    now: datetime,
    *,
    starts_in: float,
    ready_in: float,
    rough: bool,
    finishing: bool,
) -> TaskEta:
    ready_in_rounded = _to_minutes(ready_in)
    # Абсолютное время тоже кладём на минутную сетку: иначе оно ползло бы каждую
    # секунду вместе с `now` и ломало ETag поллящихся списков.
    raw_ready = now + timedelta(seconds=ready_in_rounded)
    bump = 1 if raw_ready.second >= 30 else 0
    ready_at = raw_ready.replace(second=0, microsecond=0) + timedelta(minutes=bump)
    return TaskEta(
        starts_in_s=_to_minutes(starts_in),
        ready_in_s=ready_in_rounded,
        ready_at=ready_at.isoformat(),
        rough=rough,
        finishing=finishing,
        units=task.volume_units,
        unit_kind=task.volume_kind,
    )


async def _load_active_snapshots(db: AsyncSession) -> list[TaskSnapshot]:
    """Активная очередь в виде лёгких снимков.

    Из `progress_data` берём четыре скаляра через JSON-доступ (SQLAlchemy сама
    разложит его в `->>` на PostgreSQL и `json_extract` на SQLite), а не тянем
    весь документ: там лежат позиции сметы и OCR-текст страниц.
    """
    rows = (
        await db.execute(
            select(
                Task.id,
                Task.task_type,
                Task.status,
                Task.processing_mode,
                Task.volume_units,
                Task.volume_kind,
                Task.created_at,
                Task.started_at,
                Task.progress_data["_stage"].as_string().label("stage"),
                Task.progress_data["batch_id"].as_string().label("batch_id"),
                Task.progress_data["chunks_done"].as_integer().label("chunks_done"),
                Task.progress_data["total_chunks"].as_integer().label("total_chunks"),
                Task.progress_data["chunks_total"].as_integer().label("chunks_total"),
            ).where(
                Task.deleted_at.is_(None),
                Task.status.in_(ACTIVE_STATUSES),
            )
        )
    ).all()

    return [
        TaskSnapshot(
            id=str(r.id),
            task_type=r.task_type,
            status=r.status,
            processing_mode=(r.processing_mode or "fast").lower(),
            volume_units=r.volume_units,
            volume_kind=r.volume_kind,
            created_at=r.created_at,
            started_at=r.started_at,
            batch_pending=r.stage == "batch_pending" and bool(r.batch_id),
            chunks_done=r.chunks_done,
            chunks_total=r.total_chunks if r.total_chunks else r.chunks_total,
        )
        for r in rows
    ]


async def queue_forecast(
    db: AsyncSession,
    active_tasks: Optional[Sequence[Union[Task, TaskSnapshot]]] = None,
    now: Optional[datetime] = None,
) -> dict[str, TaskEta]:
    """Прогноз по всей активной очереди: task_id → TaskEta.

    Считать по одной задаче нельзя: её старт зависит от всех, кто впереди.
    `active_tasks` передаётся вызывающим, если он их уже загрузил (дашборд).
    """
    now = now or datetime.now(timezone.utc)
    if active_tasks is None:
        active_tasks = await _load_active_snapshots(db)
    if not active_tasks:
        return {}

    rates = await load_rates(db, now=now)
    return simulate_queue(active_tasks, rates, now)
