"""
migrate_tasks_to_kanban.py — one-shot idempotent migration.

Creates a WorkflowCard for every task that:
  - has a project_id
  - has a known task_type (mapped to a kanban stage)
  - is NOT already referenced by any existing WorkflowCard

Card name = task.name if set, else the human-readable label from TASK_TYPE_LABELS.
Idempotent: safe to run multiple times.

Usage:
  cd backend
  DATABASE_URL=postgresql+asyncpg://... python scripts/migrate_tasks_to_kanban.py
"""
import asyncio
import os
import sys
import uuid

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, or_

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.task import Task
from app.models.workflow_card import WorkflowCard
from app.constants import TASK_TYPE_TO_FIELD, TASK_TYPE_TO_STAGE, TASK_TYPE_LABELS

TASK_TYPE_LABELS_FALLBACK = TASK_TYPE_LABELS


async def migrate(database_url: str) -> None:
    engine = create_async_engine(database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Collect all task IDs already linked to a card
        cards_result = await session.execute(select(WorkflowCard))
        existing_cards = cards_result.scalars().all()
        linked_task_ids: set[str] = set()
        for card in existing_cards:
            for field in ("list_task_id", "completeness_task_id", "estimate_task_id", "optimization_task_id"):
                val = getattr(card, field, None)
                if val:
                    linked_task_ids.add(str(val))

        # Fetch all tasks with project_id and a known task_type
        tasks_result = await session.execute(
            select(Task).where(
                Task.project_id.isnot(None),
                Task.task_type.in_(list(TASK_TYPE_TO_FIELD.keys())),
            )
        )
        tasks = tasks_result.scalars().all()

        created = 0
        skipped = 0
        for task in tasks:
            task_id = str(task.id)
            if task_id in linked_task_ids:
                skipped += 1
                continue

            field_name = TASK_TYPE_TO_FIELD[task.task_type]
            stage = TASK_TYPE_TO_STAGE[task.task_type]
            card_name = task.name if task.name else TASK_TYPE_LABELS_FALLBACK.get(task.task_type, task.task_type)

            card = WorkflowCard(
                id=str(uuid.uuid4()),
                project_id=task.project_id,
                name=card_name,
                stage=stage,
            )
            setattr(card, field_name, task_id)
            session.add(card)
            created += 1

        await session.commit()
        print(f"Done: created {created} cards, skipped {skipped} already-linked tasks.")

    await engine.dispose()


if __name__ == "__main__":
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)
    asyncio.run(migrate(url))
