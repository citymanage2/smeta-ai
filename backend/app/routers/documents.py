"""Единый API документов — то, с чем работает единый редактор таблиц.

Один контракт на все типы документов карточки сметы. Вся логика прав, черновиков,
истории и присутствия живёт в `services/document_service.py`; здесь — только
HTTP-обвязка.
"""
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.document import (
    ApplyRequest,
    ApplyResponse,
    DocumentMeta,
    DocumentRows,
    HeartbeatResponse,
    HistoryEntryOut,
    ProjectSettings,
    SaveDraftRequest,
    VersionBrief,
)
from app.services import document_service as svc
from app.utils.auth import get_current_user

logger = structlog.get_logger()

router = APIRouter(prefix="/documents", tags=["documents"])

# Слот файла: 'input' открывает документ исходного файла заказчика (только чтение).
FileSlotQuery = Query(default=None, description="Слот файла: 'input' — исходный файл")
FileIndexQuery = Query(default=None, description="Номер входного файла (для file_slot='input')")


@router.get("/by-task/{task_id}")
async def locate_document_by_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Какой документ соответствует задаче — для старых ссылок вида /tasks/{id}."""
    project_id, card_id, kind = await svc.locate_by_task(db, task_id, current_user)
    return {"project_id": project_id, "card_id": card_id, "kind": kind}


@router.get("/{card_id}/{kind}", response_model=DocumentMeta)
async def get_document_meta(
    card_id: str,
    kind: str,
    file_slot: Optional[str] = FileSlotQuery,
    file_index: Optional[int] = FileIndexQuery,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Метаданные документа: версии, права, черновик, коэффициент, присутствие."""
    doc = await svc.resolve_document(db, card_id, kind, current_user, file_slot, file_index)
    # Первое открытие документа создаёт V0 из файла — раньше это делал клиент.
    doc = await svc.ensure_versions(db, doc, current_user, file_index)
    can_write, reason = svc.write_state(doc, current_user)
    active = doc.active
    lock = await svc.get_foreign_lock(db, card_id, kind, current_user)

    return DocumentMeta(
        card_id=str(doc.card.id),
        kind=doc.kind,
        row_format=doc.row_format,
        file_slot=doc.file_slot,
        task_id=str(doc.task.id),
        task_type=doc.task.task_type,
        task_status=doc.task.status,
        can_write=can_write,
        readonly_reason=reason,
        rev=active.rev if active else 0,
        active_version_id=str(active.id) if active else None,
        versions=[
            VersionBrief(
                id=str(v.id),
                version_number=v.version_number,
                version_label=v.version_label,
                version_display_name=v.version_display_name,
                is_rolled_back=v.is_rolled_back,
                created_at=v.created_at.isoformat(),
                overhead_pct=float(v.overhead_pct or 0),
                transport_pct=float(v.transport_pct or 0),
                contingency_pct=float(v.contingency_pct or 0),
                expenses_overridden=bool(v.expenses_overridden),
            )
            for v in doc.versions
        ],
        coefficient=active.coefficient if active else None,
        has_draft=bool(active and active.draft_rows is not None),
        draft_updated_at=(
            active.draft_updated_at.isoformat()
            if active and active.draft_updated_at else None
        ),
        lock=lock,
        project=ProjectSettings(
            overhead_pct=doc.project.overhead_pct,
            transport_pct=doc.project.transport_pct,
        ),
    )


@router.get("/{card_id}/{kind}/rows", response_model=DocumentRows)
async def get_document_rows(
    card_id: str,
    kind: str,
    version_id: Optional[str] = Query(default=None),
    file_slot: Optional[str] = FileSlotQuery,
    file_index: Optional[int] = FileIndexQuery,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    doc = await svc.resolve_document(db, card_id, kind, current_user, file_slot, file_index)
    doc = await svc.ensure_versions(db, doc, current_user, file_index)
    version = svc.pick_version(doc, version_id)
    return DocumentRows(
        version_id=str(version.id),
        rev=version.rev or 0,
        rows=version.rows or [],
        draft_rows=version.draft_rows,
    )


@router.put("/{card_id}/{kind}/draft")
async def save_document_draft(
    card_id: str,
    kind: str,
    body: SaveDraftRequest,
    file_slot: Optional[str] = FileSlotQuery,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Автосохранение правок. Рабочие строки и файл не трогает."""
    doc = await svc.resolve_document(db, card_id, kind, current_user, file_slot)
    version = svc.pick_version(doc, body.version_id)
    await svc.save_draft(db, doc, version, body.rows, current_user)
    return {"version_id": str(version.id), "rows_count": len(body.rows)}


@router.delete("/{card_id}/{kind}/draft")
async def drop_document_draft(
    card_id: str,
    kind: str,
    version_id: Optional[str] = Query(default=None),
    file_slot: Optional[str] = FileSlotQuery,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Отказаться от непринятых правок."""
    doc = await svc.resolve_document(db, card_id, kind, current_user, file_slot)
    version = svc.pick_version(doc, version_id)
    svc.ensure_writable(doc, current_user)
    await svc.discard_draft(db, version)
    await db.commit()
    return {"version_id": str(version.id), "status": "discarded"}


@router.post("/{card_id}/{kind}/apply", response_model=ApplyResponse)
async def apply_document(
    card_id: str,
    kind: str,
    body: ApplyRequest,
    file_slot: Optional[str] = FileSlotQuery,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """«Применить»: черновик (или переданные строки) → рабочие строки."""
    doc = await svc.resolve_document(db, card_id, kind, current_user, file_slot)
    version = svc.pick_version(doc, body.version_id)
    result = await svc.apply_rows(
        db, doc, version, body.rows, body.rev, current_user
    )
    return ApplyResponse(**result)


@router.get("/{card_id}/{kind}/history", response_model=list[HistoryEntryOut])
async def get_document_history(
    card_id: str,
    kind: str,
    file_slot: Optional[str] = FileSlotQuery,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    doc = await svc.resolve_document(db, card_id, kind, current_user, file_slot)
    return [HistoryEntryOut(**entry) for entry in await svc.list_history(db, doc)]


@router.post("/{card_id}/{kind}/history/{entry_id}/revert", response_model=ApplyResponse)
async def revert_document(
    card_id: str,
    kind: str,
    entry_id: str,
    version_id: Optional[str] = Query(default=None),
    file_slot: Optional[str] = FileSlotQuery,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Вернуть документ к состоянию до выбранной правки."""
    doc = await svc.resolve_document(db, card_id, kind, current_user, file_slot)
    version = svc.pick_version(doc, version_id)
    result = await svc.revert_to_entry(db, doc, version, entry_id, current_user)
    return ApplyResponse(**result)


@router.post("/{card_id}/{kind}/heartbeat", response_model=HeartbeatResponse)
async def document_heartbeat(
    card_id: str,
    kind: str,
    file_slot: Optional[str] = FileSlotQuery,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Отметиться в документе и узнать, не редактирует ли его кто-то ещё."""
    doc = await svc.resolve_document(db, card_id, kind, current_user, file_slot)
    lock = await svc.heartbeat(db, str(doc.card.id), doc.kind, current_user)
    return HeartbeatResponse(lock=lock)
