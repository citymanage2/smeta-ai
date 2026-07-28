"""REST API for EstimateVersion — online editor + optimization pipeline."""
import asyncio
import uuid
from decimal import Decimal
from typing import Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import base64
import json as _json_top

from app.database import get_db, AsyncSessionLocal
from app.models.estimate_version import EstimateVersion
from app.models.task import Task
from app.models.task_input_file import TaskInputFile
from app.services import storage_service
from app.utils.file_parser import parse_file as _parse_file
from app.schemas.estimate_version import (
    EstimateVersionResponse,
    EstimateVersionSummary,
    OptimizationProposalSchema,
)
from fastapi.responses import StreamingResponse
from app.utils.auth import get_current_user
from app.utils.permissions import can_access

logger = structlog.get_logger()

router = APIRouter(prefix="/tasks", tags=["estimate"])

VALID_LABELS = frozenset({
    "original",
    "client",
    "completeness_checked",
    "no_redundant",
    "tech_optimized",
    "material_optimized",
    "prices_filled",
    "custom",
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_task_or_404(
    task_id: str, db: AsyncSession, current_user: Optional[dict] = None
) -> Task:
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    if current_user is not None and not can_access(task.owner_id, current_user, task.is_shared):
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
    rows = list(v.rows or [])
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
    file_slot: Optional[str] = Query(default=None, description="Фильтр по file_slot: 'result' или 'input'"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Return all non-rolled-back versions for a task (without rows for speed)."""
    await _get_task_or_404(task_id, db, current_user)
    query = (
        select(EstimateVersion)
        .where(EstimateVersion.task_id == task_id, EstimateVersion.is_rolled_back == False)  # noqa: E712
        .order_by(EstimateVersion.version_number)
    )
    if file_slot is not None:
        query = query.where(EstimateVersion.file_slot == file_slot)
    result = await db.execute(query)
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
    await _get_task_or_404(version.task_id, db, current_user)
    return _version_to_response(version)


# ---------------------------------------------------------------------------
# PUT /tasks/{task_id}/estimate/versions/{version_id}/rows
# ---------------------------------------------------------------------------

class SaveRowsRequest(BaseModel):
    rows: list[dict]


_LIST_COMPLETENESS_TYPES = frozenset({
    "LIST_FROM_GRAND", "LIST_FROM_PROJECT",
    "CHECK_LIST_COMPLETENESS", "CHECK_PROJECT_COMPLETENESS",
})


@router.put("/{task_id}/estimate/versions/{version_id}/rows")
async def save_rows(
    task_id: str,
    version_id: str,
    body: SaveRowsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Persist edited rows for a version. Marks task as manually edited."""
    from datetime import datetime, timezone
    from app.models.result import TaskResult
    from app.models.task_input_file import TaskInputFile
    from app.utils.xlsx_generic import rows_to_xlsx

    version = await _get_version_or_404(task_id, version_id, db)
    version.rows = body.rows
    task = await _get_task_or_404(task_id, db, current_user)
    task.manually_edited_at = datetime.now(timezone.utc)

    # For LIST/COMPLETENESS: regenerate xlsx and persist back to source record
    if version.task_type in _LIST_COMPLETENESS_TYPES:
        xlsx_bytes = rows_to_xlsx(body.rows)

        if version.file_slot == "result":
            res = await db.execute(
                select(TaskResult)
                .where(TaskResult.task_id == task_id, TaskResult.slot == "result")
                .order_by(TaskResult.id.desc())
                .limit(1)
            )
            tr = res.scalar_one_or_none()
            if tr is not None:
                tr.storage_key = await storage_service.store_result_file(
                    task_id, "result", tr.file_name or "result.xlsx", tr.mime_type, xlsx_bytes
                )
                tr.size_bytes = len(xlsx_bytes)

        elif version.file_slot == "input":
            # file_index encoded in version_label as "input_N"
            try:
                file_index = int(version.version_label.split("_")[-1])
            except (ValueError, AttributeError):
                file_index = 0
            res = await db.execute(
                select(TaskInputFile).where(
                    TaskInputFile.task_id == task_id,
                    TaskInputFile.file_index == file_index,
                )
            )
            tif = res.scalar_one_or_none()
            if tif is not None:
                tif.storage_key = await storage_service.store_input_file(
                    task_id, tif.file_index, tif.file_name, tif.mime_type, xlsx_bytes
                )
                tif.size_bytes = len(xlsx_bytes)

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
    from datetime import datetime, timezone
    version = await _get_version_or_404(task_id, version_id, db)
    version.overhead_pct = body.overhead_pct
    version.transport_pct = body.transport_pct
    version.contingency_pct = body.contingency_pct
    version.expenses_overridden = True
    task = await _get_task_or_404(task_id, db, current_user)
    task.manually_edited_at = datetime.now(timezone.utc)
    await db.commit()
    return {"version_id": version_id, "expenses_overridden": True}


# ---------------------------------------------------------------------------
# POST /tasks/{task_id}/estimate/init-from-result
# ---------------------------------------------------------------------------

@router.post("/{task_id}/estimate/init-from-result")
async def init_from_result(
    task_id: str,
    file_slot: str = Query(default="result", description="Слот файла результата: 'result' или 'estimate'"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Idempotent: create V0 EstimateVersion from TaskResult for LIST/COMPLETENESS tasks."""
    from app.models.result import TaskResult
    from app.utils.xlsx_generic import parse_xlsx_to_generic_rows

    task = await _get_task_or_404(task_id, db, current_user)

    existing = await db.execute(
        select(EstimateVersion).where(
            EstimateVersion.task_id == task_id,
            EstimateVersion.file_slot == file_slot,
        ).limit(1)
    )
    if existing.scalar_one_or_none() is not None:
        return {"status": "already_exists"}

    # Look for TaskResult in requested slot, fallback to 'result' if 'estimate' not found
    slots_to_try = [file_slot] if file_slot == "result" else [file_slot, "result"]
    tr = None
    for slot_candidate in slots_to_try:
        res = await db.execute(
            select(TaskResult)
            .where(TaskResult.task_id == task_id, TaskResult.slot == slot_candidate)
            .order_by(TaskResult.id.desc())
            .limit(1)
        )
        tr = res.scalar_one_or_none()
        if tr is not None:
            break

    if tr is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="TaskResult не найден")

    rows = parse_xlsx_to_generic_rows(
        await storage_service.load_bytes(tr.storage_key)
    )
    count_res = await db.execute(select(EstimateVersion).where(EstimateVersion.task_id == task_id))
    all_versions = count_res.scalars().all()
    next_num = _next_version_number(all_versions)

    version = EstimateVersion(
        id=str(uuid.uuid4()),
        task_id=task_id,
        version_number=next_num,
        version_label="original",
        version_display_name="V0 — Оригинал",
        rows=rows,
        file_slot=file_slot,
        task_type=task.task_type,
    )
    db.add(version)
    await db.commit()
    return {"status": "created", "version_id": str(version.id)}


# ---------------------------------------------------------------------------
# POST /tasks/{task_id}/estimate/init-from-input
# ---------------------------------------------------------------------------

@router.post("/{task_id}/estimate/init-from-input")
async def init_from_input(
    task_id: str,
    file_index: int = Query(default=0),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Create EstimateVersion from TaskInputFile[file_index] (file_slot='input'). Idempotent per file_index."""
    from app.models.task_input_file import TaskInputFile
    from app.utils.xlsx_generic import parse_xlsx_to_generic_rows

    task = await _get_task_or_404(task_id, db, current_user)
    label = f"input_{file_index}"

    existing = await db.execute(
        select(EstimateVersion).where(
            EstimateVersion.task_id == task_id,
            EstimateVersion.file_slot == "input",
            EstimateVersion.version_label == label,
        ).limit(1)
    )
    ev = existing.scalar_one_or_none()
    if ev is not None:
        return {"status": "already_exists", "version_id": str(ev.id)}

    res = await db.execute(
        select(TaskInputFile).where(
            TaskInputFile.task_id == task_id,
            TaskInputFile.file_index == file_index,
        )
    )
    tif = res.scalar_one_or_none()
    if tif is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Input-файл с index={file_index} не найден")

    rows = parse_xlsx_to_generic_rows(
        await storage_service.load_bytes(tif.storage_key)
    )
    count_res = await db.execute(select(EstimateVersion).where(EstimateVersion.task_id == task_id))
    all_versions = count_res.scalars().all()
    next_num = _next_version_number(all_versions)

    version = EstimateVersion(
        id=str(uuid.uuid4()),
        task_id=task_id,
        version_number=next_num,
        version_label=label,
        version_display_name=f"V0 — Оригинал (файл {file_index})",
        rows=rows,
        file_slot="input",
        task_type=task.task_type,
    )
    db.add(version)
    await db.commit()
    return {"status": "created", "version_id": str(version.id)}


# ---------------------------------------------------------------------------
# POST /tasks/{task_id}/estimate/init-from-estimate-result
# ---------------------------------------------------------------------------

@router.post("/{task_id}/estimate/init-from-estimate-result")
async def init_from_estimate_result(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Idempotent: create EstimateVersion from ESTIMATE_FROM_LIST task result using estimate parser."""
    from app.models.result import TaskResult
    from app.services.estimate_parser import parse_estimate_excel

    task = await _get_task_or_404(task_id, db, current_user)
    if task.task_type != "ESTIMATE_FROM_LIST":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Endpoint доступен только для задач ESTIMATE_FROM_LIST",
        )

    existing = await db.execute(
        select(EstimateVersion).where(
            EstimateVersion.task_id == task_id,
            EstimateVersion.file_slot == "estimate",
            EstimateVersion.version_label == "original",
        ).limit(1)
    )
    ev = existing.scalar_one_or_none()
    if ev is not None:
        return {"status": "already_exists", "version_id": str(ev.id)}

    res = await db.execute(
        select(TaskResult)
        .where(TaskResult.task_id == task_id, TaskResult.slot.in_(["estimate", "result"]))
        .order_by(TaskResult.id.desc())
        .limit(1)
    )
    tr = res.scalar_one_or_none()
    if tr is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Результат задачи не найден. Дождитесь завершения расчёта сметы.",
        )

    try:
        rows = parse_estimate_excel(
            await storage_service.load_bytes(tr.storage_key)
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Не удалось распарсить Excel-смету: {exc}",
        )

    count_res = await db.execute(select(EstimateVersion).where(EstimateVersion.task_id == task_id))
    all_versions = count_res.scalars().all()
    next_num = _next_version_number(all_versions)

    version = EstimateVersion(
        id=str(uuid.uuid4()),
        task_id=task_id,
        version_number=next_num,
        version_label="original",
        version_display_name="Исходная смета",
        rows=rows,
        file_slot="estimate",
        task_type=task.task_type,
    )
    db.add(version)
    await db.commit()
    logger.info("EstimateVersion init-from-estimate-result", task_id=task_id, version_id=version.id, rows=len(rows))
    return {"status": "created", "version_id": str(version.id)}


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


def _auto_apply_proposals(source_rows: list[dict], proposals: list[dict]) -> list[dict]:
    """Apply all proposals to source_rows in-place. Returns modified rows list."""
    import copy as _copy
    rows = _copy.deepcopy(source_rows)
    rows_by_id = {r["id"]: r for r in rows}

    for p in proposals:
        ptype = p.get("proposal_type")
        row_id = p.get("row_id")
        confidence = p.get("confidence", "low")
        description = p.get("description", "")

        if ptype == "remove" and row_id:
            target = rows_by_id.get(row_id)
            if target:
                target["is_excluded"] = True
                target["optimization_note"] = p.get("explanation") or p.get("description") or ""

        elif ptype in ("replace_tech", "replace_material") and row_id:
            target = rows_by_id.get(row_id)
            if target and p.get("new_value"):
                nv = p["new_value"]
                if nv.get("name"):
                    target["name"] = nv["name"]
                if ptype == "replace_tech" and nv.get("price_work") is not None:
                    target["price_work"] = nv["price_work"]
                elif ptype == "replace_material" and nv.get("price_material") is not None:
                    target["price_material"] = nv["price_material"]
                target["optimization_note"] = description
                target["optimization_confidence"] = confidence

        elif ptype == "add":
            nv = p.get("new_value") or {}
            new_id = str(uuid.uuid4())
            new_row: dict = {
                "id": new_id,
                "lineage_id": new_id,
                "num": len(rows) + 1,
                "type": nv.get("type", "material"),
                "name": nv.get("name") or description or "Новая позиция",
                "unit": nv.get("unit", ""),
                "qty": nv.get("qty"),
                "price_work": None,
                "price_material": None,
                "cost": None,
                "selected": False,
                "abc_group": None,
                "optimization_note": description,
                "optimization_confidence": confidence,
            }
            after_row_id = p.get("after_row_id")
            if after_row_id and after_row_id in rows_by_id:
                insert_idx = next((i for i, r in enumerate(rows) if r["id"] == after_row_id), None)
                if insert_idx is not None:
                    rows.insert(insert_idx + 1, new_row)
                    for i, r in enumerate(rows):
                        r["num"] = i + 1
                else:
                    rows.append(new_row)
            else:
                rows.append(new_row)
            rows_by_id[new_id] = new_row

    return rows


_CONTEXT_FILE_TYPES = {"Проект", "ТЗ", "Другое"}
_CONTEXT_TEXT_LIMIT = 8000  # chars per file — protect against context overflow


async def _load_client_context(
    task: Task, db: AsyncSession
) -> tuple[str, list[dict]]:
    """Load non-Смета client files and return (text_context, image_blocks).

    text_context — formatted string to inject into the prompt.
    image_blocks — list of Claude content block dicts (PDF / images).
    """
    user_prompt_meta: dict = {}
    if task.user_prompt:
        try:
            user_prompt_meta = _json_top.loads(task.user_prompt)
        except (ValueError, TypeError):
            pass

    client_files_meta: list[dict] = user_prompt_meta.get("client_files", [])
    if not client_files_meta:
        return "", []

    # Build index → type mapping for non-"Смета" files
    context_indices: dict[int, str] = {}
    for cf in client_files_meta:
        idx = cf.get("index")
        ftype = cf.get("type", "")
        if isinstance(idx, int) and ftype in _CONTEXT_FILE_TYPES:
            context_indices[idx] = ftype

    if not context_indices:
        return "", []

    result = await db.execute(
        select(TaskInputFile)
        .where(TaskInputFile.task_id == task.id)
        .order_by(TaskInputFile.file_index)
    )
    input_files = result.scalars().all()

    text_parts: list[str] = []
    image_blocks: list[dict] = []

    for f in input_files:
        ftype = context_indices.get(f.file_index)
        if ftype is None:
            continue
        _fbytes = await storage_service.load_bytes(f.storage_key)
        content_b64 = base64.b64encode(_fbytes).decode("utf-8")
        try:
            parsed = _parse_file(f.file_name, f.mime_type, content_b64)
        except Exception:
            continue

        if isinstance(parsed, str):
            text = parsed
            if len(text) > _CONTEXT_TEXT_LIMIT:
                text = text[:_CONTEXT_TEXT_LIMIT] + "\n...(обрезано)"
            text_parts.append(f"[{ftype}: {f.file_name}]\n{text}")
        elif isinstance(parsed, dict):
            # PDF or image block for Claude Vision
            image_blocks.append(parsed)
            text_parts.append(f"[{ftype}: {f.file_name}] — передан как документ/изображение")

    text_context = ""
    if text_parts:
        text_context = (
            "\n\n=== ДОКУМЕНТАЦИЯ ЗАКАЗЧИКА ===\n"
            + "\n\n".join(text_parts)
            + "\n=== КОНЕЦ ДОКУМЕНТАЦИИ ===\n"
        )

    return text_context, image_blocks


async def _run_optimization_step(
    task_id: str,
    step: str,  # "completeness" | "redundancy" | "technology" | "materials"
) -> None:
    """Background task: run an AI optimization step and create a new EstimateVersion."""
    from app.services.claude_service import call_claude
    from app.utils.json_utils import extract_json
    import json as _json

    step_labels = {
        "completeness": ("completeness_checked", "V1 - Полнота"),
        "redundancy": ("no_redundant", "V2 - Лишнее"),
        "technology": ("tech_optimized", "V3 - Технологии"),
        "materials": ("material_optimized", "V4 - Материалы"),
    }
    next_label, display_name = step_labels[step]

    RESPONSE_FORMAT = (
        "\n\nВерни СТРОГО в формате JSON без markdown-блоков:\n"
        '{"proposals": [{"id": "uuid4", "row_id": "id строки или null для add", '
        '"after_row_id": "id строки после которой вставить новую (только для add, иначе null)", '
        '"proposal_type": "add|remove|replace_tech|replace_material", '
        '"description": "краткое: что меняем", "explanation": "обоснование", '
        '"economy_rub": число_или_null, "confidence": "high|medium|low", '
        '"new_value": {name,type,unit,qty,price_work,price_material}_или_null}]}'
    )

    _CONTEXT_HINT = (
        "\nЕсли выше передана документация заказчика (Проект, ТЗ, спецификации) — "
        "используй её при анализе: границы работ, требования, ограничения.\n"
    )

    step_prompts = {
        "completeness": (
            "Ты — опытный инженер-сметчик со знанием ГЭСН-2017/ФСНБ-2022.\n\n"
            "Для каждой работы в смете проверь:\n"
            "1. Все ли нормативно необходимые материалы учтены (по ГЭСН/ФСНБ для данного вида работ).\n"
            "2. Соответствуют ли объёмы материалов расходным нормам ГЭСН, исходя из объёма работы.\n\n"
            "Если передана проектная документация или ТЗ — используй её для уточнения видов работ и объёмов.\n"
            "Добавляй в результат только реальные несоответствия. "
            "Если не уверен в коде ГЭСН — не называй его, напиши описание работы.\n"
            "Для каждого предложения:\n"
            "- proposal_type='add', row_id=null (новая строка), economy_rub=null\n"
            "- after_row_id = id работы, К КОТОРОЙ относится этот материал (чтобы вставить сразу после неё)\n"
            "- new_value ОБЯЗАТЕЛЕН: {\"name\": название, \"type\": \"material\", \"unit\": ед.изм., "
            "\"qty\": количество_число_или_null, \"price_work\": null, \"price_material\": цена_или_null}\n"
            "Если количество или цена неизвестны — ставь null, но поле name и unit обязательны.\n"
            + _CONTEXT_HINT
        ),
        "redundancy": (
            "Ты — опытный инженер-сметчик со знанием ГЭСН-2017/ФСНБ-2022.\n\n"
            "Найди в смете ЛИШНИЕ позиции по четырём категориям:\n\n"
            "1. ДУБЛИРОВАНИЕ — одна и та же работа/материал указаны дважды с одним назначением.\n"
            "   Важно: материал для разных работ — НЕ дубль. Дубль — только если совпадают и материал/работа, И назначение.\n\n"
            "2. НОРМАТИВНОЕ ВКЛЮЧЕНИЕ — позиция входит в состав другой расценки по ГЭСН (double-counting).\n"
            "   Пример: «Очистка поверхности» входит в расценку грунтования (ГЭСН 15-04).\n\n"
            "3. ВНЕ ПРОЕКТА — позиция явно не применима к данному типу работ/объекту.\n"
            "   Если передана проектная документация — опирайся на неё для определения границ работ.\n\n"
            "4. Правило точности: не добавляй позиции, в которых не уверен.\n\n"
            "Для каждого предложения: proposal_type='remove', row_id=id строки, economy_rub=стоимость позиции.\n"
            + _CONTEXT_HINT
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
            "  4. Технология реализуема (учти ограничения объекта из проектной документации если передана)\n"
            "  5. Учти все доп. затраты (аренда оборудования)\n"
            "Если не уверен в коде ГЭСН — не называй его, напиши описание.\n\n"
            "proposal_type='replace_tech', new_value={name,price_work} если известно.\n"
            + _CONTEXT_HINT
        ),
        "materials": (
            "Ты — опытный инженер-сметчик и снабженец.\n\n"
            "Тебе переданы материальные позиции ГРУППЫ А — наиболее дорогостоящие материалы (около 80% суммы).\n\n"
            "Найди возможности снизить стоимость материалов при том же конечном результате.\n\n"
            "Два направления:\n"
            "1. Замена материала — другой материал с теми же характеристиками и функцией.\n"
            "   Примеры: Knauf Rotband → Волма Слой (ГОСТ Р 57957), Импортная арматура → Отечественная А500\n"
            "   Если в документации заказчика указаны ограничения на замену материалов — учти их.\n"
            "2. Закупочная оптимизация — тот же материал, но дешевле за счёт условий закупки.\n"
            "   (укажи в explanation, proposal_type='replace_material', economy_rub=null)\n\n"
            "Для каждого предложения по замене проверь:\n"
            "  1. Функциональный результат не изменится\n"
            "  2. Соответствует ГОСТ/ТУ/СП\n"
            "  3. Экономия > 5%\n"
            "  4. Материал реально доступен\n\n"
            "proposal_type='replace_material', new_value={name,price_material} если известно.\n"
            + _CONTEXT_HINT
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

            # Load client context files (Проект, ТЗ, Другое)
            client_text, image_blocks = await _load_client_context(task, db)

            prompt = (
                step_prompts[step]
                + client_text
                + "\nСтроки сметы (JSON):\n"
                + rows_json
                + RESPONSE_FORMAT
            )

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
                image_data=image_blocks if image_blocks else None,
                use_web_search=False,
                processing_timeout=180.0,
            )

            data = extract_json(response_text)
            proposals_raw = data.get("proposals", [])

            # Assign ids where missing
            for p in proposals_raw:
                if not p.get("id"):
                    p["id"] = str(uuid.uuid4())

            # Auto-apply all proposals — rows already have confidence markers
            applied_rows = _auto_apply_proposals(source_rows, proposals_raw)

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
                rows=applied_rows,  # proposals auto-applied, rows marked with confidence
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
        task = await _get_task_or_404(task_id, db, current_user)
        from app.services import job_queue
        await job_queue.enqueue(db, "version.optimize", {"task_id": task_id, "step": step}, owner_id=task.owner_id)
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
# POST /tasks/{task_id}/estimate/optimize/fill-prices — Шаг 5
# ---------------------------------------------------------------------------

_PROMPT_FILL_PRICES = """Ты — эксперт по строительному сметному делу в России.

Тебе переданы позиции сметы, для которых НЕ найдено совпадений в корпоративном прайсе.
Твоя задача — определить рыночную цену для каждой позиции.

Текущая дата: {current_date}
Регион: г. Екатеринбург, Свердловская область

Для каждой позиции:
1. Найди 3 актуальных рыночных цены (г. Екатеринбург)
   - Для работ: квалифицированные подрядчики с лицензиями/допусками СРО
   - Для материалов: известные поставщики, нормальное качество
2. Поставь среднюю из трёх найденных цен
3. Укажи все 3 источника с ценами в поле sources
4. Цена работ → в поле work_price (если тип "Работа")
5. Цена материалов → в поле material_price (если тип "Материал")

Позиции для оценки:
{unmatched_items_json}

Верни результат СТРОГО в формате JSON, без markdown, первый символ {{,
последний }}:
{{
  "items": [
    {{
      "name": "Наименование позиции",
      "type": "Работа" | "Материал",
      "work_price": число или null,
      "material_price": число или null,
      "sources": "Источник 1: цена₁ руб; Источник 2: цена₂ руб; Источник 3: цена₃ руб"
    }}
  ]
}}"""

_FILL_PRICES_SYSTEM = (
    "IMPORTANT: When the task requires JSON output, return ONLY raw JSON without any "
    "markdown formatting, code blocks, backticks, or explanations. "
    "Start your response directly with { or [ and end with } or ].\n\n"
    "Ты — эксперт по строительному сметному делу в России. "
    "Отвечай чётко, структурированно, на русском языке. "
    "При указании цен ссылайся на источник."
)


async def _run_fill_prices_step(task_id: str) -> None:
    """Background: find prices for rows without prices using price list → Claude web search."""
    import json as _json
    import uuid as _uuid
    from datetime import date as _date
    from app.services import price_service as _ps
    from app.services.claude_service import call_claude
    from app.utils.json_utils import extract_json

    STEP = "fill_prices"

    async with AsyncSessionLocal() as db:
        try:
            task = await db.get(Task, task_id)
            if not task:
                return

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
                task.progress_data = {"opt_step": STEP, "status": "error", "error": "Нет версий сметы"}
                await db.commit()
                return

            source_rows: list[dict] = list(source_version.rows or [])

            def _has_no_price(row: dict) -> bool:
                r_type = row.get("type", "")
                if r_type == "work":
                    return not (row.get("price_work") or 0)
                if r_type == "material":
                    return not (row.get("price_material") or 0)
                return False

            unpriced = [r for r in source_rows if _has_no_price(r)]

            # Helper: create new version and signal done
            async def _create_version_and_signal(rows: list, proposals: list, all_priced: bool) -> None:
                count_res = await db.execute(
                    select(EstimateVersion).where(EstimateVersion.task_id == task_id)
                )
                all_v = count_res.scalars().all()
                next_num = _next_version_number(all_v)
                new_ver = EstimateVersion(
                    id=str(_uuid.uuid4()),
                    task_id=task_id,
                    version_number=next_num,
                    version_label="prices_filled",
                    version_display_name="V5 - Цены",
                    rows=rows,
                    overhead_pct=source_version.overhead_pct,
                    transport_pct=source_version.transport_pct,
                    contingency_pct=source_version.contingency_pct,
                    expenses_overridden=source_version.expenses_overridden,
                    optimization_proposals=proposals,
                )
                db.add(new_ver)
                task.progress_message = None
                task.progress_data = {
                    "opt_step": STEP,
                    "status": "done",
                    "all_priced": all_priced,
                    "proposals": proposals,
                    "new_version_id": str(new_ver.id),
                }
                await db.commit()

            if not unpriced:
                await _create_version_and_signal(source_rows, [], True)
                return

            task.progress_message = f"Проставляем цены: 0/{len(unpriced)} позиций..."
            task.progress_data = {"opt_step": STEP, "status": "running"}
            await db.commit()

            # ── Step 1: price list (exact + embedding, no web) ──────────────
            price_list_hits: dict[str, dict] = {}   # row_id → {price_work|price_material, price_list_name}
            for_claude: list[dict] = []

            for row in unpriced:
                row_id = str(row.get("id", ""))
                name = str(row.get("name", "")).strip()
                r_type = row.get("type", "")
                found = False

                if r_type == "work":
                    work_info = _ps._exact_match_work(name)
                    if work_info is None:
                        work_info = await _ps._embedding_match_work(name)
                    if work_info and work_info.get("min_price"):
                        price_list_hits[row_id] = {
                            "price_work": float(work_info["min_price"]),
                            "price_list_name": work_info.get("name", name),
                        }
                        found = True

                elif r_type == "material":
                    mat = _ps._exact_match_material(name)
                    if mat is None:
                        mat = await _ps._embedding_match_material(name)
                    if mat is not None:
                        price_list_hits[row_id] = {
                            "price_material": float(mat),
                            "price_list_name": name,
                        }
                        found = True

                if not found:
                    for_claude.append({
                        "id": row_id,
                        "type": "Работа" if r_type == "work" else "Материал",
                        "name": name,
                        "unit": row.get("unit", ""),
                        "quantity": row.get("qty"),
                    })

            # ── Step 2: Claude + web for items not in price list ────────────
            claude_results: dict[str, dict] = {}

            if for_claude:
                current_date = _date.today().strftime("%d.%m.%Y")
                # Chunk at "Работа" boundaries, max 25 per chunk
                chunks: list[list] = []
                cur_chunk: list = []
                for it in for_claude:
                    if it["type"] == "Работа" and cur_chunk and len(cur_chunk) >= 25:
                        chunks.append(cur_chunk)
                        cur_chunk = []
                    cur_chunk.append(it)
                if cur_chunk:
                    chunks.append(cur_chunk)

                for i, chunk in enumerate(chunks):
                    task.progress_message = f"Claude: часть {i + 1}/{len(chunks)}..."
                    await db.commit()

                    items_payload = [
                        {"type": it["type"], "name": it["name"],
                         "unit": it["unit"], "quantity": it.get("quantity")}
                        for it in chunk
                    ]
                    prompt_text = _PROMPT_FILL_PRICES.format(
                        current_date=current_date,
                        unmatched_items_json=_json.dumps(items_payload, ensure_ascii=False, indent=2),
                    )
                    try:
                        resp = await call_claude(
                            messages=[{"role": "user", "content": prompt_text}],
                            system_prompt=_FILL_PRICES_SYSTEM,
                            use_web_search=True,
                        )
                        data = extract_json(resp)
                        for item in data.get("items", []):
                            key = str(item.get("name", "")).strip()
                            claude_results[key] = item
                    except Exception as e:
                        logger.warning("fill_prices Claude chunk failed", chunk=i + 1, error=str(e))

            # ── Step 3: build updated rows + proposals ───────────────────────
            updated_rows: list[dict] = []
            proposals: list[dict] = []

            for row in source_rows:
                row_copy = dict(row)
                row_id = str(row.get("id", ""))
                name = str(row.get("name", "")).strip()
                r_type = row.get("type", "")

                if row_id in price_list_hits:
                    hit = price_list_hits[row_id]
                    pl_name = hit["price_list_name"]
                    if r_type == "work":
                        row_copy["price_work"] = hit["price_work"]
                    elif r_type == "material":
                        row_copy["price_material"] = hit["price_material"]
                    row_copy["optimization_note"] = f"Из прайса: {pl_name}"
                    proposals.append({
                        "id": str(_uuid.uuid4()),
                        "row_id": row_id,
                        "proposal_type": "price_search",
                        "description": f"Цена из прайса: {pl_name}",
                        "explanation": f"Из прайса: {pl_name}",
                        "economy_rub": None,
                        "confidence": "high",
                        "source": f"Из прайса: {pl_name}",
                        "new_value": None,
                    })

                elif _has_no_price(row) and r_type in ("work", "material"):
                    cr = claude_results.get(name)
                    if cr:
                        sources = cr.get("sources", "")
                        note = f"Из интернета: {sources}" if sources else "Из интернета"
                        filled_price: Optional[float] = None
                        if r_type == "work" and cr.get("work_price"):
                            row_copy["price_work"] = float(cr["work_price"])
                            filled_price = float(cr["work_price"])
                        elif r_type == "material" and cr.get("material_price"):
                            row_copy["price_material"] = float(cr["material_price"])
                            filled_price = float(cr["material_price"])
                        if filled_price is not None:
                            row_copy["optimization_note"] = note
                            proposals.append({
                                "id": str(_uuid.uuid4()),
                                "row_id": row_id,
                                "proposal_type": "price_search",
                                "description": f"Цена из интернета: {filled_price}",
                                "explanation": note,
                                "economy_rub": None,
                                "confidence": "medium",
                                "source": sources,
                                "new_value": None,
                            })

                updated_rows.append(row_copy)

            await _create_version_and_signal(updated_rows, proposals, False)
            logger.info("fill_prices step done", task_id=task_id, filled=len(proposals))

        except Exception as e:
            logger.error("fill_prices step failed", task_id=task_id, error=str(e))
            try:
                task = await db.get(Task, task_id)
                if task:
                    task.progress_message = None
                    task.progress_data = {"opt_step": STEP, "status": "error", "error": str(e)}
                    await db.commit()
            except Exception:
                pass


@router.post("/{task_id}/estimate/optimize/fill-prices", summary="Шаг 5 — Проставить цены")
async def optimize_fill_prices(
    task_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    task = await _get_task_or_404(task_id, db, current_user)
    from app.services import job_queue
    await job_queue.enqueue(db, "version.fill_prices", {"task_id": task_id}, owner_id=task.owner_id)
    return {"status": "running", "step": "fill_prices"}


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
    await _get_task_or_404(version.task_id, db, current_user)
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
    proposals: Optional[list[dict]] = None  # inline proposals (e.g. from custom optimization, not stored in version)


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
    # prefer inline proposals (from custom single-row optimization, not persisted in version)
    proposals = body.proposals if body.proposals is not None else (version.optimization_proposals or [])

    accepted = {p["id"]: p for p in proposals if p.get("id") in body.accepted_proposal_ids}
    if not accepted:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нет принятых предложений")

    rows = _copy.deepcopy(version.rows or [])
    rows_by_id = {r["id"]: r for r in rows}

    for proposal in accepted.values():
        ptype = proposal.get("proposal_type")
        row_id = proposal.get("row_id")

        if ptype == "remove":
            target = rows_by_id.get(row_id)
            if target:
                target["is_excluded"] = True
                target["optimization_note"] = proposal.get("explanation") or proposal.get("description") or ""

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
    task = await _get_task_or_404(task_id, db, current_user)
    from datetime import datetime, timezone
    task.manually_edited_at = datetime.now(timezone.utc)
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
    from urllib.parse import quote as _quote
    from app.services.excel_service import generate_estimate_export

    version = await _get_version_or_404(task_id, version_id, db)
    await _get_task_or_404(version.task_id, db, current_user)

    try:
        # CPU-тяжёлая генерация xlsx — в отдельный поток, чтобы не блокировать loop.
        xlsx_bytes = await asyncio.to_thread(
            generate_estimate_export,
            rows=version.rows or [],
            overhead_pct=float(version.overhead_pct or 0),
            transport_pct=float(version.transport_pct or 0),
            contingency_pct=float(version.contingency_pct or 0),
            version_display_name=version.version_display_name,
        )
    except Exception as exc:
        logger.error("export_version failed", error=str(exc), task_id=task_id, version_id=version_id, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Ошибка генерации файла: {exc}")

    safe_name = version.version_display_name.replace(" ", "_").replace("/", "-")
    ascii_fallback = f"smeta_v{version.version_number}.xlsx"
    utf8_encoded = _quote(f"smeta_{safe_name}.xlsx", safe="")
    content_disposition = f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{utf8_encoded}"

    return StreamingResponse(
        _io.BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": content_disposition},
    )


class CustomerEstimateExport(BaseModel):
    works: float = 0
    materials: float = 0
    vat: float = 0
    grand_total: float = 0


class ComparisonExportBody(BaseModel):
    version_ids: list[str]
    customer_estimate: Optional[CustomerEstimateExport] = None


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

    await _get_task_or_404(task_id, db, current_user)

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

    customer_est = body.customer_estimate.model_dump() if body.customer_estimate else None
    # CPU-тяжёлая генерация xlsx — в отдельный поток, чтобы не блокировать loop.
    xlsx_bytes = await asyncio.to_thread(generate_comparison_export, versions_data, customer_estimate=customer_est)

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
    await _get_task_or_404(version.task_id, db, current_user)

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
    await _get_task_or_404(version.task_id, db, current_user)
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
    await _get_task_or_404(source.task_id, db, current_user)

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
