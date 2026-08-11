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

from app.config import settings
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
                candidates_raw = await price_service.find_top_n_materials_combined(name, n=3)
            else:
                candidates_raw = await price_service.find_top_n_works_combined(name, n=3)

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
        # Открыто ли дообучение. Пары собирать можно всегда — они копятся и не
        # пропадают; запускать обучение нельзя, пока модели негде храниться.
        "retraining_enabled": settings.RETRAINING_ENABLED,
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


# ── Перегенерация эмбеддингов прайса ────────────────────────────────────────

async def regenerate_all_price_embeddings(db: AsyncSession) -> None:
    """Перегенерирует эмбеддинги всех позиций прайса после смены модели."""
    from app.models.price import PriceWork, PriceMaterial
    from app.models.price_list import PriceList
    from app.services.embedding_service import normalize_name, generate_embeddings_batch

    for model_cls, pl_type in ((PriceWork, "works"), (PriceMaterial, "materials")):
        rows_res = await db.execute(select(model_cls))
        rows = rows_res.scalars().all()
        if not rows:
            continue

        names = [normalize_name(r.name) for r in rows]
        embeddings = generate_embeddings_batch(names, input_type="search_document")
        for row, emb in zip(rows, embeddings):
            row.embedding = emb

        pl_res = await db.execute(
            select(PriceList)
            .where(PriceList.type == pl_type)
            .order_by(PriceList.updated_at.desc())
            .limit(1)
        )
        price_list = pl_res.scalar_one_or_none()
        if price_list:
            price_list.embedding_status = "ready"

        await db.commit()

    await price_service.load_cache(db)


# ── Фоновое обучение (Фаза 4) ────────────────────────────────────────────────

async def run_training_job(job_id: str, db: AsyncSession) -> None:
    """Фоновая задача дообучения модели эмбеддингов."""
    result = await db.execute(
        select(TrainingJob).where(TrainingJob.id == uuid.UUID(job_id))
    )
    job = result.scalar_one_or_none()
    if not job:
        logger.error("Training job not found", job_id=job_id)
        return

    # Второй рубеж после проверки в роутере: задание могло встать в очередь,
    # когда дообучение было открыто, и дождаться выполнения уже после того, как
    # его закрыли. Обучение пересчитывает эмбеддинги всего прайса моделью,
    # которая не переживёт перезапуск, — после него поиск цен сравнивал бы
    # векторы разных моделей и молча ошибался.
    if not settings.RETRAINING_ENABLED:
        job.status = "failed"
        job.error = (
            "Дообучение закрыто: обученная модель не переживает перезапуск "
            "сервиса, а эмбеддинги прайса пересчитываются под неё."
        )
        job.finished_at = datetime.now(timezone.utc)
        await db.commit()
        logger.warning("Training job rejected: retraining disabled", job_id=job_id)
        return

    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    job.progress_message = "Подготовка данных..."
    job.progress_pct = 5
    await db.commit()

    # shared dict для передачи прогресса из sync-треда без async
    shared: dict = {"pct": 5, "msg": "Подготовка данных..."}

    async def _progress_updater() -> None:
        try:
            while True:
                await asyncio.sleep(5)
                job.progress_pct = shared["pct"]
                job.progress_message = shared["msg"]
                await db.commit()
        except asyncio.CancelledError:
            pass

    try:
        pairs_result = await db.execute(select(TrainingPair))
        all_pairs = pairs_result.scalars().all()
        positives = [p for p in all_pairs if p.is_positive]
        negatives = [p for p in all_pairs if not p.is_positive]

        if len(positives) < 10:
            raise ValueError(f"Слишком мало позитивных пар: {len(positives)} (нужно минимум 10)")

        shared["msg"] = f"Загружено {len(positives)} позитивных, {len(negatives)} негативных пар"
        shared["pct"] = 10
        job.progress_message = shared["msg"]
        job.progress_pct = 10
        await db.commit()

        output_path = "/tmp/smeta-finetuned"

        updater = asyncio.create_task(_progress_updater())
        try:
            await asyncio.to_thread(
                _train_model_sync,
                positives, negatives, output_path, shared,
            )
        finally:
            updater.cancel()
            try:
                await updater
            except asyncio.CancelledError:
                pass

        job.progress_pct = 90
        job.progress_message = "Перезагрузка модели..."
        await db.commit()

        from app.services.embedding_service import reload_model
        reload_model(output_path, model_type="sentence_transformers")

        job.progress_pct = 93
        job.progress_message = "Перегенерация эмбеддингов прайса..."
        await db.commit()

        await regenerate_all_price_embeddings(db)

        job.status = "completed"
        job.progress_pct = 100
        job.progress_message = "Обучение завершено. Модель и эмбеддинги обновлены."
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


def _train_model_sync(positives: list, negatives: list, output_path: str, shared: dict) -> None:
    """Синхронная часть дообучения (запускается в thread через asyncio.to_thread).

    Обновляет shared["pct"]/shared["msg"] — async progress_updater читает их каждые 5 сек.
    """
    import random
    from sentence_transformers import SentenceTransformer, InputExample, losses  # noqa: PLC0415
    from torch.utils.data import DataLoader  # noqa: PLC0415

    from app.services.embedding_service import EMBEDDING_MODEL

    log = logging.getLogger(__name__)

    shared["pct"] = 15
    shared["msg"] = "Формирование обучающих пар..."

    neg_pool = list(negatives)
    examples: list = []

    if neg_pool:
        random.shuffle(neg_pool)
        for i, pos in enumerate(positives):
            neg = neg_pool[i % len(neg_pool)]
            examples.append(InputExample(
                texts=[pos.anchor_text, pos.candidate_text, neg.candidate_text]
            ))
    else:
        # Нет негативных пар — обучаем на косинусном сходстве
        for pos in positives:
            examples.append(InputExample(
                texts=[pos.anchor_text, pos.candidate_text],
                label=1.0,
            ))

    if not examples:
        raise ValueError("Нет обучающих примеров для дообучения")

    num_epochs = 3
    batch_size = min(16, len(examples))
    warmup_steps = min(50, max(1, len(examples) // 4))

    shared["pct"] = 20
    shared["msg"] = f"Загрузка базовой модели ({len(examples)} примеров)..."
    log.info("Loading base model for training, examples=%d", len(examples))

    model = SentenceTransformer(EMBEDDING_MODEL)

    shared["pct"] = 30
    shared["msg"] = "Модель загружена. Начинаю дообучение..."

    dataloader = DataLoader(examples, shuffle=True, batch_size=batch_size)
    loss_fn = (
        losses.TripletLoss(model=model) if neg_pool
        else losses.CosineSimilarityLoss(model=model)
    )

    def _epoch_callback(score: float, epoch: int, steps: int) -> None:
        pct = 30 + int((epoch / num_epochs) * 55)  # 30% → 85%
        shared["pct"] = pct
        shared["msg"] = f"Эпоха {epoch}/{num_epochs} завершена"
        log.info("Training epoch %d/%d done", epoch, num_epochs)

    model.fit(
        train_objectives=[(dataloader, loss_fn)],
        epochs=num_epochs,
        warmup_steps=warmup_steps,
        output_path=output_path,
        show_progress_bar=False,
        callback=_epoch_callback,
    )
    # Явное сохранение — страховка на случай если fit не записал
    model.save(output_path)

    shared["pct"] = 88
    shared["msg"] = "Обучение завершено. Сохраняем модель..."
    log.info("Training complete, model saved to %s", output_path)
