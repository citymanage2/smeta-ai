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
from fastapi.responses import StreamingResponse
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

def _abc_analysis(rows: list[dict], row_type: str) -> tuple[list[dict], dict]:
    """Compute ABC groups for rows of given type. Mutates rows in-place, returns (rows, breakdown)."""
    import copy as _copy
    rows = _copy.deepcopy(rows)

    def _cost(r: dict) -> float:
        qty = r.get("qty") or 0
        pw = r.get("price_work") or 0
        pm = r.get("price_material") or 0
        return float(qty) * (float(pw) + float(pm))

    typed_indices = [(i, r) for i, r in enumerate(rows) if r.get("type") == row_type]
    total = sum(_cost(r) for _, r in typed_indices)

    if total <= 0 or not typed_indices:
        return rows, {"a_count": 0, "b_count": 0, "c_count": 0,
                      "a_sum": 0.0, "b_sum": 0.0, "c_sum": 0.0, "total_sum": 0.0}

    typed_sorted = sorted(typed_indices, key=lambda x: _cost(x[1]), reverse=True)
    cumulative = 0.0
    for idx, r in typed_sorted:
        cumulative += _cost(r)
        pct = cumulative / total
        if pct <= 0.80:
            rows[idx]["abc_group"] = "A"
        elif pct <= 0.95:
            rows[idx]["abc_group"] = "B"
        else:
            rows[idx]["abc_group"] = "C"

    breakdown = {
        "a_count": sum(1 for i, _ in typed_indices if rows[i].get("abc_group") == "A"),
        "b_count": sum(1 for i, _ in typed_indices if rows[i].get("abc_group") == "B"),
        "c_count": sum(1 for i, _ in typed_indices if rows[i].get("abc_group") == "C"),
        "a_sum": sum(_cost(rows[i]) for i, _ in typed_indices if rows[i].get("abc_group") == "A"),
        "b_sum": sum(_cost(rows[i]) for i, _ in typed_indices if rows[i].get("abc_group") == "B"),
        "c_sum": sum(_cost(rows[i]) for i, _ in typed_indices if rows[i].get("abc_group") == "C"),
        "total_sum": total,
    }
    return rows, breakdown


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

    RESPONSE_FORMAT = (
        "\n\nВерни СТРОГО в формате JSON без markdown-блоков:\n"
        '{"proposals": [{"id": "uuid4", "row_id": "id строки или null для add", '
        '"proposal_type": "add|remove|replace_tech|replace_material", '
        '"description": "краткое: что меняем", "explanation": "обоснование", '
        '"economy_rub": число_или_null, "confidence": "high|medium|low", '
        '"new_value": null_или_{name,price_work,price_material}}]}'
    )

    step_prompts = {
        "completeness": (
            "Ты — опытный инженер-сметчик со знанием ГЭСН-2017/ФСНБ-2022.\n\n"
            "Для каждой работы в смете проверь:\n"
            "1. Все ли нормативно необходимые материалы учтены (по ГЭСН/ФСНБ для данного вида работ).\n"
            "2. Соответствуют ли объёмы материалов расходным нормам ГЭСН, исходя из объёма работы.\n\n"
            "Добавляй в результат только реальные несоответствия. "
            "Если не уверен в коде ГЭСН — не называй его, напиши описание работы.\n"
            "Для каждого предложения: proposal_type='add', row_id=null (новая строка), "
            "economy_rub=null (это добавление, а не экономия).\n"
        ),
        "redundancy": (
            "Ты — опытный инженер-сметчик со знанием ГЭСН-2017/ФСНБ-2022.\n\n"
            "Найди в смете ЛИШНИЕ позиции по четырём категориям:\n\n"
            "1. ДУБЛИРОВАНИЕ — одна и та же работа/материал указаны дважды с одним назначением.\n"
            "   Важно: материал для разных работ — НЕ дубль. Дубль — только если совпадают и материал/работа, И назначение.\n\n"
            "2. НОРМАТИВНОЕ ВКЛЮЧЕНИЕ — позиция входит в состав другой расценки по ГЭСН (double-counting).\n"
            "   Пример: «Очистка поверхности» входит в расценку грунтования (ГЭСН 15-04).\n\n"
            "3. ВНЕ ПРОЕКТА — позиция явно не применима к данному типу работ/объекту.\n\n"
            "4. Правило точности: не добавляй позиции, в которых не уверен.\n\n"
            "Для каждого предложения: proposal_type='remove', row_id=id строки, economy_rub=стоимость позиции.\n"
        ),
        "technology": (
            "Ты — опытный инженер-сметчик со знанием ГЭСН-2017/ФСНБ-2022.\n\n"
            "Тебе переданы позиции ГРУППЫ А из сметы — наиболее дорогостоящие виды работ (около 80% суммы).\n\n"
            "Для каждой позиции найди возможности снизить НАШУ СЕБЕСТОИМОСТЬ при том же конечном результате.\n\n"
            "Два направления:\n"
            "1. Технологическая замена — та же работа, но производительнее/механизированнее.\n"
            "   Примеры: Ручная штукатурка → Механизированная (от 900 м²), Мокрая стяжка → Полусухая (от 300 м²)\n"
            "2. Оптимизация операций — меньше вспомогательных операций за счёт технологической синергии.\n\n"
            "Для каждого предложения проверь 5 критериев перед тем как предлагать:\n"
            "  1. Конечный результат для заказчика не изменится\n"
            "  2. Расценка есть в ФСНБ/ГЭСН\n"
            "  3. Экономия > 5% от стоимости позиции\n"
            "  4. Технология реализуема\n"
            "  5. Учти все доп. затраты (аренда оборудования)\n"
            "Если не уверен в коде ГЭСН — не называй его, напиши описание.\n\n"
            "proposal_type='replace_tech', new_value={name,price_work} если известно.\n"
        ),
        "materials": (
            "Ты — опытный инженер-сметчик и снабженец.\n\n"
            "Тебе переданы материальные позиции ГРУППЫ А — наиболее дорогостоящие материалы (около 80% суммы).\n\n"
            "Найди возможности снизить стоимость материалов при том же конечном результате.\n\n"
            "Два направления:\n"
            "1. Замена материала — другой материал с теми же характеристиками и функцией.\n"
            "   Примеры: Knauf Rotband → Волма Слой (ГОСТ Р 57957), Импортная арматура → Отечественная А500\n"
            "2. Закупочная оптимизация — тот же материал, но дешевле за счёт условий закупки.\n"
            "   (укажи в explanation, proposal_type='replace_material', economy_rub=null)\n\n"
            "Для каждого предложения по замене проверь:\n"
            "  1. Функциональный результат не изменится\n"
            "  2. Соответствует ГОСТ/ТУ/СП\n"
            "  3. Экономия > 5%\n"
            "  4. Материал реально доступен\n\n"
            "proposal_type='replace_material', new_value={name,price_material} если известно.\n"
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

            source_rows = source_version.rows or []
            abc_breakdown: dict | None = None
            rows_for_claude = source_rows

            # ABC analysis for steps 3 and 4
            if step == "technology":
                updated_rows, abc_breakdown = _abc_analysis(source_rows, "work")
                source_rows = updated_rows  # rows with abc_group populated
                rows_for_claude = [r for r in updated_rows if r.get("abc_group") == "A"]
                task.progress_message = f"ABC-анализ: группа А — {abc_breakdown['a_count']} работ"
                task.progress_data = {"opt_step": step, "abc_breakdown": abc_breakdown, "chunks_done": 0, "chunks_total": 1}
                await db.commit()

            elif step == "materials":
                updated_rows, abc_breakdown = _abc_analysis(source_rows, "material")
                source_rows = updated_rows
                rows_for_claude = [r for r in updated_rows if r.get("abc_group") == "A"]
                task.progress_message = f"ABC-анализ: группа А — {abc_breakdown['a_count']} материалов"
                task.progress_data = {"opt_step": step, "abc_breakdown": abc_breakdown, "chunks_done": 0, "chunks_total": 1}
                await db.commit()

            rows_json = _json.dumps(rows_for_claude, ensure_ascii=False)
            prompt = step_prompts[step] + "\nСтроки сметы (JSON):\n" + rows_json + RESPONSE_FORMAT

            # Update progress: running
            task.progress_message = f"Анализ '{step}' выполняется..."
            task.progress_data = {
                "opt_step": step,
                "chunks_done": 0,
                "chunks_total": 1,
                **({"abc_breakdown": abc_breakdown} if abc_breakdown else {}),
            }
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
                rows=source_rows,  # rows with abc_group filled for steps 3/4
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
                **({"abc_breakdown": abc_breakdown} if abc_breakdown else {}),
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
# Export endpoints
# ---------------------------------------------------------------------------

@router.get("/{task_id}/estimate/versions/{version_id}/export")
async def export_version(
    task_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Download a single EstimateVersion as xlsx."""
    import io as _io
    from app.services.excel_service import generate_estimate_export

    version = await _get_version_or_404(task_id, version_id, db)

    xlsx_bytes = generate_estimate_export(
        rows=version.rows or [],
        overhead_pct=float(version.overhead_pct or 0),
        transport_pct=float(version.transport_pct or 0),
        contingency_pct=float(version.contingency_pct or 0),
        version_display_name=version.version_display_name,
    )

    safe_name = version.version_display_name.replace(" ", "_").replace("/", "-")
    filename = f"smeta_{safe_name}.xlsx"

    return StreamingResponse(
        _io.BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class ComparisonExportBody(BaseModel):
    version_ids: list[str]


@router.post("/{task_id}/estimate/comparison/export")
async def export_comparison(
    task_id: str,
    body: ComparisonExportBody,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Download a multi-version comparison as xlsx."""
    import io as _io
    from app.services.excel_service import generate_comparison_export

    await _get_task_or_404(task_id, db)

    result = await db.execute(
        select(EstimateVersion).where(
            EstimateVersion.task_id == task_id,
            EstimateVersion.id.in_(body.version_ids),
        )
    )
    versions_map = {str(v.id): v for v in result.scalars().all()}

    versions_data = []
    for vid in body.version_ids:
        v = versions_map.get(vid)
        if v:
            versions_data.append({
                "id": str(v.id),
                "version_display_name": v.version_display_name,
                "rows": v.rows or [],
                "overhead_pct": float(v.overhead_pct or 0),
                "transport_pct": float(v.transport_pct or 0),
                "contingency_pct": float(v.contingency_pct or 0),
            })

    if not versions_data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Версии не найдены")

    xlsx_bytes = generate_comparison_export(versions_data)

    return StreamingResponse(
        _io.BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="sravnenie_smety.xlsx"'},
    )


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
