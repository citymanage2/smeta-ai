"""
Сервис для сбора обучающих пар и дообучения модели эмбеддингов.

Фаза 2: parse_files_for_review, CRUD для training_pairs/jobs.
Фаза 4: run_training_job (lazy import sentence-transformers).
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.training_job import TrainingJob
from app.models.training_pair import TrainingPair
from app.services import price_service
from app.services.estimate_parser import parse_estimate_excel

logger = structlog.get_logger()


# ── Типы ────────────────────────────────────────────────────────────────────

class CandidateItem:
    def __init__(self, text: str, score: float, candidate_type: str,
                 unit: Optional[str] = None, min_price: Optional[float] = None):
        self.text = text
        self.score = score
        self.type = candidate_type
        self.unit = unit
        self.min_price = min_price

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "score": self.score,
            "type": self.type,
            "unit": self.unit,
            "min_price": self.min_price,
        }


class ReviewItem:
    def __init__(self, anchor: str, candidates: list[CandidateItem],
                 source_file: Optional[str] = None):
        self.anchor = anchor
        self.candidates = candidates
        self.source_file = source_file

    def to_dict(self) -> dict:
        return {
            "anchor": self.anchor,
            "candidates": [c.to_dict() for c in self.candidates],
            "source_file": self.source_file,
        }


# ── Парсинг файлов ───────────────────────────────────────────────────────────

async def parse_files_for_review(files: list[UploadFile]) -> list[dict]:
    """Парсит xlsx-файлы и для каждой позиции находит top-3 кандидата из прайса."""
    all_items: list[dict] = []

    for file in files:
        content = await file.read()
        rows = parse_estimate_excel(content)

        for row in rows:
            row_type = row.get("type", "work")
            if row_type == "section":
                continue
            name = row.get("name", "").strip()
            if not name:
                continue

            if row_type == "material":
                candidates_raw = await price_service.find_top_n_materials(name, n=3)
            else:
                candidates_raw = await price_service.find_top_n_works(name, n=3)

            if not candidates_raw:
                continue

            candidates = [CandidateItem(**c) for c in candidates_raw]
            item = ReviewItem(
                anchor=name,
                candidates=candidates,
                source_file=file.filename,
            )
            all_items.append(item.to_dict())

    return all_items


# ── CRUD training_pairs ──────────────────────────────────────────────────────

async def save_training_pair(
    db: AsyncSession,
    anchor_text: str,
    candidate_text: str,
    candidate_type: str,
    is_positive: bool,
    similarity_score: float,
    source_file: Optional[str] = None,
) -> TrainingPair:
    pair = TrainingPair(
        anchor_text=anchor_text,
        candidate_text=candidate_text,
        candidate_type=candidate_type,
        is_positive=is_positive,
        similarity_score=similarity_score,
        source_file=source_file,
    )
    db.add(pair)
    await db.commit()
    await db.refresh(pair)
    return pair


async def get_stats(db: AsyncSession) -> dict:
    total_result = await db.execute(select(func.count()).select_from(TrainingPair))
    total = total_result.scalar() or 0

    positive_result = await db.execute(
        select(func.count()).select_from(TrainingPair).where(TrainingPair.is_positive.is_(True))
    )
    positive = positive_result.scalar() or 0

    negative = total - positive

    last_job_status: Optional[str] = None
    last_job_result = await db.execute(
        select(TrainingJob).order_by(TrainingJob.created_at.desc()).limit(1)
    )
    last_job = last_job_result.scalar_one_or_none()
    if last_job:
        last_job_status = last_job.status

    from app.services.embedding_service import _current_model_path
    model_loaded = _current_model_path is not None

    return {
        "total_pairs": total,
        "positive_pairs": positive,
        "negative_pairs": negative,
        "last_job_status": last_job_status,
        "model_loaded": model_loaded,
    }


# ── CRUD training_jobs ───────────────────────────────────────────────────────

async def create_training_job(db: AsyncSession, pairs_count: int) -> TrainingJob:
    job = TrainingJob(pairs_count=pairs_count)
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def get_training_job(db: AsyncSession, job_id: uuid.UUID) -> Optional[TrainingJob]:
    result = await db.execute(select(TrainingJob).where(TrainingJob.id == job_id))
    return result.scalar_one_or_none()


async def update_job_progress(
    db: AsyncSession,
    job: TrainingJob,
    status: Optional[str] = None,
    progress_pct: Optional[int] = None,
    progress_message: Optional[str] = None,
    model_path: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    if status is not None:
        job.status = status
    if progress_pct is not None:
        job.progress_pct = progress_pct
    if progress_message is not None:
        job.progress_message = progress_message
    if model_path is not None:
        job.model_path = model_path
    if error is not None:
        job.error = error
    await db.commit()


# ── Фоновое обучение (Фаза 4) ────────────────────────────────────────────────

async def run_training_job(job_id: str, db: AsyncSession) -> None:
    """Фоновая задача дообучения (реализуется в Фазе 4)."""
    result = await db.execute(
        select(TrainingJob).where(TrainingJob.id == uuid.UUID(job_id))
    )
    job = result.scalar_one_or_none()
    if not job:
        logger.error("Training job not found", job_id=job_id)
        return

    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    job.progress_message = "Подготовка данных..."
    await db.commit()

    try:
        pairs_result = await db.execute(select(TrainingPair))
        all_pairs = pairs_result.scalars().all()
        positives = [p for p in all_pairs if p.is_positive]
        negatives = [p for p in all_pairs if not p.is_positive]

        if len(positives) < 10:
            raise ValueError(f"Слишком мало позитивных пар: {len(positives)} (нужно минимум 10)")

        job.progress_message = f"Загружено {len(positives)} позитивных и {len(negatives)} негативных пар"
        job.progress_pct = 10
        await db.commit()

        output_path = "/tmp/smeta-finetuned"

        await asyncio.to_thread(
            _train_model_sync,
            positives, negatives, output_path,
            job_id, db,
        )

        from app.services.embedding_service import reload_model
        reload_model(output_path)

        job.status = "completed"
        job.progress_pct = 100
        job.progress_message = "Обучение завершено. Модель загружена."
        job.model_path = output_path
        job.finished_at = datetime.now(timezone.utc)
        await db.commit()
        logger.info("Training job completed", job_id=job_id)

    except Exception as e:
        logger.error("Training job failed", job_id=job_id, error=str(e))
        job.status = "failed"
        job.error = str(e)
        job.finished_at = datetime.now(timezone.utc)
        await db.commit()


def _train_model_sync(positives, negatives, output_path: str, job_id: str, db) -> None:
    """Синхронная часть обучения (запускается в thread). Реализуется в Фазе 4."""
    # Заглушка: Фаза 4 заполнит эту функцию полной логикой sentence-transformers
    import time
    logging.getLogger(__name__).info("Training placeholder — implement in Phase 4")
    time.sleep(1)
