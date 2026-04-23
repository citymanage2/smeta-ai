"""REST API for EstimateVersion — online editor + optimization pipeline."""
import uuid
from decimal import Decimal
from typing import Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, AsyncSessionLocal
from app.models.estimate_version import EstimateVersion
from app.models.task import Task
from app.schemas.estimate_version import (
    EstimateRowSchema,
    EstimateVersionResponse,
    EstimateVersionSummary,
    OptimizationProposalSchema,
)
from app.utils.auth import get_current_user

logger = structlog.get_logger()

router = APIRouter(prefix="/tasks", tags=["estimate"])

VALID_LABELS = frozenset({
    "original",
    "client",
    "completeness_checked",
    "no_redundant",
    "tech_optimized",
    "material_optimized",
    "custom",
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_task_or_404(task_id: str, db: AsyncSession) -> Task:
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    return task


async def _get_version_or_404(task_id: str, version_id: str, db: AsyncSession) -> EstimateVersion:
    result = await db.execute(
        select(EstimateVersion).where(
            EstimateVersion.id == version_id,
            EstimateVersion.task_id == task_id,
        )
    )
    version = result.scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Версия сметы не найдена")
    return version


def _version_to_summary(v: EstimateVersion) -> EstimateVersionSummary:
    return EstimateVersionSummary(
        id=str(v.id),
        task_id=str(v.task_id),
        version_number=v.version_number,
        version_label=v.version_label,
        version_display_name=v.version_display_name,
        overhead_pct=v.overhead_pct,
        transport_pct=v.transport_pct,
        contingency_pct=v.contingency_pct,
        expenses_overridden=v.expenses_overridden,
        is_rolled_back=v.is_rolled_back,
        created_at=v.created_at.isoformat(),
    )


def _version_to_response(v: EstimateVersion) -> EstimateVersionResponse:
    rows = [EstimateRowSchema(**r) for r in (v.rows or [])]
    proposals = None
    if v.optimization_proposals:
        proposals = [OptimizationProposalSchema(**p) for p in v.optimization_proposals]
    return EstimateVersionResponse(
        id=str(v.id),
        task_id=str(v.task_id),
        version_number=v.version_number,
        version_label=v.version_label,
        version_display_name=v.version_display_name,
        rows=rows,
        overhead_pct=v.overhead_pct,
        transport_pct=v.transport_pct,
        contingency_pct=v.contingency_pct,
        expenses_overridden=v.expenses_overridden,
        optimization_proposals=proposals,
        is_rolled_back=v.is_rolled_back,
        created_at=v.created_at.isoformat(),
    )


def _next_version_number(versions: list[EstimateVersion]) -> int:
    return max((v.version_number for v in versions), default=-1) + 1


# ---------------------------------------------------------------------------
# GET /tasks/{task_id}/estimate/versions
# ---------------------------------------------------------------------------

@router.get("/{task_id}/estimate/versions", response_model=list[EstimateVersionSummary])
async def list_versions(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Return all non-rolled-back versions for a task (without rows for speed)."""
    await _get_task_or_404(task_id, db)
    result = await db.execute(
        select(EstimateVersion)
        .where(EstimateVersion.task_id == task_id, EstimateVersion.is_rolled_back == False)  # noqa: E712
        .order_by(EstimateVersion.version_number)
    )
    versions = result.scalars().all()
    return [_version_to_summary(v) for v in versions]


# ---------------------------------------------------------------------------
# GET /tasks/{task_id}/estimate/versions/{version_id}
# ---------------------------------------------------------------------------

@router.get("/{task_id}/estimate/versions/{version_id}", response_model=EstimateVersionResponse)
async def get_version(
    task_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Return a full version including rows."""
    version = await _get_version_or_404(task_id, version_id, db)
    return _version_to_response(version)


# ---------------------------------------------------------------------------
# PUT /tasks/{task_id}/estimate/versions/{version_id}/rows
# ---------------------------------------------------------------------------

class SaveRowsRequest(BaseModel):
    rows: list[dict]


@router.put("/{task_id}/estimate/versions/{version_id}/rows")
async def save_rows(
    task_id: str,
    version_id: str,
    body: SaveRowsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Persist edited rows for a version."""
    version = await _get_version_or_404(task_id, version_id, db)
    version.rows = body.rows
    await db.commit()
    return {"version_id": version_id, "rows_count": len(body.rows)}


# ---------------------------------------------------------------------------
# PUT /tasks/{task_id}/estimate/versions/{version_id}/expenses
# ---------------------------------------------------------------------------

class SaveExpensesRequest(BaseModel):
    overhead_pct: Decimal
    transport_pct: Decimal
    contingency_pct: Decimal


@router.put("/{task_id}/estimate/versions/{version_id}/expenses")
async def save_expenses(
    task_id: str,
    version_id: str,
    body: SaveExpensesRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Save additional expense percentages for a specific version."""
    version = await _get_version_or_404(task_id, version_id, db)
    version.overhead_pct = body.overhead_pct
    version.transport_pct = body.transport_pct
    version.contingency_pct = body.contingency_pct
    version.expenses_overridden = True
    await db.commit()
    return {"version_id": version_id, "expenses_overridden": True}


# ---------------------------------------------------------------------------
# Background optimization runner (shared by steps 1–4)
# ---------------------------------------------------------------------------

async def _run_optimization_step(
    task_id: str,
    step: str,  # "completeness" | "redundancy" | "technology" | "materials"
) -> None:
    """Background task: run an AI optimization step and create a new EstimateVersion."""
    from app.services.claude_service import call_claude
    from app.utils.json_utils import extract_json
    import json as _json

    step_labels = {
        "completeness": ("completeness_checked", "Оптимизация 1 — Полнота"),
        "redundancy": ("no_redundant", "Оптимизация 2 — Лишние позиции"),
        "technology": ("tech_optimized", "Оптимизация 3 — Технологии"),
        "materials": ("material_optimized", "Оптимизация 4 — Материалы"),
    }
    next_label, display_name = step_labels[step]

    step_prompts = {
        "completeness": (
            "Ты — эксперт по строительному сметному делу (ГЭСН/ФСНБ-2022, ФЕР/ТЕР, Свердловская обл.).\n\n"
            "Задача: проверить полноту сметы. Найди позиции, которые, вероятно, отсутствуют по нормативам ГЭСН.\n\n"
            "Для каждого предложения:\n"
            "- proposal_type: 'add'\n"
            "- description: что добавить\n"
            "- explanation: почему это нужно по нормативам\n"
            "- economy_rub: null (это добавление, а не экономия)\n"
            "- confidence: high/medium/low\n"
            "- Если не уверен в коде ГЭСН — не называй его, напиши описание работы\n\n"
        ),
        "redundancy": (
            "Ты — эксперт по строительному сметному делу.\n\n"
            "Задача: найти позиции, которые, вероятно, лишние или дублируются.\n\n"
            "Для каждого предложения:\n"
            "- proposal_type: 'remove'\n"
            "- row_id: id строки для удаления\n"
            "- description: что удалить\n"
            "- explanation: почему позиция лишняя (дублирование, несоответствие объёму и т.п.)\n"
            "- economy_rub: предполагаемая экономия в рублях\n"
            "- confidence: high/medium/low\n"
            "- Оцени уверенность своего предложения: high/medium/low\n\n"
        ),
        "technology": (
            "Ты — эксперт по строительным технологиям.\n\n"
            "Задача: найти позиции, где можно заменить технологию на более дешёвую без потери качества.\n\n"
            "Для каждого предложения:\n"
            "- proposal_type: 'replace_tech'\n"
            "- row_id: id строки для замены\n"
            "- description: текущая технология → предлагаемая замена\n"
            "- explanation: почему замена безопасна и даёт экономию\n"
            "- economy_rub: предполагаемая экономия в рублях\n"
            "- confidence: high/medium/low\n"
            "- new_value: {\"name\": \"новое название\", \"price_work\": новая_цена} (если известно)\n"
            "- Если не уверен в коде ГЭСН — не называй его, напиши описание работы\n\n"
        ),
        "materials": (
            "Ты — эксперт по строительным материалам и закупкам.\n\n"
            "Задача: найти позиции, где можно заменить материал на более дешёвый аналог.\n\n"
            "Для каждого предложения:\n"
            "- proposal_type: 'replace_material'\n"
            "- row_id: id строки для замены\n"
            "- description: текущий материал → предлагаемый аналог\n"
            "- explanation: почему аналог приемлем (характеристики, ГОСТ)\n"
            "- economy_rub: предполагаемая экономия в рублях\n"
            "- confidence: high/medium/low\n"
            "- new_value: {\"name\": \"новое название\", \"price_material\": новая_цена} (если известно)\n\n"
        ),
    }

    async with AsyncSessionLocal() as db:
        try:
            task = await db.get(Task, task_id)
            if not task:
                return

            # Find latest non-rolled-back version as input
            result = await db.execute(
                select(EstimateVersion)
                .where(
                    EstimateVersion.task_id == task_id,
                    EstimateVersion.is_rolled_back == False,  # noqa: E712
                )
                .order_by(EstimateVersion.version_number.desc())
            )
            source_version = result.scalars().first()
            if source_version is None:
                task.progress_data = {"opt_step": step, "status": "error", "error": "Нет версий сметы"}
                await db.commit()
                return

            rows_json = _json.dumps(source_version.rows or [], ensure_ascii=False)
            prompt = (
                step_prompts[step]
                + "Строки сметы (JSON):\n"
                + rows_json
                + "\n\nВерни СТРОГО в формате JSON без markdown:\n"
                '{"proposals": [{"id": "uuid", "row_id": "...", "proposal_type": "...", '
                '"description": "...", "explanation": "...", "economy_rub": число_или_null, '
                '"confidence": "high|medium|low", "new_value": null_или_объект}]}'
            )

            # Update progress: running
            task.progress_message = f"Анализ: шаг '{step}' выполняется..."
            task.progress_data = {"opt_step": step, "chunks_done": 0, "chunks_total": 1}
            await db.commit()

            response_text = await call_claude(
                messages=[{"role": "user", "content": prompt}],
                use_web_search=False,
                processing_timeout=180.0,
            )

            data = extract_json(response_text)
            proposals_raw = data.get("proposals", [])

            # Assign ids where missing
            for p in proposals_raw:
                if not p.get("id"):
                    p["id"] = str(uuid.uuid4())

            # Count versions to get next number
            count_result = await db.execute(
                select(EstimateVersion).where(EstimateVersion.task_id == task_id)
            )
            all_versions = count_result.scalars().all()
            next_num = _next_version_number(all_versions)

            new_version = EstimateVersion(
                id=str(uuid.uuid4()),
                task_id=task_id,
                version_number=next_num,
                version_label=next_label,
                version_display_name=display_name,
                rows=source_version.rows or [],
                overhead_pct=source_version.overhead_pct,
                transport_pct=source_version.transport_pct,
                contingency_pct=source_version.contingency_pct,
                expenses_overridden=source_version.expenses_overridden,
                optimization_proposals=proposals_raw,
            )
            db.add(new_version)

            task.progress_message = None
            task.progress_data = {
                "opt_step": step,
                "status": "done",
                "proposals": proposals_raw,
                "new_version_id": str(new_version.id),
            }
            await db.commit()
            logger.info("Optimization step done", task_id=task_id, step=step, proposals=len(proposals_raw))

        except Exception as e:
            logger.error("Optimization step failed", task_id=task_id, step=step, error=str(e))
            try:
                task = await db.get(Task, task_id)
                if task:
                    task.progress_message = None
                    task.progress_data = {"opt_step": step, "status": "error", "error": str(e)}
                    await db.commit()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# POST optimize/completeness | redundancy | technology | materials
# ---------------------------------------------------------------------------

def _make_optimize_endpoint(step: str):
    async def optimize(
        task_id: str,
        background_tasks: BackgroundTasks,
        db: AsyncSession = Depends(get_db),
        current_user: dict = Depends(get_current_user),
    ):
        await _get_task_or_404(task_id, db)
        background_tasks.add_task(_run_optimization_step, task_id, step)
        return {"status": "running", "step": step}
    return optimize


router.add_api_route(
    "/{task_id}/estimate/optimize/completeness",
    _make_optimize_endpoint("completeness"),
    methods=["POST"],
    summary="Шаг 1 — Проверка полноты",
)
router.add_api_route(
    "/{task_id}/estimate/optimize/redundancy",
    _make_optimize_endpoint("redundancy"),
    methods=["POST"],
    summary="Шаг 2 — Лишние позиции",
)
router.add_api_route(
    "/{task_id}/estimate/optimize/technology",
    _make_optimize_endpoint("technology"),
    methods=["POST"],
    summary="Шаг 3 — Оптимизация технологий",
)
router.add_api_route(
    "/{task_id}/estimate/optimize/materials",
    _make_optimize_endpoint("materials"),
    methods=["POST"],
    summary="Шаг 4 — Оптимизация материалов",
)


# ---------------------------------------------------------------------------
# POST /tasks/{task_id}/estimate/optimize/custom
# ---------------------------------------------------------------------------

class CustomOptimizeRequest(BaseModel):
    version_id: str
    row_ids: list[str]


@router.post("/{task_id}/estimate/optimize/custom")
async def optimize_custom(
    task_id: str,
    body: CustomOptimizeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Synchronous custom optimization for selected rows (few rows, no chunking)."""
    from app.services.claude_service import call_claude
    from app.utils.json_utils import extract_json
    import json as _json

    version = await _get_version_or_404(task_id, body.version_id, db)
    rows = version.rows or []
    selected = [r for r in rows if r.get("id") in body.row_ids]
    if not selected:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Не найдены выбранные строки")

    rows_json = _json.dumps(selected, ensure_ascii=False)
    prompt = (
        "Ты — эксперт по строительным сметам.\n\n"
        "Для каждой выбранной позиции предложи варианты оптимизации по трём направлениям:\n"
        "1. replace_tech — замена технологии на более дешёвую\n"
        "2. replace_material — замена материала на более дешёвый аналог\n"
        "3. price_search — поиск цены у альтернативных поставщиков (укажи источник)\n\n"
        "Оцени уверенность: high/medium/low. "
        "Если не уверен в коде ГЭСН — не называй его, напиши описание работы.\n\n"
        "Выбранные строки:\n" + rows_json + "\n\n"
        "Верни СТРОГО JSON без markdown:\n"
        '{"proposals": [{"id": "uuid", "row_id": "...", "proposal_type": "replace_tech|replace_material|price_search", '
        '"description": "...", "explanation": "...", "economy_rub": число_или_null, '
        '"confidence": "high|medium|low", "source": null_или_строка, "new_value": null_или_объект}]}'
    )

    try:
        response_text = await call_claude(
            messages=[{"role": "user", "content": prompt}],
            use_web_search=True,
            processing_timeout=120.0,
        )
        data = extract_json(response_text)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Ошибка Claude: {e}")

    proposals = data.get("proposals", [])
    for p in proposals:
        if not p.get("id"):
            p["id"] = str(uuid.uuid4())

    return {"proposals": proposals}


# ---------------------------------------------------------------------------
# POST /tasks/{task_id}/estimate/apply-proposals
# ---------------------------------------------------------------------------

class ApplyProposalsRequest(BaseModel):
    version_id: str
    accepted_proposal_ids: list[str]
    version_display_name: Optional[str] = None


@router.post("/{task_id}/estimate/apply-proposals", response_model=EstimateVersionResponse)
async def apply_proposals(
    task_id: str,
    body: ApplyProposalsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Apply accepted proposals to a version and return a new version."""
    import copy as _copy

    version = await _get_version_or_404(task_id, body.version_id, db)
    proposals = version.optimization_proposals or []

    accepted = {p["id"]: p for p in proposals if p.get("id") in body.accepted_proposal_ids}
    if not accepted:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нет принятых предложений")

    rows = _copy.deepcopy(version.rows or [])
    rows_by_id = {r["id"]: r for r in rows}

    for proposal in accepted.values():
        ptype = proposal.get("proposal_type")
        row_id = proposal.get("row_id")

        if ptype == "remove":
            rows = [r for r in rows if r.get("id") != row_id]
            rows_by_id = {r["id"]: r for r in rows}

        elif ptype in ("replace_tech", "replace_material"):
            target = rows_by_id.get(row_id)
            if target and proposal.get("new_value"):
                target.update(proposal["new_value"])
                target["optimization_note"] = proposal.get("description", "")

        elif ptype == "add" and proposal.get("new_value"):
            new_row_id = str(uuid.uuid4())
            new_row = {
                "id": new_row_id,
                "lineage_id": new_row_id,
                "num": len(rows) + 1,
                "type": "work",
                "name": proposal.get("description", "Новая позиция"),
                "unit": "",
                "qty": None,
                "price_work": None,
                "price_material": None,
                "cost": None,
                "selected": False,
                "abc_group": None,
                "optimization_note": proposal.get("description", ""),
            }
            new_row.update(proposal["new_value"])
            new_row["id"] = new_row_id
            new_row["lineage_id"] = new_row_id
            rows.append(new_row)
            rows_by_id[new_row_id] = new_row

    # Get all versions for next version number
    count_result = await db.execute(
        select(EstimateVersion).where(EstimateVersion.task_id == task_id)
    )
    all_versions = count_result.scalars().all()
    next_num = _next_version_number(all_versions)

    display_name = body.version_display_name or f"Ручная правка {next_num}"

    new_version = EstimateVersion(
        id=str(uuid.uuid4()),
        task_id=task_id,
        version_number=next_num,
        version_label="custom",
        version_display_name=display_name,
        rows=rows,
        overhead_pct=version.overhead_pct,
        transport_pct=version.transport_pct,
        contingency_pct=version.contingency_pct,
        expenses_overridden=version.expenses_overridden,
    )
    db.add(new_version)
    await db.commit()
    await db.refresh(new_version)

    return _version_to_response(new_version)


# ---------------------------------------------------------------------------
# POST /tasks/{task_id}/estimate/versions/{version_id}/rollback
# ---------------------------------------------------------------------------

@router.post("/{task_id}/estimate/versions/{version_id}/rollback")
async def rollback_version(
    task_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Mark all versions after this one as is_rolled_back=True."""
    version = await _get_version_or_404(task_id, version_id, db)

    result = await db.execute(
        select(EstimateVersion).where(
            EstimateVersion.task_id == task_id,
            EstimateVersion.version_number > version.version_number,
        )
    )
    later_versions = result.scalars().all()
    for v in later_versions:
        v.is_rolled_back = True

    await db.commit()
    return {"rolled_back_count": len(later_versions), "active_version_id": version_id}


# ---------------------------------------------------------------------------
# PATCH /tasks/{task_id}/estimate/versions/{version_id}  — rename
# ---------------------------------------------------------------------------

class RenameVersionRequest(BaseModel):
    version_display_name: str


@router.patch("/{task_id}/estimate/versions/{version_id}")
async def rename_version(
    task_id: str,
    version_id: str,
    body: RenameVersionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Rename a version's display name."""
    version = await _get_version_or_404(task_id, version_id, db)
    version.version_display_name = body.version_display_name.strip()
    await db.commit()
    return {"version_id": version_id, "version_display_name": version.version_display_name}


# ---------------------------------------------------------------------------
# POST /tasks/{task_id}/estimate/versions  — manual snapshot ("Зафиксировать")
# ---------------------------------------------------------------------------

class CreateVersionRequest(BaseModel):
    source_version_id: str
    version_display_name: Optional[str] = None


@router.post("/{task_id}/estimate/versions", response_model=EstimateVersionResponse)
async def create_manual_version(
    task_id: str,
    body: CreateVersionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Manually snapshot the current state of a version (Зафиксировать версию)."""
    source = await _get_version_or_404(task_id, body.source_version_id, db)

    count_result = await db.execute(
        select(EstimateVersion).where(EstimateVersion.task_id == task_id)
    )
    all_versions = count_result.scalars().all()
    next_num = _next_version_number(all_versions)

    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%H:%M")
    display_name = body.version_display_name or f"Ручная правка {ts}"

    new_version = EstimateVersion(
        id=str(uuid.uuid4()),
        task_id=task_id,
        version_number=next_num,
        version_label="custom",
        version_display_name=display_name,
        rows=source.rows or [],
        overhead_pct=source.overhead_pct,
        transport_pct=source.transport_pct,
        contingency_pct=source.contingency_pct,
        expenses_overridden=source.expenses_overridden,
    )
    db.add(new_version)
    await db.commit()
    await db.refresh(new_version)

    return _version_to_response(new_version)
