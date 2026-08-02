"""Документный сервис — единая точка работы с таблицами всех типов.

Документ = (карточка сметы, тип документа). Сервис прячет за собой то, что
физически данные лежат по-разному: перечень и полнота — плоскими строками
`{row_id, cells}`, смета и оптимизация — типизированными `EstimateRow`.
Роутер и клиент видят один контракт.

Ключевые правила, ради которых сервис и появился:
  * правки живут в черновике и попадают в рабочие строки только по «Применить»;
  * `rev` защищает от тихого затирания чужих правок;
  * право на запись определяет сервер (а не параметр в адресе страницы);
  * пока задача считается — только чтение;
  * входной файл заказчика неприкосновенен.
"""
from __future__ import annotations

import uuid as _uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from fastapi import HTTPException, status
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document_lock import LOCK_TTL_SECONDS, DocumentLock
from app.models.estimate_version import EstimateVersion
from app.models.history import TaskHistory
from app.models.project import Project
from app.models.summary_section_doc import SummarySectionDoc
from app.models.task import Task
from app.models.user import User
from app.models.workflow_card import WorkflowCard
from app.utils.auth import current_user_id
from app.utils.permissions import can_edit

logger = structlog.get_logger()

# --- Типы документов -------------------------------------------------------

KIND_LIST = "list"
KIND_COMPLETENESS = "completeness"
KIND_ESTIMATE = "estimate"
KIND_OPTIMIZATION = "optimization"
# Раздел сводной. Единственный тип, который живёт не в версиях: его строки —
# снимок внутри `summary_estimates.sections`, см. `_resolve_summary_section`.
KIND_SUMMARY_SECTION = "summary-section"

DOCUMENT_KINDS: tuple[str, ...] = (
    KIND_LIST, KIND_COMPLETENESS, KIND_ESTIMATE, KIND_OPTIMIZATION,
    KIND_SUMMARY_SECTION,
)

_KIND_TO_CARD_FIELD = {
    KIND_LIST: "list_task_id",
    KIND_COMPLETENESS: "completeness_task_id",
    KIND_ESTIMATE: "estimate_task_id",
    KIND_OPTIMIZATION: "optimization_task_id",
}

# Слот, в котором лежат версии документа этого типа.
_KIND_TO_FILE_SLOT = {
    KIND_LIST: "result",
    KIND_COMPLETENESS: "result",
    KIND_ESTIMATE: "estimate",
    KIND_OPTIMIZATION: "result",
    KIND_SUMMARY_SECTION: "summary",
}

_KIND_TO_ROW_FORMAT = {
    KIND_LIST: "generic",
    KIND_COMPLETENESS: "generic",
    KIND_ESTIMATE: "estimate",
    KIND_OPTIMIZATION: "estimate",
    KIND_SUMMARY_SECTION: "estimate",
}

_KIND_LABEL = {
    KIND_LIST: "Перечень",
    KIND_COMPLETENESS: "Полнота",
    KIND_ESTIMATE: "Смета",
    KIND_OPTIMIZATION: "Оптимизация",
    KIND_SUMMARY_SECTION: "Раздел сводной",
}

# Типы задач, у которых сохранение строк пересобирает xlsx результата.
_XLSX_REBUILD_TYPES = frozenset({
    "LIST_FROM_GRAND", "LIST_FROM_PROJECT",
    "CHECK_LIST_COMPLETENESS", "CHECK_PROJECT_COMPLETENESS",
})

# Читаемые названия полей типизированной строки сметы — для истории правок.
_ESTIMATE_FIELD_LABELS = {
    "name": "Наименование",
    "unit": "Ед. изм.",
    "qty": "Кол-во",
    "price_work": "Цена работ",
    "price_material": "Цена материалов",
    "cost": "Стоимость",
    "type": "Тип",
    "is_excluded": "Исключена",
    "num": "№",
}

# Глубина истории на документ: старые записи чистим, иначе снимки строк
# разрастаются без предела (одна запись сметы на 2000 строк — сотни КБ).
HISTORY_DEPTH = 20
# Снимок «как было» держим только у последних записей: он нужен для отката, но
# именно он и весит. Более старые записи остаются в списке как справка — с
# перечнем изменений, но без возможности отката. 2000 строк × 20 записей — это
# ~8 МБ на документ; со снимками только у 10 последних — вдвое меньше.
SNAPSHOT_DEPTH = 10
# Сколько изменений показываем детально; остальное — только счётчиком.
MAX_DETAILED_CHANGES = 200


