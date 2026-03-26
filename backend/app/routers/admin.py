import base64
import csv
import io
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
import openpyxl
import structlog

from sqlalchemy import text
from app.database import get_db
from app.models.task import Task
from app.models.price import PriceWork, PriceMaterial
from app.models.price_list import PriceList
from app.utils.auth import get_admin_user
from app.services import price_service

logger = structlog.get_logger()

router = APIRouter(prefix="/admin", tags=["admin"])

PRICE_LIST_ALLOWED_EXTS = {".xlsx", ".xls", ".csv", ".txt", ".pdf", ".docx"}
MAX_PRICE_FILE_BYTES = 20 * 1024 * 1024  # 20 MB


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class TaskListItem(BaseModel):
    id: str
    user_role: str
    task_type: str
    status: str
    progress_message: Optional[str]
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime
    files_count: int


class TaskDetail(BaseModel):
    id: str
    user_role: str
    task_type: str
    status: str
    input_files: list
    user_prompt: Optional[str]
    chat_history: list
    progress_message: Optional[str]
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime


class TaskListResponse(BaseModel):
    items: list[TaskListItem]
    total: int


class PriceUploadResponse(BaseModel):
    works_loaded: int
    materials_loaded: int


class PriceListInfo(BaseModel):
    type: str
    filename: Optional[str]
    updated_at: Optional[str]


class PriceListsInfoResponse(BaseModel):
    works: PriceListInfo
    materials: PriceListInfo


class SinglePriceUploadResponse(BaseModel):
    loaded: int
    message: str


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_price_rows(rows: list, is_works: bool) -> list[dict]:
    """
    Parse price data from a list of rows (list of cell values).
    Auto-detects header row by looking for 'Наименование' or falling back to row 0.
    """
    if not rows:
        return []

    # Find header row
    header_row_idx = 0
    headers: list[str] = []
    for i, row in enumerate(rows):
        for cell in row:
            if cell and isinstance(cell, str) and "наименование" in cell.lower():
                header_row_idx = i
                headers = [str(h).strip() if h is not None else "" for h in row]
                break
        if headers:
            break

    if not headers:
        headers = [str(h).strip() if h is not None else "" for h in rows[0]]
        header_row_idx = 0

    # Map column indices
    name_col: Optional[int] = None
    unit_col: Optional[int] = None
    price_col: Optional[int] = None
    contractor_cols: list[tuple[int, str]] = []

    for i, h in enumerate(headers):
        lower = h.lower()
        if "наименование" in lower or "название" in lower or "name" in lower:
            name_col = i
        elif ("ед" in lower and ("изм" in lower or "." in lower)) or lower in ("ед", "unit"):
            unit_col = i
        elif "цена" in lower or "стоимость" in lower or "price" in lower:
            price_col = i

    if name_col is None:
        return []

    # For works: all non-name/unit columns with headers are contractor price cols
    if is_works:
        for i, h in enumerate(headers):
            if i != name_col and i != unit_col and h:
                contractor_cols.append((i, h))

    result = []
    for row in rows[header_row_idx + 1:]:
        if not row or all(cell is None or str(cell).strip() == "" for cell in row):
            continue

        name = row[name_col] if name_col < len(row) else None
        if not name:
            continue
        name = str(name).strip()
        if not name or name.lower() in ("итого", "всего", "total"):
            continue

        unit = ""
        if unit_col is not None and unit_col < len(row) and row[unit_col] is not None:
            unit = str(row[unit_col]).strip()

        if is_works:
            prices: dict[str, float] = {}
            for col_idx, contractor_name in contractor_cols:
                if col_idx < len(row) and row[col_idx] is not None:
                    try:
                        prices[contractor_name] = float(row[col_idx])
                    except (ValueError, TypeError):
                        pass
            min_price = min(prices.values()) if prices else None
            result.append({"name": name, "unit": unit, "prices": prices, "min_price": min_price})
        else:
            price: Optional[float] = None
            col = price_col if price_col is not None else (
                # Fall back to last non-name/unit numeric column
                next(
                    (i for i in range(len(row) - 1, -1, -1)
                     if i != name_col and i != unit_col and row[i] is not None),
                    None,
                )
            )
            if col is not None and col < len(row) and row[col] is not None:
                try:
                    price = float(row[col])
                except (ValueError, TypeError):
                    pass
            result.append({"name": name, "unit": unit, "price": price})

    return result


