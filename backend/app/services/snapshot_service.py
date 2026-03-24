"""Snapshot service — saves/restores estimate_items state to task_versions."""
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import structlog

from app.models.estimate_item import EstimateItem
from app.models.task import Task
from app.models.task_version import TaskVersion

logger = structlog.get_logger()


async def _next_version_number(task_id: str, db: AsyncSession) -> int:
    result = await db.execute(
        select(func.max(TaskVersion.version_number)).where(
            TaskVersion.task_id == task_id
        )
    )
    current_max = result.scalar()
    return (current_max or 0) + 1


async def save_snapshot(
    task_id: str,
    db: AsyncSession,
    change_description: str,
    change_type: str,
    created_by: str = "user",
) -> TaskVersion:
    """Snapshot current estimate_items for a task before any modification."""
    items_result = await db.execute(
        select(EstimateItem)
        .where(EstimateItem.task_id == task_id)
        .order_by(EstimateItem.position)
    )
    items = items_result.scalars().all()

    snapshot_items = []
    for item in items:
        snapshot_items.append({
            "id": item.id,
            "position": item.position,
            "type": item.type,
            "name": item.name,
            "unit": item.unit,
            "quantity": item.quantity,
            "work_price": item.work_price,
            "mat_price": item.mat_price,
            "section": item.section,
            "notes": item.notes,
            "is_analogue": item.is_analogue,
            "original_item_id": item.original_item_id,
            "analogue_note": item.analogue_note,
            "extra": item.extra or {},
        })

    version_number = await _next_version_number(task_id, db)
    version = TaskVersion(
        task_id=task_id,
        version_number=version_number,
        snapshot={"items": snapshot_items},
        change_description=change_description,
        change_type=change_type,
        created_by=created_by,
    )
    db.add(version)
    await db.commit()
    await db.refresh(version)
    logger.info("Snapshot saved", task_id=task_id, version=version_number, change_type=change_type)
    return version


async def restore_snapshot(
    task_id: str,
    version_id: str,
    db: AsyncSession,
) -> None:
    """Restore estimate_items from a snapshot, then update estimate_status."""
    version_result = await db.execute(
        select(TaskVersion).where(
            TaskVersion.id == version_id,
            TaskVersion.task_id == task_id,
        )
    )
    version = version_result.scalar_one_or_none()
    if not version:
        raise ValueError(f"Version {version_id} not found for task {task_id}")

    snapshot_items: list[dict] = version.snapshot.get("items", [])

    # Delete all current items for this task
    items_result = await db.execute(
        select(EstimateItem).where(EstimateItem.task_id == task_id)
    )
    for item in items_result.scalars().all():
        await db.delete(item)
    await db.flush()

    # Restore from snapshot (preserve original IDs so FK refs stay valid)
    for idx, s in enumerate(snapshot_items):
        restored = EstimateItem(
            id=s["id"],
            task_id=task_id,
            position=s.get("position", idx),
            type=s["type"],
            name=s["name"],
            unit=s.get("unit"),
            quantity=s.get("quantity"),
            work_price=s.get("work_price"),
            mat_price=s.get("mat_price"),
            section=s.get("section"),
            notes=s.get("notes"),
            is_analogue=s.get("is_analogue", False),
            original_item_id=s.get("original_item_id"),
            analogue_note=s.get("analogue_note"),
            extra=s.get("extra", {}),
        )
        db.add(restored)

    # Update estimate_status based on how old this version is
    task_result = await db.execute(select(Task).where(Task.id == task_id))
    task = task_result.scalar_one_or_none()
    if task:
        task.estimate_status = "calculated"
        task.estimate_status_updated_at = datetime.now(timezone.utc)
        task.estimate_status_updated_by = "auto"

    await db.commit()
    logger.info("Snapshot restored", task_id=task_id, version_id=version_id)


def items_to_snapshot_list(items: list[EstimateItem]) -> list[dict]:
    return [
        {
            "id": item.id,
            "position": item.position,
            "type": item.type,
            "name": item.name,
            "unit": item.unit,
            "quantity": item.quantity,
            "work_price": item.work_price,
            "mat_price": item.mat_price,
            "section": item.section,
            "notes": item.notes,
            "is_analogue": item.is_analogue,
            "original_item_id": item.original_item_id,
            "analogue_note": item.analogue_note,
            "extra": item.extra or {},
        }
        for item in items
    ]