@dataclass
class ResolvedDocument:
    card: WorkflowCard
    kind: str
    task: Task
    project: Project
    file_slot: str
    row_format: str
    versions: list[EstimateVersion]
    # Носитель черновика и `rev`: версия сметы либо — у раздела сводной —
    # запись `SummarySectionDoc`. Строки у них берутся из разных мест, поэтому
    # чтение и запись строк идут через `read_rows` / `_store_rows`.
    active: Optional[Any]
    # Только для kind='summary-section': сама сводная и место раздела в ней.
    summary: Optional[Any] = None
    section_index: Optional[int] = None


# ---------------------------------------------------------------------------
# Разрешение документа и прав
# ---------------------------------------------------------------------------

def _not_found() -> HTTPException:
    # Чужой документ неотличим от несуществующего — как и везде в проекте.
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Документ не найден")


async def _section_anchor_task(
    db: AsyncSession, card: WorkflowCard, section: dict
) -> Optional[Task]:
    """Задача, к которой привязывается история правок раздела.

    У раздела своей задачи нет — он снимок сметы карточки. История правок живёт
    в `task_history` (task_id обязателен), поэтому берём задачу, из версии
    которой раздел собран; если версии уже нет — задачу сметы карточки.
    """
    version_id = section.get("version_id")
    if version_id:
        version = await db.get(EstimateVersion, str(version_id))
        if version is not None:
            task = await db.get(Task, str(version.task_id))
            if task is not None:
                return task

    for field in ("estimate_task_id", "optimization_task_id"):
        task_id = getattr(card, field, None)
        if task_id:
            task = await db.get(Task, str(task_id))
            if task is not None:
                return task
    return None


async def _ensure_section_doc(
    db: AsyncSession, summary_id: str, card_id: str
) -> SummarySectionDoc:
    """Запись черновика и `rev` для раздела. Создаётся при первом открытии."""
    res = await db.execute(
        select(SummarySectionDoc).where(
            SummarySectionDoc.summary_id == summary_id,
            SummarySectionDoc.card_id == card_id,
        )
    )
    doc_row = res.scalar_one_or_none()
    if doc_row is not None:
        return doc_row

    doc_row = SummarySectionDoc(
        id=str(_uuid.uuid4()), summary_id=summary_id, card_id=card_id, rev=0,
    )
    db.add(doc_row)
    await db.flush()
    return doc_row


async def _resolve_summary_section(
    db: AsyncSession, card_id: str, current_user: dict
) -> ResolvedDocument:
    """Раздел сводной как документ.

    Хранилище у него своё: строки лежат снимком в `summary_estimates.sections`,
    а не в версии. Право на правку даёт проект — сводная принадлежит проекту, а
    не задаче, и не запирается на время расчёта сметы: раздел это снимок.
    """
    from app.models.summary_estimate import SummaryEstimate

    card = await db.get(WorkflowCard, card_id)
    if card is None or card.deleted_at is not None:
        raise _not_found()

    project = await db.get(Project, str(card.project_id))
    if project is None or not can_edit(project.owner_id, current_user, project.is_shared):
        raise _not_found()

    res = await db.execute(
        select(SummaryEstimate).where(SummaryEstimate.project_id == str(card.project_id))
    )
    summary = res.scalar_one_or_none()
    if summary is None:
        raise _not_found()

    sections = list(summary.sections or [])
    index = next(
        (
            i for i, section in enumerate(sections)
            if isinstance(section, dict) and str(section.get("card_id")) == str(card_id)
        ),
        None,
    )
    if index is None:
        raise _not_found()

    task = await _section_anchor_task(db, card, sections[index])
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Раздел сводной не привязан к смете",
        )

    doc_row = await _ensure_section_doc(db, str(summary.id), str(card_id))

    return ResolvedDocument(
        card=card,
        kind=KIND_SUMMARY_SECTION,
        task=task,
        project=project,
        file_slot=_KIND_TO_FILE_SLOT[KIND_SUMMARY_SECTION],
        row_format=_KIND_TO_ROW_FORMAT[KIND_SUMMARY_SECTION],
        versions=[],
        active=doc_row,
        summary=summary,
        section_index=index,
    )


