"""Единый источник правды по смете.

До этого модуля смета жила в двух местах: `task.progress_data['items']` (что
выдал расчёт) и `EstimateVersion.rows` (что видит редактор). Правки шли то туда,
то сюда, и пользователь мог увидеть три разных числа для одной строки — на
странице задачи, в редакторе и в скачанном файле.

Теперь правда одна — рабочая версия сметы (`EstimateVersion`, слот `estimate`).
`progress_data['items']` остаётся записью «что выдал ИИ» и больше никем не
переписывается.

Все записи проходят через этот модуль, поэтому три величины всегда сходятся:
строки версии, `task.cost` и содержимое скачиваемого xlsx.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.estimate_version import EstimateVersion
from app.models.project import Project
from app.models.result import TaskResult
from app.models.task import Task
from app.services import storage_service
from app.utils.estimate_rows import items_to_rows, rows_to_items
from app.utils.xlsx_exporter import DEFAULT_OVERHEAD_PCT, generate_estimate_xlsx

logger = structlog.get_logger()

# Прежние 3%: значение по умолчанию у проекта, поведение не меняется.
DEFAULT_PCT = DEFAULT_OVERHEAD_PCT
ESTIMATE_SLOT = "estimate"
ESTIMATE_FILENAME = "Смета_из_перечня.xlsx"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ---------------------------------------------------------------------------
# Чтение
# ---------------------------------------------------------------------------

async def get_working_version(db: AsyncSession, task_id: str) -> Optional[EstimateVersion]:
    """Рабочая версия сметы — та, из которой считается всё остальное."""
    res = await db.execute(
        select(EstimateVersion)
        .where(
            EstimateVersion.task_id == str(task_id),
            EstimateVersion.file_slot == ESTIMATE_SLOT,
        )
        .order_by(EstimateVersion.version_number)
    )
    versions = list(res.scalars().all())
    if not versions:
        return None
    return next((v for v in versions if not v.is_rolled_back), versions[0])


async def read_items(db: AsyncSession, task: Task) -> list[dict]:
    """Смета в формате позиций — для генератора xlsx и для подбора цен через ИИ.

    Источник — рабочая версия. `progress_data['items']` используется только как
    запасной вариант: у смет, посчитанных до перехода на единый источник, версии
    ещё может не быть.
    """
    version = await get_working_version(db, str(task.id))
    if version is not None and version.rows:
        return rows_to_items(version.rows)
    return list((task.progress_data or {}).get("items") or [])


# ---------------------------------------------------------------------------
# Запись
# ---------------------------------------------------------------------------

def _clean_name(result: Optional[TaskResult]) -> Optional[str]:
    """Имя файла из записи результата, если оно вообще пригодно как имя."""
    name = getattr(result, "file_name", None) if result is not None else None
    return name.strip() if isinstance(name, str) and name.strip() else None


async def _store_estimate_file(db: AsyncSession, task: Task, data: bytes) -> None:
    res = await db.execute(
        select(TaskResult).where(
            TaskResult.task_id == str(task.id),
            TaskResult.slot == ESTIMATE_SLOT,
        ).order_by(TaskResult.id.desc()).limit(1)
    )
    existing = res.scalar_one_or_none()
    file_name = _clean_name(existing)
    if not file_name:
        # Первый файл в слоте `estimate` наследует имя от файла расчёта: оно
        # собрано из названия задачи, и терять его при первой же правке незачем.
        res_result = await db.execute(
            select(TaskResult).where(
                TaskResult.task_id == str(task.id),
                TaskResult.slot == "result",
            ).order_by(TaskResult.id.desc()).limit(1)
        )
        file_name = _clean_name(res_result.scalar_one_or_none()) or ESTIMATE_FILENAME

    key = await storage_service.store_result_file(
        str(task.id), ESTIMATE_SLOT, file_name, XLSX_MIME, data,
    )
    if existing is not None:
        existing.storage_key = key
        existing.size_bytes = len(data)
    else:
        db.add(TaskResult(
            task_id=str(task.id),
            file_name=file_name,
            mime_type=XLSX_MIME,
            storage_key=key,
            size_bytes=len(data),
            slot=ESTIMATE_SLOT,
        ))


async def expense_settings(
    db: AsyncSession, task: Task, version: Optional[EstimateVersion] = None
) -> tuple:
    """Ставки доп. расходов и коэффициент для сметы задачи.

    Порядок: проценты берём у проекта — это единая настройка, из-за отсутствия
    которой 3% были зашиты в генераторе файла. Версия может их переопределить
    (`expenses_overridden`) — так работает сравнение версий. Коэффициент всегда
    принадлежит версии: он настройка конкретного документа.
    """
    if version is None:
        version = await get_working_version(db, str(task.id))

    overhead = DEFAULT_PCT
    transport = DEFAULT_PCT
    if task.project_id:
        project = await db.get(Project, str(task.project_id))
        if project is not None:
            overhead = float(project.overhead_pct if project.overhead_pct is not None else DEFAULT_PCT)
            transport = float(project.transport_pct if project.transport_pct is not None else DEFAULT_PCT)

    coefficient = None
    if version is not None:
        coefficient = version.coefficient
        if version.expenses_overridden:
            overhead = float(version.overhead_pct or 0)
            transport = float(version.transport_pct or 0)

    return overhead, transport, coefficient


async def sync_artifacts(
    db: AsyncSession,
    task: Task,
    rows: list,
    version: Optional[EstimateVersion] = None,
) -> float:
    """Пересобрать файл сметы и итог задачи по строкам. Версию не трогает.

    Вызывается там, где строки версии уже записаны — в документном сервисе,
    который сам ведёт `rev`, черновик и историю правок.
    """
    overhead_pct, transport_pct, coefficient = await expense_settings(db, task, version)
    excel_data, grand_total = generate_estimate_xlsx(
        rows_to_items(rows),
        overhead_pct=overhead_pct,
        transport_pct=transport_pct,
        coefficient=coefficient,
    )
    await _store_estimate_file(db, task, excel_data)

    task.cost = Decimal(str(round(grand_total, 2)))
    task.estimation_status = "estimated"
    task.updated_at = datetime.now(timezone.utc)
    await sync_summary_sections(db, task, rows, version)
    return grand_total


async def sync_summary_sections(
    db: AsyncSession,
    task: Task,
    rows: list,
    version: Optional[EstimateVersion] = None,
) -> None:
    """Разделы сводной, собранные из этой сметы, показывают её текущие строки.

    Раздел сводной хранит снимок строк. Пока снимок жил своей жизнью, сводная и
    смета молча расходились: человек правил сводную неделю, а при смене состава
    разделов работа исчезала. Теперь снимок производный — его обновляет тот же
    модуль, что пишет смету, поэтому расходиться нечему.

    Ссылка на версию переставляется на ту, в которую строки записаны: иначе
    следующая смена состава собрала бы раздел из устаревшей версии.
    """
    from app.models.summary_estimate import SummaryEstimate
    from app.models.workflow_card import WorkflowCard

    res = await db.execute(
        select(WorkflowCard).where(WorkflowCard.estimate_task_id == str(task.id))
    )
    cards = {str(card.id): card for card in res.scalars().all()}
    if not cards:
        return

    project_ids = {str(card.project_id) for card in cards.values()}
    res = await db.execute(
        select(SummaryEstimate).where(SummaryEstimate.project_id.in_(project_ids))
    )

    for summary in res.scalars().all():
        sections = list(summary.sections or [])
        touched = False
        for index, section in enumerate(sections):
            if not isinstance(section, dict) or str(section.get("card_id")) not in cards:
                continue
            updated = {**section, "rows": rows}
            if version is not None:
                updated["version_id"] = str(version.id)
                updated["version_display_name"] = version.version_display_name
            sections[index] = updated
            touched = True
        if touched:
            # Список пересобираем целиком: правку JSON «на месте» SQLAlchemy не
            # замечает и запись молча не доехала бы до базы.
            summary.sections = sections
            summary.updated_at = datetime.now(timezone.utc)


async def _new_version(db: AsyncSession, task: Task, rows: list) -> EstimateVersion:
    count_res = await db.execute(
        select(EstimateVersion).where(EstimateVersion.task_id == str(task.id))
    )
    next_number = max(
        (v.version_number for v in count_res.scalars().all()), default=-1
    ) + 1
    version = EstimateVersion(
        id=str(_uuid.uuid4()),
        task_id=str(task.id),
        version_number=next_number,
        version_label="original",
        version_display_name="Смета",
        rows=rows,
        file_slot=ESTIMATE_SLOT,
        task_type=task.task_type,
    )
    db.add(version)
    return version


async def ensure_working_version(
    db: AsyncSession,
    task: Task,
    rows: list,
    *,
    commit: bool = True,
) -> EstimateVersion:
    """Создать рабочую версию, если её ещё нет. Файл и итог не трогает.

    Вызывается по завершении расчёта: файл и `task.cost` там уже записаны из тех
    же позиций, пересобирать их второй раз незачем. Идемпотентно — при
    существующей версии возвращает её как есть, чтобы повторный прогон не
    затирал правки человека.
    """
    version = await get_working_version(db, str(task.id))
    if version is not None:
        return version

    version = await _new_version(db, task, rows)
    if commit:
        await db.commit()
    logger.info("estimate_version_created", task_id=str(task.id), rows=len(rows))
    return version


async def write_rows(
    db: AsyncSession,
    task: Task,
    rows: list,
    *,
    commit: bool = True,
) -> tuple[EstimateVersion, float]:
    """Записать смету целиком: строки версии, файл и итог задачи.

    Точка входа для всего, что приходит не из редактора: завершение расчёта,
    исправление пустых цен, пересчёт цены строки, старый эндпоинт сохранения.
    `rev` увеличивается, поэтому открытый рядом редактор со старым `rev` получит
    честный отказ, а не тихо затрёт результат расчёта.
    """
    version = await get_working_version(db, str(task.id))
    if version is None:
        version = await _new_version(db, task, rows)
    else:
        version.rows = rows
        version.rev = (version.rev or 0) + 1
        # Черновик относился к прежним строкам: оставить его — значит предложить
        # человеку «применить» правки поверх уже изменившейся сметы.
        version.draft_rows = None
        version.draft_updated_at = None
        version.draft_user_id = None

    grand_total = await sync_artifacts(db, task, rows, version)

    if commit:
        await db.commit()

    logger.info(
        "estimate_written",
        task_id=str(task.id), rows=len(rows), grand_total=grand_total,
    )
    return version, grand_total


async def write_items(
    db: AsyncSession,
    task: Task,
    items: list,
    *,
    commit: bool = True,
) -> tuple[EstimateVersion, float]:
    """То же, что `write_rows`, но на входе позиции в формате ИИ."""
    return await write_rows(db, task, items_to_rows(items), commit=commit)
