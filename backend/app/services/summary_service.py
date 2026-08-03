import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.estimate_version import EstimateVersion
from app.models.project import Project
from app.models.summary_estimate import SummaryEstimate
from app.models.summary_section_doc import SummarySectionDoc
from app.models.workflow_card import WorkflowCard
from app.schemas.summary_estimate import (
    SummaryEstimateCreate,
    SummaryEstimateUpdate,
    SummaryOverrides,
)

logger = structlog.get_logger()


async def get_summary(project_id: str, db: AsyncSession) -> Optional[SummaryEstimate]:
    result = await db.execute(
        select(SummaryEstimate).where(SummaryEstimate.project_id == project_id)
    )
    return result.scalar_one_or_none()


async def _build_sections_snapshot(sections_input: list, db: AsyncSession) -> list[dict]:
    """Копирует строки из EstimateVersion в snapshot сводной (изоляция от оригинала)."""
    snapshot: list[dict] = []
    for sec in sections_input:
        card = await db.get(WorkflowCard, sec.card_id)
        if card is None:
            logger.warning("WorkflowCard not found, skipping", card_id=sec.card_id)
            continue

        version_result = await db.execute(
            select(EstimateVersion).where(EstimateVersion.id == sec.version_id)
        )
        version = version_result.scalar_one_or_none()
        if version is None:
            logger.warning("EstimateVersion not found, skipping", version_id=sec.version_id)
            continue

        snapshot.append({
            "card_id": sec.card_id,
            "card_name": card.name,
            "version_id": sec.version_id,
            "version_display_name": version.version_display_name,
            "rows": list(version.rows or []),
        })
    return snapshot


async def create_summary(
    project_id: str,
    data: SummaryEstimateCreate,
    db: AsyncSession,
) -> SummaryEstimate:
    overrides = (data.overrides or SummaryOverrides()).model_dump(mode="json")
    sections = await _build_sections_snapshot(data.sections, db)

    summary = SummaryEstimate(
        id=str(uuid.uuid4()),
        project_id=project_id,
        sections=sections,
        overrides=overrides,
        total_for_customer=Decimal("0"),
    )
    db.add(summary)

    project = await db.get(Project, project_id)
    if project is not None:
        project.summary_total = Decimal("0")

    await db.commit()
    await db.refresh(summary)
    logger.info("SummaryEstimate created", project_id=project_id, summary_id=summary.id)
    return summary


async def set_sections(
    summary: SummaryEstimate,
    data: SummaryEstimateCreate,
    db: AsyncSession,
) -> SummaryEstimate:
    """Сменить состав разделов, не теряя работу человека.

    Раньше «Изменить разделы» удаляло сводную целиком и собирало разделы заново
    из смет: правки во всех разделах пропадали вместе с черновиками и историей,
    без единого предупреждения. Здесь меняется только состав — раздел, который
    остался в списке, сохраняет свои строки.

    Строки пересобираются лишь тогда, когда человек выбрал для раздела **другую
    версию** сметы: это осознанный выбор, и он должен что-то менять.
    """
    stored = {
        str(section["card_id"]): section
        for section in (summary.sections or [])
        if isinstance(section, dict) and section.get("card_id") is not None
    }

    sections: list[dict] = []
    for wanted in data.sections:
        kept = stored.get(str(wanted.card_id))
        if kept is not None and str(kept.get("version_id")) == str(wanted.version_id):
            sections.append(kept)
            continue
        fresh = await _build_sections_snapshot([wanted], db)
        # Карточки или версии уже нет — пропускаем, как при первой сборке.
        if fresh:
            # Настройки раздела (налог, имя) переживают смену версии: человек
            # менял источник строк, а не бланк.
            sections.append({**(kept or {}), **fresh[0]})

    dropped = set(stored) - {str(section["card_id"]) for section in sections}
    if dropped:
        # Черновик убранного раздела нельзя оставлять: вернув раздел, человек
        # увидел бы «есть непринятые правки» от строк, которых уже нет, и
        # «Применить» затёрло бы заново собранный снимок.
        await db.execute(
            delete(SummarySectionDoc).where(
                SummarySectionDoc.summary_id == summary.id,
                SummarySectionDoc.card_id.in_(dropped),
            )
        )

    summary.sections = sections
    if data.overrides is not None:
        summary.overrides = data.overrides.model_dump(mode="json")
    summary.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(summary)
    logger.info(
        "SummaryEstimate sections changed",
        summary_id=summary.id, sections=len(sections), dropped=len(dropped),
    )
    return summary


def _merge_sections(stored: list, incoming: list) -> list:
    """Сохранить настройки разделов, но не их строки.

    Строки раздела правятся только через документный API (`summary-section`,
    план 2026-08-02, Фаза 7). Если бы страница сводной продолжала присылать свой
    снимок строк, у строки снова стало бы два писателя — ровно та беда, из-за
    которой смета до Фазы 5 показывала три разных числа. Поэтому из присланного
    берём состав и настройки разделов (налог, порядок, имя), а строки —
    из хранилища.
    """
    rows_by_card = {}
    for section in stored or []:
        if isinstance(section, dict) and section.get("card_id") is not None:
            rows_by_card[str(section["card_id"])] = section.get("rows") or []

    merged: list[dict] = []
    for section in incoming or []:
        if not isinstance(section, dict):
            continue
        card_id = section.get("card_id")
        kept = rows_by_card.get(str(card_id)) if card_id is not None else None
        # Раздел, которого в хранилище ещё нет (добавлен вручную), приходит со
        # своими строками — терять их нельзя.
        merged.append({**section, "rows": kept if kept is not None else (section.get("rows") or [])})
    return merged


async def update_summary(
    summary: SummaryEstimate,
    data: SummaryEstimateUpdate,
    db: AsyncSession,
) -> SummaryEstimate:
    if data.sections is not None:
        summary.sections = _merge_sections(summary.sections, data.sections)
    if data.overrides is not None:
        summary.overrides = data.overrides.model_dump(mode="json")
    if data.total_for_customer is not None:
        summary.total_for_customer = data.total_for_customer
        project = await db.get(Project, summary.project_id)
        if project is not None:
            project.summary_total = data.total_for_customer
    summary.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(summary)
    logger.info("SummaryEstimate updated", summary_id=summary.id)
    return summary