def _parse_xlsx_single(data: bytes, is_works: bool) -> list[dict]:
    """Parse a single-type xlsx/xls file (all sheets tried)."""
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    for sheet_name in wb.sheetnames:
        rows = list(wb[sheet_name].iter_rows(values_only=True))
        items = _parse_price_rows(rows, is_works)
        if items:
            return items
    return []


def _parse_xlsx_combined(data: bytes) -> tuple[list[dict], list[dict]]:
    """
    Parse combined xlsx with 'Работы' and 'Материалы' sheets.
    Used by the legacy /prices/upload endpoint.
    """
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    works: list[dict] = []
    materials: list[dict] = []
    for name in wb.sheetnames:
        lower = name.lower()
        rows = list(wb[name].iter_rows(values_only=True))
        if "работ" in lower or "work" in lower:
            works = _parse_price_rows(rows, is_works=True)
        elif "материал" in lower or "material" in lower:
            materials = _parse_price_rows(rows, is_works=False)
    return works, materials


def _parse_csv_single(data: bytes, is_works: bool) -> list[dict]:
    """Parse a CSV or TXT price list file."""
    text = data.decode("utf-8-sig", errors="replace")
    # Detect delimiter
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = [list(row) for row in reader]
    return _parse_price_rows(rows, is_works)


def _parse_file_for_type(data: bytes, filename: str, mime_type: str, is_works: bool) -> list[dict]:
    """Route file to the correct parser based on extension."""
    lower = filename.lower()
    if lower.endswith(".xlsx") or lower.endswith(".xls"):
        return _parse_xlsx_single(data, is_works)
    if lower.endswith(".csv") or lower.endswith(".txt"):
        return _parse_csv_single(data, is_works)
    # PDF / DOCX — cannot parse automatically
    return []


def _ext_from_filename(filename: str) -> str:
    return "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


# ---------------------------------------------------------------------------
# Task endpoints
# ---------------------------------------------------------------------------

@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    task_type: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_admin_user),
):
    """Get paginated list of all tasks with optional filters."""
    query = select(Task)

    if date_from:
        query = query.where(Task.created_at >= date_from)
    if date_to:
        query = query.where(Task.created_at <= date_to)
    if status_filter:
        query = query.where(Task.status == status_filter)
    if task_type:
        query = query.where(Task.task_type == task_type)

    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(Task.created_at.desc())
    query = query.offset((page - 1) * limit).limit(limit)

    result = await db.execute(query)
    tasks = result.scalars().all()

    items = [
        TaskListItem(
            id=str(t.id),
            user_role=t.user_role,
            task_type=t.task_type,
            status=t.status,
            progress_message=t.progress_message,
            error_message=t.error_message,
            created_at=t.created_at,
            updated_at=t.updated_at,
            files_count=len(t.input_files or []),
        )
        for t in tasks
    ]
    return TaskListResponse(items=items, total=total)


@router.get("/tasks/{task_id}", response_model=TaskDetail)
async def get_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_admin_user),
):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    return TaskDetail(
        id=str(task.id),
        user_role=task.user_role,
        task_type=task.task_type,
        status=task.status,
        input_files=task.input_files or [],
        user_prompt=task.user_prompt,
        chat_history=task.chat_history or [],
        progress_message=task.progress_message,
        error_message=task.error_message,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


@router.get("/tasks/{task_id}/download-input/{file_index}")
async def download_input_file(
    task_id: str,
    file_index: int,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_admin_user),
):
    """Download an original input file for a task by index."""
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")

    file_data_list = task.input_file_data or []
    if file_index < 0 or file_index >= len(file_data_list):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")

    file_info = file_data_list[file_index]
    content_b64 = file_info.get("content_b64", "")
    if not content_b64:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Содержимое файла отсутствует")

    content = base64.b64decode(content_b64)
    mime_type = file_info.get("mime_type", "application/octet-stream")
    name = file_info.get("name", f"file_{file_index}")

    return Response(
        content=content,
        media_type=mime_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
    )


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_admin_user),
):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    await db.delete(task)
    await db.commit()
    logger.info("Task deleted by admin", task_id=task_id)


