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
from sqlalchemy import select, delete, update, func
import openpyxl
import structlog

from app.database import get_db
from app.models.task import Task
from app.models.price import PriceWork, PriceMaterial
from app.models.price_list import PriceList
from app.utils.auth import get_admin_user
from app.services import price_service
from app.services.embedding_service import (
    normalize_name,
    generate_embeddings_batch,
    EmbeddingUnavailableError,
)

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
    deleted_at: Optional[datetime]
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
    embedding_status: str = "pending"


class PriceListsInfoResponse(BaseModel):
    works: PriceListInfo
    materials: PriceListInfo


class SinglePriceUploadResponse(BaseModel):
    loaded: int
    message: str
    added: Optional[int] = None
    updated: Optional[int] = None


class GenerateEmbeddingsResponse(BaseModel):
    status: str
    updated: int = 0
    error: Optional[str] = None


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
    # Build WHERE conditions separately so they apply to both count and data queries
    conditions = [Task.deleted_at.is_(None)]
    if date_from:
        conditions.append(Task.created_at >= date_from)
    if date_to:
        conditions.append(Task.created_at <= date_to)
    if status_filter:
        conditions.append(Task.status == status_filter)
    if task_type:
        conditions.append(Task.task_type == task_type)

    # COUNT: select only id — avoids loading input_file_data / chat_history
    count_query = select(func.count(Task.id)).where(*conditions)
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # DATA: select only the columns needed for TaskListItem
    data_query = select(
        Task.id, Task.user_role, Task.task_type, Task.status,
        Task.progress_message, Task.error_message,
        Task.created_at, Task.updated_at, Task.deleted_at, Task.input_files,
    ).where(*conditions).order_by(Task.created_at.desc()).offset((page - 1) * limit).limit(limit)

    result = await db.execute(data_query)
    rows = result.all()

    items = [
        TaskListItem(
            id=str(row.id),
            user_role=row.user_role,
            task_type=row.task_type,
            status=row.status,
            progress_message=row.progress_message,
            error_message=row.error_message,
            created_at=row.created_at,
            updated_at=row.updated_at,
            deleted_at=row.deleted_at,
            files_count=len(row.input_files or []),
        )
        for row in rows
    ]
    return TaskListResponse(items=items, total=total)


@router.get("/tasks/trash", response_model=TaskListResponse)
async def list_trash(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_admin_user),
):
    """Список задач в корзине (deleted_at IS NOT NULL)."""
    conditions = [Task.deleted_at.is_not(None)]

    count_query = select(func.count(Task.id)).where(*conditions)
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    data_query = select(
        Task.id, Task.user_role, Task.task_type, Task.status,
        Task.progress_message, Task.error_message,
        Task.created_at, Task.updated_at, Task.deleted_at, Task.input_files,
    ).where(*conditions).order_by(Task.deleted_at.desc()).offset((page - 1) * limit).limit(limit)

    result = await db.execute(data_query)
    rows = result.all()

    items = [
        TaskListItem(
            id=str(row.id),
            user_role=row.user_role,
            task_type=row.task_type,
            status=row.status,
            progress_message=row.progress_message,
            error_message=row.error_message,
            created_at=row.created_at,
            updated_at=row.updated_at,
            deleted_at=row.deleted_at,
            files_count=len(row.input_files or []),
        )
        for row in rows
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


@router.delete("/tasks/trash", status_code=status.HTTP_204_NO_CONTENT)
async def clear_trash(
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_admin_user),
):
    """Очистить корзину — окончательно удалить все задачи с deleted_at IS NOT NULL."""
    await db.execute(delete(Task).where(Task.deleted_at.is_not(None)))
    await db.commit()
    logger.info("Trash cleared by admin")


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_admin_user),
):
    """Мягкое удаление — перемещает задачу в корзину."""
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    task.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    logger.info("Task moved to trash by admin", task_id=task_id)


@router.post("/tasks/{task_id}/restore", status_code=status.HTTP_204_NO_CONTENT)
async def restore_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_admin_user),
):
    """Восстановить задачу из корзины."""
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    task.deleted_at = None
    await db.commit()
    logger.info("Task restored from trash by admin", task_id=task_id)