async def resolve_document(
    db: AsyncSession,
    card_id: str,
    kind: str,
    current_user: dict,
    file_slot: Optional[str] = None,
    file_index: Optional[int] = None,
) -> ResolvedDocument:
    if kind not in DOCUMENT_KINDS:
        raise _not_found()

    if kind == KIND_SUMMARY_SECTION:
        try:
            return await _resolve_summary_section(db, card_id, current_user)
        except IntegrityError:
            # Двое открыли раздел одновременно и оба создали запись черновика:
            # чужая уже в базе — перечитываем документ целиком.
            await db.rollback()
            return await _resolve_summary_section(db, card_id, current_user)

    card = await db.get(WorkflowCard, card_id)
    if card is None or card.deleted_at is not None:
        raise _not_found()

    task_id = getattr(card, _KIND_TO_CARD_FIELD[kind], None)
    if not task_id:
        raise _not_found()

    task = await db.get(Task, str(task_id))
    if task is None:
        raise _not_found()
    if not can_edit(task.owner_id, current_user, task.is_shared):
        raise _not_found()

    project = await db.get(Project, str(card.project_id))
    if project is None:
        raise _not_found()

    slot = file_slot if file_slot == "input" else _KIND_TO_FILE_SLOT[kind]

    res = await db.execute(
        select(EstimateVersion)
        .where(
            EstimateVersion.task_id == str(task_id),
            EstimateVersion.file_slot == slot,
        )
        .order_by(EstimateVersion.version_number)
    )
    versions = list(res.scalars().all())
    if slot == "input" and file_index is not None:
        # У задачи может быть несколько входных файлов — версия каждого помечена
        # меткой input_N.
        label = f"input_{file_index}"
        versions = [v for v in versions if v.version_label == label]

    active = next((v for v in versions if not v.is_rolled_back), versions[0] if versions else None)

    return ResolvedDocument(
        card=card,
        kind=kind,
        task=task,
        project=project,
        file_slot=slot,
        row_format=_KIND_TO_ROW_FORMAT[kind],
        versions=versions,
        active=active,
    )


async def locate_by_task(
    db: AsyncSession, task_id: str, current_user: dict
) -> tuple[str, str, str]:
    """Задача → (проект, карточка, тип документа).

    Нужна там, где на руках только идентификатор задачи: старые ссылки вида
    /tasks/{id}/status и точки входа, оставшиеся от прежней навигации. Задача
    без карточки (создана вне сметы) сюда не попадает — вызывающий показывает
    прежнюю страницу задачи.
    """
    task = await db.get(Task, task_id)
    if task is None or not can_edit(task.owner_id, current_user, task.is_shared):
        raise _not_found()

    for kind, field in _KIND_TO_CARD_FIELD.items():
        res = await db.execute(
            select(WorkflowCard).where(
                getattr(WorkflowCard, field) == task_id,
                WorkflowCard.deleted_at.is_(None),
            ).limit(1)
        )
        card = res.scalar_one_or_none()
        if card is not None:
            return str(card.project_id), str(card.id), kind

    raise _not_found()


async def ensure_versions(
    db: AsyncSession,
    doc: ResolvedDocument,
    current_user: dict,
    file_index: Optional[int] = None,
) -> ResolvedDocument:
    """Создать V0 из файла, если версий ещё нет.

    Раньше это делал сам редактор при открытии; теперь — сервис, чтобы документ
    открывался одинаково из любой точки входа. Идемпотентно: при существующих
    версиях ничего не делает.
    """
    # У раздела сводной версий нет — есть готовый снимок строк внутри сводной.
    if doc.kind == KIND_SUMMARY_SECTION:
        return doc
    if doc.versions or doc.task.status != "completed":
        return doc

    from app.models.result import TaskResult
    from app.models.task_input_file import TaskInputFile
    from app.services import storage_service

    rows: Optional[list] = None
    label = "original"
    display = "V0 — Оригинал"

    if doc.file_slot == "input":
        from app.utils.xlsx_generic import parse_xlsx_to_generic_rows

        index = file_index or 0
        res = await db.execute(
            select(TaskInputFile).where(
                TaskInputFile.task_id == str(doc.task.id),
                TaskInputFile.file_index == index,
            )
        )
        source = res.scalar_one_or_none()
        if source is None:
            return doc
        rows = parse_xlsx_to_generic_rows(await storage_service.load_bytes(source.storage_key))
        label = f"input_{index}"
        display = f"V0 — Оригинал (файл {index})"

    elif doc.row_format == "generic":
        from app.utils.xlsx_generic import parse_xlsx_to_generic_rows

        res = await db.execute(
            select(TaskResult)
            .where(TaskResult.task_id == str(doc.task.id), TaskResult.slot == "result")
            .order_by(TaskResult.id.desc())
            .limit(1)
        )
        source = res.scalar_one_or_none()
        if source is None:
            return doc
        rows = parse_xlsx_to_generic_rows(await storage_service.load_bytes(source.storage_key))

    elif doc.kind == KIND_ESTIMATE:
        from app.services.estimate_parser import parse_estimate_excel

        res = await db.execute(
            select(TaskResult)
            .where(
                TaskResult.task_id == str(doc.task.id),
                TaskResult.slot.in_(["estimate", "result"]),
            )
            .order_by(TaskResult.id.desc())
            .limit(1)
        )
        source = res.scalar_one_or_none()
        if source is None:
            return doc
        try:
            rows = parse_estimate_excel(await storage_service.load_bytes(source.storage_key))
        except Exception as exc:  # noqa: BLE001 — показываем причину пользователю
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Не удалось разобрать файл сметы: {exc}",
            )
        display = "Исходная смета"

    if rows is None:
        # Версии оптимизации создаёт сам процесс оптимизации — сюда не попадаем.
        return doc

    count_res = await db.execute(
        select(EstimateVersion).where(EstimateVersion.task_id == str(doc.task.id))
    )
    next_number = max(
        (v.version_number for v in count_res.scalars().all()), default=-1
    ) + 1

    db.add(EstimateVersion(
        id=str(_uuid.uuid4()),
        task_id=str(doc.task.id),
        version_number=next_number,
        version_label=label,
        version_display_name=display,
        rows=rows,
        file_slot=doc.file_slot,
        task_type=doc.task.task_type,
    ))
    await db.commit()
    logger.info(
        "document_version_initialised",
        card_id=str(doc.card.id), kind=doc.kind, slot=doc.file_slot, rows=len(rows),
    )

    return await resolve_document(
        db, str(doc.card.id), doc.kind, current_user, doc.file_slot, file_index,
    )