# ---------------------------------------------------------------------------
# Price list info endpoint
# ---------------------------------------------------------------------------

@router.get("/price-lists/info", response_model=PriceListsInfoResponse)
async def get_price_lists_info(
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_admin_user),
):
    """Return metadata for currently stored works and materials price lists."""
    async def _get_info(pl_type: str) -> PriceListInfo:
        res = await db.execute(
            select(PriceList)
            .where(PriceList.type == pl_type)
            .order_by(PriceList.updated_at.desc())
            .limit(1)
        )
        row = res.scalar_one_or_none()
        if row:
            return PriceListInfo(
                type=pl_type,
                filename=row.filename,
                updated_at=row.updated_at.isoformat(),
            )
        return PriceListInfo(type=pl_type, filename=None, updated_at=None)

    return PriceListsInfoResponse(
        works=await _get_info("works"),
        materials=await _get_info("materials"),
    )


# ---------------------------------------------------------------------------
# Separate upload endpoints
# ---------------------------------------------------------------------------

async def _handle_price_upload(
    file: UploadFile,
    pl_type: str,
    is_works: bool,
    db: AsyncSession,
) -> SinglePriceUploadResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Файл не выбран")

    ext = _ext_from_filename(file.filename)
    if ext not in PRICE_LIST_ALLOWED_EXTS:
        raise HTTPException(
            status_code=415,
            detail=f"Недопустимый формат. Разрешены: {', '.join(PRICE_LIST_ALLOWED_EXTS)}",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Файл пустой")
    if len(data) > MAX_PRICE_FILE_BYTES:
        raise HTTPException(status_code=413, detail="Файл превышает 20 МБ")

    mime_type = file.content_type or "application/octet-stream"
    now = datetime.now(timezone.utc)

    # Try to parse data into price rows
    try:
        items = _parse_file_for_type(data, file.filename, mime_type, is_works)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Ошибка разбора файла: {e}")

    # Persist raw file (upsert: delete old, insert new)
    await db.execute(delete(PriceList).where(PriceList.type == pl_type))
    db.add(PriceList(
        type=pl_type,
        filename=file.filename,
        mime_type=mime_type,
        content=data,
        updated_at=now,
    ))

    # Update price tables if we got rows
    if items:
        if is_works:
            await db.execute(delete(PriceWork))
            for item in items:
                db.add(PriceWork(
                    name=item["name"],
                    unit=item.get("unit", ""),
                    prices=item.get("prices", {}),
                    min_price=item.get("min_price"),
                    updated_at=now,
                ))
        else:
            await db.execute(delete(PriceMaterial))
            for item in items:
                db.add(PriceMaterial(
                    name=item["name"],
                    unit=item.get("unit", ""),
                    price=item.get("price"),
                    updated_at=now,
                ))

    await db.commit()
    await price_service.load_cache(db)

    loaded = len(items)
    if loaded == 0 and ext in (".pdf", ".docx"):
        msg = "Файл сохранён. Автоматический разбор PDF/DOCX не поддерживается — данные в базе не обновлены."
    elif loaded == 0:
        msg = "Файл сохранён, но позиции не найдены. Проверьте структуру файла (нужны колонки Наименование, Цена)."
    else:
        kind = "работ" if is_works else "материалов"
        msg = f"Прайс {kind} успешно загружен: {loaded} позиций."

    logger.info("Price list uploaded", type=pl_type, filename=file.filename, loaded=loaded)
    return SinglePriceUploadResponse(loaded=loaded, message=msg)


@router.post("/price-lists/works", response_model=SinglePriceUploadResponse)
async def upload_works_price_list(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_admin_user),
):
    """Upload price list for works. Replaces existing works prices."""
    return await _handle_price_upload(file, "works", is_works=True, db=db)


