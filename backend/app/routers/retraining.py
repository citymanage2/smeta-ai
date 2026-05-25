"""
REST API для сбора обучающих пар и управления дообучением модели эмбеддингов.

Доступен только администратору.
"""
import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services import retraining_service
from app.utils.auth import get_admin_user

router = APIRouter(prefix="/retraining", tags=["retraining"])


# ── Схемы запросов / ответов ─────────────────────────────────────────────────

class SavePairRequest(BaseModel):
    anchor_text: str
    candidate_text: str
    candidate_type: str  # "work" | "material"
    is_positive: bool
    similarity_score: float
    source_file: Optional[str] = None


class PairResponse(BaseModel):
    id: str
    anchor_text: str
    candidate_text: str
    candidate_type: str
    is_positive: bool
    similarity_score: float
    source_file: Optional[str]


class StatsResponse(BaseModel):
    total_pairs: int
    positive_pairs: int
    negative_pairs: int
    last_job_status: Optional[str]
    model_loaded: bool


class TrainResponse(BaseModel):
    job_id: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    progress_pct: int
    progress_message: Optional[str]
    error: Optional[str]
    model_path: Optional[str]


# ── Эндпоинты ────────────────────────────────────────────────────────────────

@router.post("/parse")
async def parse_files(
    files: list[UploadFile] = File(...),
    _admin=Depends(get_admin_user),
):
    """Парсит xlsx-файлы и возвращает список позиций с top-3 кандидатами для оценки."""
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Не переданы файлы")

    for f in files:
        if not f.filename or not f.filename.lower().endswith(".xlsx"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Файл '{f.filename}' не является xlsx",
            )

    items = await retraining_service.parse_files_for_review(files)
    return {"items": items, "total": len(items)}


@router.post("/pairs", response_model=PairResponse)
async def save_pair(
    body: SavePairRequest,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(get_admin_user),
):
    """Сохраняет одну обучающую пару (оценку пользователя)."""
    if body.candidate_type not in ("work", "material"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="candidate_type должен быть 'work' или 'material'",
        )

    pair = await retraining_service.save_training_pair(
        db,
        anchor_text=body.anchor_text,
        candidate_text=body.candidate_text,
        candidate_type=body.candidate_type,
        is_positive=body.is_positive,
        similarity_score=body.similarity_score,
        source_file=body.source_file,
    )
    return PairResponse(
        id=str(pair.id),
        anchor_text=pair.anchor_text,
        candidate_text=pair.candidate_text,
        candidate_type=pair.candidate_type,
        is_positive=pair.is_positive,
        similarity_score=pair.similarity_score,
        source_file=pair.source_file,
    )


@router.get("/stats", response_model=StatsResponse)
async def get_stats(
    db: AsyncSession = Depends(get_db),
    _admin=Depends(get_admin_user),
):
    """Возвращает статистику накопленных пар и статус последнего обучения."""
    stats = await retraining_service.get_stats(db)
    return StatsResponse(**stats)


@router.post("/train", response_model=TrainResponse)
async def start_training(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(get_admin_user),
):
    """Запускает фоновую задачу дообучения модели."""
    stats = await retraining_service.get_stats(db)
    if stats["positive_pairs"] < 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Слишком мало позитивных пар: {stats['positive_pairs']} (нужно минимум 10)",
        )

    job = await retraining_service.create_training_job(db, pairs_count=stats["total_pairs"])
    job_id = str(job.id)

    background_tasks.add_task(
        retraining_service.run_training_job,
        job_id,
        db,
    )

    return TrainResponse(job_id=job_id)


@router.get("/train/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(get_admin_user),
):
    """Возвращает статус и прогресс задачи дообучения."""
    try:
        parsed_id = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный job_id")

    job = await retraining_service.get_training_job(db, parsed_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")

    return JobStatusResponse(
        job_id=str(job.id),
        status=job.status,
        progress_pct=job.progress_pct,
        progress_message=job.progress_message,
        error=job.error,
        model_path=job.model_path,
    )