def write_state(doc: ResolvedDocument, current_user: dict) -> tuple[bool, Optional[str]]:
    """Можно ли писать в документ и почему нет. Решает сервер, не клиент."""
    if doc.kind == KIND_SUMMARY_SECTION:
        # Раздел принадлежит проекту, а не задаче: право даёт проект, и идущий
        # пересчёт сметы раздел не запирает — он снимок и от расчёта не зависит.
        if not can_edit(doc.project.owner_id, current_user, doc.project.is_shared):
            return False, "no_permission"
        return True, None
    if doc.file_slot == "input":
        return False, "input_readonly"
    if not can_edit(doc.task.owner_id, current_user, doc.task.is_shared):
        return False, "no_permission"
    if doc.task.status in ("processing", "pending"):
        return False, "task_processing"
    return True, None


_READONLY_MESSAGE = {
    "input_readonly": "Исходный файл заказчика доступен только для чтения",
    "no_permission": "Недостаточно прав для изменения документа",
    "task_processing": "Идёт расчёт — документ доступен только для просмотра",
}


def ensure_writable(doc: ResolvedDocument, current_user: dict) -> None:
    can, reason = write_state(doc, current_user)
    if can:
        return
    if reason == "no_permission":
        raise _not_found()
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=_READONLY_MESSAGE.get(reason, "Документ недоступен для изменения"),
    )


def pick_version(doc: ResolvedDocument, version_id: Optional[str]) -> Any:
    if doc.kind == KIND_SUMMARY_SECTION:
        # Версий у раздела нет: носитель черновика и `rev` всегда один.
        if doc.active is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Раздел сводной не найден")
        return doc.active
    if version_id:
        for v in doc.versions:
            if str(v.id) == str(version_id):
                return v
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Версия не найдена")
    if doc.active is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Для документа ещё нет данных. Дождитесь завершения задачи.",
        )
    return doc.active


def read_rows(doc: ResolvedDocument, version: Any) -> list:
    """Рабочие строки документа.

    У всех типов, кроме раздела сводной, они лежат в версии; у раздела —
    снимком внутри сводной. Второго хранилища ни у кого нет.
    """
    if doc.kind == KIND_SUMMARY_SECTION:
        sections = list(doc.summary.sections or [])
        if doc.section_index is None or doc.section_index >= len(sections):
            return []
        section = sections[doc.section_index]
        return list(section.get("rows") or []) if isinstance(section, dict) else []
    return list(version.rows or [])


def _store_rows(doc: ResolvedDocument, version: Any, rows: list) -> None:
    if doc.kind != KIND_SUMMARY_SECTION:
        version.rows = rows
        return

    sections = list(doc.summary.sections or [])
    section = sections[doc.section_index]
    # Список пересобираем целиком: правка JSON «на месте» SQLAlchemy не замечает
    # и запись молча не доехала бы до базы.
    sections[doc.section_index] = {**section, "rows": rows}
    doc.summary.sections = sections
    doc.summary.updated_at = datetime.now(timezone.utc)


