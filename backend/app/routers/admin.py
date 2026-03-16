import io
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
import openpyxl
import structlog

from app.database import get_db
from app.models.task import Task
from app.models.price import PriceWork, PriceMaterial
from app.utils.auth import get_admin_user
from app.services import price_service

logger = structlog.get_logger()

router = APIRouter(prefix="/admin", tags=["admin"])


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

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Paginate
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
    """Get full task details including chat history."""
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Задача не найдена",
        )

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


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_admin_user),
):
    """Delete a task and all its results (cascade)."""
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Задача не найдена",
        )

    await db.delete(task)
    await db.commit()
    logger.info("Task deleted by admin", task_id=task_id)


def _parse_price_xlsx(data: bytes) -> tuple[list[dict], list[dict]]:
    """
    Parse price list Excel file.
    Expected sheets: 'Работы' and 'Материалы' (or similar names).
    Returns (works, materials) as lists of dicts.
    """
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)

    works = []
    materials = []

    # Find works sheet
    works_sheet = None
    materials_sheet = None

    for name in wb.sheetnames:
        lower = name.lower()
        if "работ" in lower or "work" in lower:
            works_sheet = wb[name]
        elif "материал" in lower or "material" in lower:
            materials_sheet = wb[name]

    # Parse works sheet
    if works_sheet:
        works = _parse_price_sheet(works_sheet, is_works=True)

    # Parse materials sheet
    if materials_sheet:
        materials = _parse_price_sheet(materials_sheet, is_works=False)

    return works, materials


def _parse_price_sheet(ws, is_works: bool) -> list[dict]:
    """
    Parse a price sheet.
    Expected columns: Наименование, Ед. изм., then contractor columns (for works)
    or: Наименование, Ед. изм., Цена (for materials)
    """
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    # Find header row - look for "Наименование"
    header_row_idx = 0
    headers = []
    for i, row in enumerate(rows):
        for cell in row:
            if cell and isinstance(cell, str) and "наименование" in cell.lower():
                header_row_idx = i
                headers = [str(h).strip() if h else "" for h in row]
                break
        if headers:
            break

    if not headers:
        # Use first row as headers
        headers = [str(h).strip() if h else "" for h in rows[0]]
        header_row_idx = 0

    # Find column indices
    name_col = None
    unit_col = None
    price_col = None
    contractor_cols = []

    for i, h in enumerate(headers):
        lower = h.lower()
        if "наименование" in lower or "название" in lower:
            name_col = i
        elif "ед" in lower and ("изм" in lower or "." in lower):
            unit_col = i
        elif "цена" in lower or "стоимость" in lower:
            price_col = i

    if name_col is None:
        return []

    # For works, all numeric columns after unit are contractor prices
    if is_works:
        for i, h in enumerate(headers):
            if i != name_col and i != unit_col and h:
                contractor_cols.append((i, h))

    result = []
    for row in rows[header_row_idx + 1:]:
        if not row or all(cell is None for cell in row):
            continue

        name = row[name_col] if name_col is not None and name_col < len(row) else None
        if not name:
            continue
        name = str(name).strip()
        if not name or name.lower() in ("итого", "всего"):
            continue

        unit = ""
        if unit_col is not None and unit_col < len(row) and row[unit_col]:
            unit = str(row[unit_col]).strip()

        if is_works:
            prices = {}
            for col_idx, contractor_name in contractor_cols:
                if col_idx < len(row) and row[col_idx] is not None:
                    try:
                        prices[contractor_name] = float(row[col_idx])
                    except (ValueError, TypeError):
                        pass
            min_price = min(prices.values()) if prices else None
            result.append({
                "name": name,
                "unit": unit,
                "prices": prices,
                "min_price": min_price,
            })
        else:
            price = None
            if price_col is not None and price_col < len(row) and row[price_col] is not None:
                try:
                    price = float(row[price_col])
                except (ValueError, TypeError):
                    pass
            result.append({
                "name": name,
                "unit": unit,
                "price": price,
            })

    return result


@router.post("/prices/upload", response_model=PriceUploadResponse)
async def upload_prices(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_admin_user),
):
    """
    Upload price list Excel file.
    Parses works and materials sheets, replaces existing prices.
    """
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Файл не выбран",
        )

    allowed_types = {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
    }
    if file.content_type not in allowed_types and not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Принимаются только файлы Excel (.xlsx, .xls)",
        )

    data = await file.read()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Файл пустой",
        )

    try:
        works_data, materials_data = _parse_price_xlsx(data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Ошибка разбора файла: {e}",
        )

    now = datetime.now(timezone.utc)

    # Clear existing prices
    await db.execute(delete(PriceWork))
    await db.execute(delete(PriceMaterial))
    await db.commit()

    # Insert new works
    for item in works_data:
        work = PriceWork(
            name=item["name"],
            unit=item.get("unit", ""),
            prices=item.get("prices", {}),
            min_price=item.get("min_price"),
            updated_at=now,
        )
        db.add(work)

    # Insert new materials
    for item in materials_data:
        material = PriceMaterial(
            name=item["name"],
            unit=item.get("unit", ""),
            price=item.get("price"),
            updated_at=now,
        )
        db.add(material)

    await db.commit()

    # Reload cache
    await price_service.load_cache(db)

    logger.info(
        "Prices uploaded",
        works=len(works_data),
        materials=len(materials_data),
    )

    return PriceUploadResponse(
        works_loaded=len(works_data),
        materials_loaded=len(materials_data),
    )