@router.delete("/tasks/{task_id}/permanent", status_code=status.HTTP_204_NO_CONTENT)
async def permanent_delete_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_admin_user),
):
    """Окончательное удаление задачи и всех связанных данных."""
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    await db.delete(task)
    await db.commit()
    logger.info("Task permanently deleted by admin", task_id=task_id)


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
                embedding_status=row.embedding_status,
            )
        return PriceListInfo(type=pl_type, filename=None, updated_at=None, embedding_status="pending")

    return PriceListsInfoResponse(
        works=await _get_info("works"),
        materials=await _get_info("materials"),
    )


# ---------------------------------------------------------------------------
# Separate upload endpoints
# ---------------------------------------------------------------------------

_INSERT_BATCH_SIZE = 200


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

    # Generate embeddings before touching the DB (one batch API call)
    embeddings: list = []
    embedding_status = "pending"
    if items:
        try:
            normalized = [normalize_name(item["name"]) for item in items]
            embeddings = generate_embeddings_batch(normalized, input_type="search_document")
            embedding_status = "ready"
            logger.info("Embeddings generated", type=pl_type, count=len(items))
        except EmbeddingUnavailableError as e:
            embeddings = [None] * len(items)
            embedding_status = "failed"
            logger.warning("Embeddings generation failed, price list saved without vectors",
                           type=pl_type, error=str(e))

    # Load existing price rows into memory by normalised name for merge
    if is_works:
        res = await db.execute(select(PriceWork.id, PriceWork.name, PriceWork.unit, PriceWork.prices))
        existing_by_norm: dict = {
            normalize_name(row.name): {"id": row.id, "unit": row.unit, "prices": row.prices or {}}
            for row in res
        }
    else:
        res = await db.execute(select(PriceMaterial.id, PriceMaterial.name, PriceMaterial.unit))
        existing_by_norm = {
            normalize_name(row.name): {"id": row.id, "unit": row.unit}
            for row in res
        }

    # Upsert PriceList metadata (keep one record per type, update on re-upload)
    pl_res = await db.execute(
        select(PriceList).where(PriceList.type == pl_type).limit(1)
    )
    pl_obj = pl_res.scalar_one_or_none()
    if pl_obj:
        pl_obj.filename = file.filename
        pl_obj.mime_type = mime_type
        pl_obj.content = data
        pl_obj.updated_at = now
        pl_obj.embedding_status = embedding_status
    else:
        db.add(PriceList(
            type=pl_type,
            filename=file.filename,
            mime_type=mime_type,
            content=data,
            updated_at=now,
            embedding_status=embedding_status,
        ))
    await db.commit()

    # Separate new items into updates (existing name match) and inserts (new)
    model_cls = PriceWork if is_works else PriceMaterial
    update_ops: list = []   # (id, values_dict)
    insert_objs: list = []  # new ORM objects

    for item, emb in zip(items, embeddings):
        key = normalize_name(item["name"])
        if key in existing_by_norm:
            existing = existing_by_norm[key]
            if is_works:
                merged = {**existing["prices"], **item.get("prices", {})}
                positive = [v for v in merged.values() if v and v > 0]
                values: dict = {
                    "prices": merged,
                    "min_price": min(positive) if positive else None,
                    "unit": item.get("unit") or existing["unit"],
                    "embedding": emb,
                    "updated_at": now,
                }
            else:
                values = {
                    "price": item.get("price"),
                    "unit": item.get("unit") or existing["unit"],
                    "embedding": emb,
                    "updated_at": now,
                }
            update_ops.append((existing["id"], values))
        else:
            if is_works:
                obj = PriceWork(
                    name=item["name"],
                    unit=item.get("unit", ""),
                    prices=item.get("prices", {}),
                    min_price=item.get("min_price"),
                    embedding=emb,
                    updated_at=now,
                )
            else:
                obj = PriceMaterial(
                    name=item["name"],
                    unit=item.get("unit", ""),
                    price=item.get("price"),
                    embedding=emb,
                    updated_at=now,
                )
            insert_objs.append(obj)

    added = len(insert_objs)
    updated_count = len(update_ops)

    # Process updates and inserts in small batches to avoid dropping the DB
    # connection on a single huge transaction (embeddings add ~13 KB per row)
    all_ops = [("update", op) for op in update_ops] + [("insert", obj) for obj in insert_objs]
    for batch_start in range(0, len(all_ops), _INSERT_BATCH_SIZE):
        batch = all_ops[batch_start: batch_start + _INSERT_BATCH_SIZE]
        for kind, payload in batch:
            if kind == "update":
                row_id, values = payload
                await db.execute(
                    update(model_cls).where(model_cls.id == row_id).values(**values)
                )
            else:
                db.add(payload)
        await db.commit()

    await price_service.load_cache(db)

    loaded = len(items)
    if loaded == 0 and ext in (".pdf", ".docx"):
        msg = "Файл сохранён. Автоматический разбор PDF/DOCX не поддерживается — данные в базе не обновлены."
    elif loaded == 0:
        msg = "Файл сохранён, но позиции не найдены. Проверьте структуру файла (нужны колонки Наименование, Цена)."
    else:
        kind = "работ" if is_works else "материалов"
        msg = f"Прайс {kind} обновлён: добавлено {added}, обновлено {updated_count} позиций."

    logger.info("Price list merged", type=pl_type, filename=file.filename, added=added, updated=updated_count)
    return SinglePriceUploadResponse(loaded=loaded, message=msg, added=added, updated=updated_count)