async def _claim_rev(
    db: AsyncSession, doc: ResolvedDocument, version_id: str, client_rev: int
) -> int:
    """Атомарная заявка на запись: `UPDATE ... WHERE rev = client_rev`."""
    model = SummarySectionDoc if doc.kind == KIND_SUMMARY_SECTION else EstimateVersion
    claim = await db.execute(
        update(model)
        .where(model.id == version_id, model.rev == client_rev)
        .values(rev=client_rev + 1)
        .execution_options(synchronize_session=False)
    )
    return claim.rowcount


async def user_display_name(db: AsyncSession, current_user: dict) -> str:
    uid = current_user_id(current_user)
    if uid is not None:
        user = await db.get(User, uid)
        if user is not None:
            return user.full_name or user.username or f"Пользователь {uid}"
    return current_user.get("username") or "Неизвестный пользователь"


# ---------------------------------------------------------------------------
# Черновик
# ---------------------------------------------------------------------------

async def save_draft(
    db: AsyncSession,
    doc: ResolvedDocument,
    version: Any,
    rows: list,
    current_user: dict,
) -> None:
    ensure_writable(doc, current_user)
    version.draft_rows = rows
    version.draft_updated_at = datetime.now(timezone.utc)
    version.draft_user_id = current_user_id(current_user)
    await db.commit()


async def discard_draft(db: AsyncSession, version: Any) -> None:
    version.draft_rows = None
    version.draft_updated_at = None
    version.draft_user_id = None


# ---------------------------------------------------------------------------
# Диф правок для истории
# ---------------------------------------------------------------------------

def _row_key(row: Any) -> Optional[str]:
    if not isinstance(row, dict):
        return None
    key = row.get("row_id") or row.get("id")
    return str(key) if key is not None else None


def _row_name(row: Any, row_format: str) -> str:
    if not isinstance(row, dict):
        return ""
    if row_format == "generic":
        cells = row.get("cells") or {}
        for candidate in ("Наименование", "наименование", "Name"):
            if candidate in cells:
                return str(cells.get(candidate) or "")
        return ""
    return str(row.get("name") or "")


def _row_fields(row: Any, row_format: str) -> dict:
    if not isinstance(row, dict):
        return {}
    if row_format == "generic":
        cells = row.get("cells")
        return dict(cells) if isinstance(cells, dict) else {}
    return {k: v for k, v in row.items() if k not in ("id", "lineage_id")}


def _field_label(field: str, row_format: str) -> str:
    if row_format == "generic":
        return field
    return _ESTIMATE_FIELD_LABELS.get(field, field)


def diff_rows(old_rows: list, new_rows: list, row_format: str) -> list[dict]:
    """Изменения по ячейкам: «строка 12, Цена работ: 3000 → 2500».

    Сопоставление строк — по идентификатору; строки без идентификатора
    сравниваются по позиции. Добавление и удаление строк фиксируются одной
    записью на строку, а не по каждому полю.
    """
    changes: list[dict] = []
    old_by_key = {}
    for idx, row in enumerate(old_rows):
        key = _row_key(row)
        old_by_key[key if key is not None else f"__pos_{idx}"] = row

    seen: set[str] = set()
    for idx, new_row in enumerate(new_rows):
        key = _row_key(new_row)
        lookup = key if key is not None else f"__pos_{idx}"
        seen.add(lookup)
        old_row = old_by_key.get(lookup)
        row_name = _row_name(new_row, row_format)

        if old_row is None:
            changes.append({
                "row_number": idx + 1, "row_id": key, "row_name": row_name,
                "field": "Строка", "previous": None, "new": "добавлена",
            })
            continue

        old_fields = _row_fields(old_row, row_format)
        new_fields = _row_fields(new_row, row_format)
        for field in dict.fromkeys([*old_fields, *new_fields]):
            before, after = old_fields.get(field), new_fields.get(field)
            if before == after:
                continue
            changes.append({
                "row_number": idx + 1, "row_id": key, "row_name": row_name,
                "field": _field_label(field, row_format),
                "previous": before, "new": after,
            })

    for idx, old_row in enumerate(old_rows):
        key = _row_key(old_row)
        lookup = key if key is not None else f"__pos_{idx}"
        if lookup in seen:
            continue
        changes.append({
            "row_number": idx + 1, "row_id": key,
            "row_name": _row_name(old_row, row_format),
            "field": "Строка", "previous": "была", "new": "удалена",
        })

    return changes