@router.post("/price-lists/materials", response_model=SinglePriceUploadResponse)
async def upload_materials_price_list(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_admin_user),
):
    """Upload price list for materials. Replaces existing materials prices."""
    return await _handle_price_upload(file, "materials", is_works=False, db=db)


# ---------------------------------------------------------------------------
# Legacy combined upload (kept for backward compatibility)
# ---------------------------------------------------------------------------

@router.post("/prices/upload", response_model=PriceUploadResponse)
async def upload_prices(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_admin_user),
):
    """
    Upload combined price list Excel file with 'Работы' and 'Материалы' sheets.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Файл не выбран")

    allowed_exts = {".xlsx", ".xls"}
    if _ext_from_filename(file.filename) not in allowed_exts:
        raise HTTPException(status_code=415, detail="Принимаются только файлы Excel (.xlsx, .xls)")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Файл пустой")

    try:
        works_data, materials_data = _parse_xlsx_combined(data)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Ошибка разбора файла: {e}")

    now = datetime.now(timezone.utc)
    await db.execute(delete(PriceWork))
    await db.execute(delete(PriceMaterial))
    await db.commit()

    for item in works_data:
        db.add(PriceWork(
            name=item["name"], unit=item.get("unit", ""),
            prices=item.get("prices", {}), min_price=item.get("min_price"), updated_at=now,
        ))
    for item in materials_data:
        db.add(PriceMaterial(
            name=item["name"], unit=item.get("unit", ""),
            price=item.get("price"), updated_at=now,
        ))

    await db.commit()
    await price_service.load_cache(db)

    logger.info("Combined prices uploaded", works=len(works_data), materials=len(materials_data))
    return PriceUploadResponse(works_loaded=len(works_data), materials_loaded=len(materials_data))


# ---------------------------------------------------------------------------
# TEMPORARY: one-shot DB repair endpoint (remove after prod fix confirmed)
# ---------------------------------------------------------------------------

@router.get("/fix-db")
async def fix_db(
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_admin_user),
):
    """
    Applies missing migrations 004–006 directly via SQL (idempotent).

    Use once on production when alembic_version was stamped to '006' without
    running the actual migration SQL. Remove this endpoint after confirmation.
    """
    steps = []

    ddl_statements = [
        (
            "create_projects_table",
            """
            CREATE TABLE IF NOT EXISTS projects (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name        VARCHAR(255) NOT NULL,
                description TEXT,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """,
        ),
        (
            "add_tasks_project_id",
            """
            ALTER TABLE tasks
                ADD COLUMN IF NOT EXISTS project_id UUID
                    REFERENCES projects(id) ON DELETE SET NULL
            """,
        ),
        (
            "add_tasks_estimation_status",
            """
            ALTER TABLE tasks
                ADD COLUMN IF NOT EXISTS estimation_status VARCHAR(20)
                    NOT NULL DEFAULT 'not_applicable'
            """,
        ),
        (
            "add_tasks_cost",
            """
            ALTER TABLE tasks
                ADD COLUMN IF NOT EXISTS cost NUMERIC(12,2)
            """,
        ),
        (
            "add_task_results_slot",
            """
            ALTER TABLE task_results
                ADD COLUMN IF NOT EXISTS slot VARCHAR(20)
                    NOT NULL DEFAULT 'result'
            """,
        ),
        (
            "update_alembic_version",
            "UPDATE alembic_version SET version_num = '006'",
        ),
    ]

    for step_name, sql in ddl_statements:
        try:
            await db.execute(text(sql))
            steps.append({"step": step_name, "status": "ok"})
            logger.info("fix-db step completed", step=step_name)
        except Exception as exc:
            steps.append({"step": step_name, "status": "error", "detail": str(exc)})
            logger.error("fix-db step failed", step=step_name, error=str(exc))

    await db.commit()

    all_ok = all(s["status"] == "ok" for s in steps)
    return {
        "success": all_ok,
        "steps": steps,
        "message": (
            "All steps completed successfully. Schema is now up to date."
            if all_ok
            else "Some steps failed — see steps for details."
        ),
    }