@router.post("/price-lists/works", response_model=SinglePriceUploadResponse)
async def upload_works_price_list(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_admin_user),
):
    """Upload price list for works. Merges with existing works prices (new names added, matching names updated)."""
    return await _handle_price_upload(file, "works", is_works=True, db=db)


@router.post("/price-lists/materials", response_model=SinglePriceUploadResponse)
async def upload_materials_price_list(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_admin_user),
):
    """Upload price list for materials. Merges with existing materials prices (new names added, matching names updated)."""
    return await _handle_price_upload(file, "materials", is_works=False, db=db)


@router.post("/price-lists/{pl_type}/generate-embeddings", response_model=GenerateEmbeddingsResponse)
async def generate_price_embeddings(
    pl_type: str,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(get_admin_user),
):
    """
    Generate (or regenerate) embedding vectors for all rows of a price list.
    Returns HTTP 200 in both success and failure cases — check 'status' field.
    """
    if pl_type not in ("works", "materials"):
        raise HTTPException(status_code=400, detail="Тип должен быть 'works' или 'materials'")

    # Find the price list record
    res = await db.execute(
        select(PriceList)
        .where(PriceList.type == pl_type)
        .order_by(PriceList.updated_at.desc())
        .limit(1)
    )
    price_list = res.scalar_one_or_none()
    if not price_list:
        raise HTTPException(status_code=404, detail="Прайс-лист не найден")

    # Load all rows
    if pl_type == "works":
        rows_res = await db.execute(select(PriceWork))
    else:
        rows_res = await db.execute(select(PriceMaterial))
    rows = rows_res.scalars().all()

    if not rows:
        price_list.embedding_status = "ready"
        await db.commit()
        return GenerateEmbeddingsResponse(status="ready", updated=0)

    try:
        normalized = [normalize_name(row.name) for row in rows]
        embeddings = generate_embeddings_batch(normalized, input_type="search_document")
        for row, emb in zip(rows, embeddings):
            row.embedding = emb
        price_list.embedding_status = "ready"
        await db.commit()
        await price_service.load_cache(db)
        logger.info("Embeddings regenerated via endpoint", type=pl_type, count=len(rows))
        return GenerateEmbeddingsResponse(status="ready", updated=len(rows))
    except EmbeddingUnavailableError as e:
        price_list.embedding_status = "failed"
        await db.commit()
        logger.warning("Embeddings generation failed via endpoint", type=pl_type, error=str(e))
        return GenerateEmbeddingsResponse(status="failed", error=str(e))


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