# ---------------------------------------------------------------------------
# Применение правок
# ---------------------------------------------------------------------------

async def _rebuild_result_xlsx(
    db: AsyncSession, doc: ResolvedDocument, rows: list
) -> None:
    """Пересобрать xlsx результата. Входные файлы не трогаем никогда."""
    if doc.file_slot != "result":
        return
    if doc.task.task_type not in _XLSX_REBUILD_TYPES:
        return

    from app.models.result import TaskResult
    from app.services import storage_service
    from app.utils.xlsx_generic import rows_to_xlsx

    res = await db.execute(
        select(TaskResult)
        .where(TaskResult.task_id == str(doc.task.id), TaskResult.slot == "result")
        .order_by(TaskResult.id.desc())
        .limit(1)
    )
    tr = res.scalar_one_or_none()
    if tr is None:
        return

    xlsx_bytes = rows_to_xlsx(rows)
    tr.storage_key = await storage_service.store_result_file(
        str(doc.task.id), "result", tr.file_name or "result.xlsx",
        tr.mime_type, xlsx_bytes,
    )
    tr.size_bytes = len(xlsx_bytes)


async def _sync_estimate_artifacts(
    db: AsyncSession, doc: ResolvedDocument, rows: list, version: Any = None
) -> None:
    """Смета: после правки пересобрать файл и итог задачи.

    Без этого редактор, `task.cost` и скачанный файл показывали бы три разных
    числа — ровно та проблема, ради которой затевалась Фаза 5. Версию и `rev`
    ведёт `apply_rows`, поэтому здесь только артефакты.
    """
    if doc.kind != KIND_ESTIMATE:
        return

    from app.services import estimate_store

    await estimate_store.sync_artifacts(db, doc.task, rows, version)


async def _trim_history(db: AsyncSession, task_id: str, kind: str) -> None:
    """Удержать историю в разумном объёме.

    Записи глубже HISTORY_DEPTH удаляем целиком; у записей между SNAPSHOT_DEPTH и
    HISTORY_DEPTH выбрасываем снимок строк — они остаются как справка «кто и что
    менял», но откатиться на них уже нельзя.
    """
    res = await db.execute(
        select(TaskHistory)
        .where(TaskHistory.task_id == task_id, TaskHistory.document_kind == kind)
        .order_by(TaskHistory.created_at.desc())
        .offset(SNAPSHOT_DEPTH)
    )
    older = list(res.scalars().all())

    stale_ids = [e.id for e in older[HISTORY_DEPTH - SNAPSHOT_DEPTH:]]
    if stale_ids:
        await db.execute(delete(TaskHistory).where(TaskHistory.id.in_(stale_ids)))

    for entry in older[: HISTORY_DEPTH - SNAPSHOT_DEPTH]:
        previous = entry.previous_value if isinstance(entry.previous_value, dict) else {}
        if previous.get("rows") is not None:
            entry.previous_value = {"rows_dropped": True}


async def apply_rows(
    db: AsyncSession,
    doc: ResolvedDocument,
    version: Any,
    rows: Optional[list],
    client_rev: int,
    current_user: dict,
    operation_type: str = "document_edit",
    description_override: Optional[str] = None,
) -> dict:
    """Черновик (или переданные строки) → рабочие строки. Единственная точка записи."""
    ensure_writable(doc, current_user)

    # Значения снимаем заранее: после отката транзакции ORM-объекты сброшены.
    task_id, kind, version_id = str(doc.task.id), doc.kind, version.id

    if client_rev != version.rev:
        raise await _stale_rev_error(db, task_id, kind)

    old_rows = read_rows(doc, version)

    new_rows = rows if rows is not None else version.draft_rows
    if new_rows is None:
        new_rows = old_rows

    changes = diff_rows(old_rows, new_rows, doc.row_format)

    if not changes:
        # Нечего применять — черновик просто убираем, rev не трогаем.
        await discard_draft(db, version)
        await db.commit()
        return {"version_id": str(version.id), "rev": version.rev,
                "rows_count": len(new_rows), "changes_count": 0}

    user_name = await user_display_name(db, current_user)

    # Атомарная заявка на запись. Проверка `client_rev != version.rev` выше даёт
    # быстрый и понятный отказ, но между ней и коммитом есть окно: два «Применить»
    # с одним rev в параллельных запросах прошли бы оба, и второй тихо затёр бы
    # первого. UPDATE ... WHERE rev = client_rev закрывает окно на уровне БД —
    # совпадение получит ровно один запрос.
    if await _claim_rev(db, doc, version_id, client_rev) == 0:
        await db.rollback()
        raise await _stale_rev_error(db, task_id, kind)

    _store_rows(doc, version, new_rows)
    version.rev = client_rev + 1
    await discard_draft(db, version)

    await _rebuild_result_xlsx(db, doc, new_rows)
    await _sync_estimate_artifacts(db, doc, new_rows, version)
    if doc.kind != KIND_SUMMARY_SECTION:
        # Раздел сводной — снимок: правка в нём не означает, что руками правили
        # саму смету задачи.
        doc.task.manually_edited_at = datetime.now(timezone.utc)

    label = _KIND_LABEL.get(doc.kind, doc.kind)
    db.add(TaskHistory(
        id=str(_uuid.uuid4()),
        task_id=str(doc.task.id),
        operation_type=operation_type,
        slot=doc.file_slot,
        description=description_override or (
            f"{user_name}: изменено значений — {len(changes)} (документ «{label}»)"
        ),
        # previous_value хранит снимок «как было» — по нему работает откат.
        previous_value={"rows": old_rows},
        # new_value хранит только перечень изменений: второй снимок строк удвоил
        # бы объём истории, а текущее состояние и так лежит в версии.
        new_value={
            "changes": changes[:MAX_DETAILED_CHANGES],
            "changes_count": len(changes),
        },
        user_id=current_user_id(current_user),
        user_name=user_name,
        document_kind=doc.kind,
    ))
    # Явный flush: чистка истории считает записи запросом, и без него новая
    # запись не попала бы в подсчёт — глубина «плавала» бы на единицу в
    # зависимости от настройки autoflush сессии.
    await db.flush()
    await _trim_history(db, task_id, kind)
    await db.commit()

    logger.info(
        "document_applied", card_id=str(doc.card.id), kind=doc.kind,
        rev=version.rev, changes=len(changes), user=user_name,
    )
    return {"version_id": str(version.id), "rev": version.rev,
            "rows_count": len(new_rows), "changes_count": len(changes)}


async def set_coefficient(
    db: AsyncSession,
    doc: ResolvedDocument,
    version: Any,
    coefficient: Optional[dict],
    current_user: dict,
) -> dict:
    """Поставить или снять коэффициент к ценам документа.

    Коэффициент — обратимая настройка: исходные цены строк он не трогает
    никогда, поэтому снятие возвращает ровно прежние числа. Меняются только
    итоги, скачиваемый файл и выгрузка. `rev` не двигаем: строки не менялись, и
    у соседа, открывшего документ рядом, «Применить» не должно ломаться.
    """
    ensure_writable(doc, current_user)
    if doc.row_format != "estimate":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="У этого документа нет цен, коэффициент к нему неприменим",
        )

    version.coefficient = coefficient

    if doc.kind == KIND_ESTIMATE:
        # Файл и итог задачи считаются с коэффициентом — иначе на экране одно
        # число, а в скачанном файле другое.
        await _sync_estimate_artifacts(db, doc, read_rows(doc, version), version)

    user_name = await user_display_name(db, current_user)
    if coefficient is None:
        description = f"{user_name}: коэффициент к ценам снят"
    else:
        description = (
            f"{user_name}: коэффициент к ценам — работы ×{coefficient.get('work', 1)}, "
            f"материалы ×{coefficient.get('material', 1)}"
        )
        scope = coefficient.get("scope", "all")
        if isinstance(scope, list):
            description += f" (строк: {len(scope)})"

    db.add(TaskHistory(
        id=str(_uuid.uuid4()),
        task_id=str(doc.task.id),
        operation_type="document_coefficient",
        slot=doc.file_slot,
        description=description,
        previous_value={},
        new_value={"coefficient": coefficient, "changes_count": 0, "changes": []},
        user_id=current_user_id(current_user),
        user_name=user_name,
        document_kind=doc.kind,
    ))
    await db.commit()

    logger.info(
        "document_coefficient_set",
        card_id=str(doc.card.id), kind=doc.kind, coefficient=coefficient,
    )
    return {"coefficient": coefficient}


async def _stale_rev_error(db: AsyncSession, task_id: str, kind: str) -> HTTPException:
    """Принимает идентификаторы, а не ORM-объекты: вызывается в том числе после
    rollback, когда объекты сессии сброшены и любое обращение к их полям
    попыталось бы сходить в БД из синхронного контекста."""
    last = await _last_editor(db, task_id, kind)
    who = f" Последним сохранял: {last}." if last else ""
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            "Документ изменился, пока вы работали."
            f"{who} Обновите страницу, чтобы не потерять чужие правки."
        ),
    )


async def _last_editor(db: AsyncSession, task_id: str, kind: str) -> Optional[str]:
    res = await db.execute(
        select(TaskHistory.user_name)
        .where(TaskHistory.task_id == task_id, TaskHistory.document_kind == kind)
        .order_by(TaskHistory.created_at.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


# ---------------------------------------------------------------------------
# История и откат
# ---------------------------------------------------------------------------

async def list_history(db: AsyncSession, doc: ResolvedDocument) -> list[dict]:
    res = await db.execute(
        select(TaskHistory)
        .where(
            TaskHistory.task_id == str(doc.task.id),
            TaskHistory.document_kind == doc.kind,
        )
        .order_by(TaskHistory.created_at.desc())
    )
    entries = []
    for e in res.scalars().all():
        payload = e.new_value if isinstance(e.new_value, dict) else {}
        entries.append({
            "id": str(e.id),
            "kind": e.document_kind,
            "operation_type": e.operation_type,
            "description": e.description,
            "user_id": e.user_id,
            "user_name": e.user_name or "",
            "created_at": e.created_at.isoformat(),
            "changes_count": payload.get("changes_count", 0),
            "changes": payload.get("changes", []),
        })
    return entries


async def revert_to_entry(
    db: AsyncSession,
    doc: ResolvedDocument,
    version: Any,
    entry_id: str,
    current_user: dict,
) -> dict:
    entry = await db.get(TaskHistory, entry_id)
    if (
        entry is None
        or str(entry.task_id) != str(doc.task.id)
        or entry.document_kind != doc.kind
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Запись истории не найдена")

    previous = entry.previous_value if isinstance(entry.previous_value, dict) else {}
    rows = previous.get("rows")
    if rows is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="У этой записи нет сохранённого состояния для отката",
        )

    user_name = await user_display_name(db, current_user)
    return await apply_rows(
        db, doc, version, rows, version.rev, current_user,
        operation_type="document_revert",
        description_override=(
            f"{user_name}: откат к состоянию от "
            f"{entry.created_at.strftime('%d.%m.%Y %H:%M')}"
        ),
    )


# ---------------------------------------------------------------------------
# Присутствие
# ---------------------------------------------------------------------------

def _is_fresh(lock: DocumentLock) -> bool:
    hb = lock.heartbeat_at
    if hb is None:
        return False
    if hb.tzinfo is None:
        hb = hb.replace(tzinfo=timezone.utc)
    return hb > datetime.now(timezone.utc) - timedelta(seconds=LOCK_TTL_SECONDS)


def _lock_info(lock: DocumentLock) -> dict:
    hb = lock.heartbeat_at
    return {
        "user_id": lock.user_id,
        "user_name": lock.user_name or "",
        "heartbeat_at": hb.isoformat() if hb else "",
    }


async def _current_lock(
    db: AsyncSession, card_id: str, kind: str
) -> Optional[DocumentLock]:
    res = await db.execute(
        select(DocumentLock).where(
            DocumentLock.card_id == card_id, DocumentLock.kind == kind
        )
    )
    return res.scalar_one_or_none()


async def get_foreign_lock(
    db: AsyncSession, card_id: str, kind: str, current_user: dict
) -> Optional[dict]:
    """Кто ещё редактирует документ. Свой heartbeat и протухшие — не считаем."""
    lock = await _current_lock(db, card_id, kind)
    if lock is None or not _is_fresh(lock):
        return None
    if lock.user_id is not None and lock.user_id == current_user_id(current_user):
        return None
    return _lock_info(lock)


async def heartbeat(
    db: AsyncSession, card_id: str, kind: str, current_user: dict
) -> Optional[dict]:
    """Отметиться в документе. Держатель — первый пришедший, пока не ушёл."""
    uid = current_user_id(current_user)
    lock = await _current_lock(db, card_id, kind)

    if lock is not None and _is_fresh(lock) and lock.user_id != uid:
        return _lock_info(lock)  # документ уже за другим — не перехватываем

    user_name = await user_display_name(db, current_user)
    now = datetime.now(timezone.utc)
    if lock is None:
        db.add(DocumentLock(
            id=str(_uuid.uuid4()), card_id=card_id, kind=kind,
            user_id=uid, user_name=user_name, heartbeat_at=now,
        ))
    else:
        lock.user_id = uid
        lock.user_name = user_name
        lock.heartbeat_at = now
    await db.commit()
    return None
