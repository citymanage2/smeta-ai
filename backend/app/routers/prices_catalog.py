"""
CRUD-роутер для Каталога расценок.

Позволяет просматривать, добавлять, редактировать и удалять отдельные позиции
из price_works и price_materials. При каждом изменении генерирует эмбеддинг
и перезагружает in-memory кэш price_service.
"""
import asyncio
import io
from datetime import datetime, timezone
from typing import Optional, Literal
from urllib.parse import quote

import openpyxl
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.price import PriceWork, PriceMaterial
from app.services import price_service
from app.services.embedding_service import (
    normalize_name,
    generate_embedding,
    EmbeddingUnavailableError,
)
from app.utils.auth import get_current_user
from app.utils.permissions import get_manager_user

logger = structlog.get_logger()

router = APIRouter(prefix="/prices", tags=["catalog"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class CatalogItem(BaseModel):
    id: int
    kind: Literal["work", "material"]
    name: str
    unit: Optional[str]
    price: Optional[float]          # min_price для работ, price для материалов
    prices: Optional[dict]          # только для работ: {contractor: price}
    updated_at: datetime

    model_config = {"from_attributes": True}


class CatalogResponse(BaseModel):
    items: list[CatalogItem]
    total: int


class CreateWorkBody(BaseModel):
    name: str
    unit: Optional[str] = None
    prices: Optional[dict] = None   # {contractor_name: price}


class CreateMaterialBody(BaseModel):
    name: str
    unit: Optional[str] = None
    price: Optional[float] = None


class UpdateWorkBody(BaseModel):
    name: Optional[str] = None
    unit: Optional[str] = None
    prices: Optional[dict] = None


class UpdateMaterialBody(BaseModel):
    name: Optional[str] = None
    unit: Optional[str] = None
    price: Optional[float] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _work_to_item(w: PriceWork) -> CatalogItem:
    return CatalogItem(
        id=w.id,
        kind="work",
        name=w.name,
        unit=w.unit,
        price=w.min_price,
        prices=w.prices,
        updated_at=w.updated_at,
    )


def _material_to_item(m: PriceMaterial) -> CatalogItem:
    return CatalogItem(
        id=m.id,
        kind="material",
        name=m.name,
        unit=m.unit,
        price=m.price,
        prices=None,
        updated_at=m.updated_at,
    )


async def _generate_embedding_safe(name: str) -> Optional[list]:
    """Generate embedding in thread; return None on any error."""
    try:
        return await asyncio.to_thread(generate_embedding, normalize_name(name), "search_document")
    except EmbeddingUnavailableError:
        return None


async def _reload_cache(db: AsyncSession) -> None:
    await price_service.load_cache(db)


def _escape_like(term: str) -> str:
    """Экранировать спецсимволы LIKE, чтобы поиск по '%' / '_' был буквальным."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _apply_sort(items: list[CatalogItem], sort: str) -> list[CatalogItem]:
    if sort == "name_asc":
        return sorted(items, key=lambda x: x.name.lower())
    if sort == "name_desc":
        return sorted(items, key=lambda x: x.name.lower(), reverse=True)
    if sort == "price_asc":
        return sorted(items, key=lambda x: (x.price is None, x.price or 0))
    if sort == "price_desc":
        return sorted(items, key=lambda x: (x.price is None, -(x.price or 0)))
    if sort == "date_asc":
        return sorted(items, key=lambda x: x.updated_at)
    if sort == "date_desc":
        return sorted(items, key=lambda x: x.updated_at, reverse=True)
    return sorted(items, key=lambda x: x.name.lower())


# ---------------------------------------------------------------------------
# GET /prices/catalog
# ---------------------------------------------------------------------------

@router.get("/catalog", response_model=CatalogResponse)
async def list_catalog(
    tab: str = Query("all", pattern="^(all|works|materials)$"),
    search: Optional[str] = Query(None),
    sort: str = Query("name_asc", pattern="^(name_asc|name_desc|price_asc|price_desc|date_asc|date_desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    items: list[CatalogItem] = []
    search_term = search.strip() if search else None
    # Экранированный шаблон для ILIKE — фильтр выполняется в БД, а не в Python.
    pattern = f"%{_escape_like(search_term)}%" if search_term else None

    # Явный список колонок: тяжёлая колонка `embedding` (≈8-10 КБ JSON/строку)
    # НЕ грузится — она не нужна в списке. Это снимает мегабайты лишнего трафика
    # и памяти на каждый показ каталога.
    if tab in ("all", "works"):
        q = select(
            PriceWork.id, PriceWork.name, PriceWork.unit,
            PriceWork.min_price, PriceWork.prices, PriceWork.updated_at,
        )
        if pattern:
            q = q.where(PriceWork.name.ilike(pattern, escape="\\"))
        rows = (await db.execute(q)).all()
        items.extend(
            CatalogItem(
                id=r.id, kind="work", name=r.name, unit=r.unit,
                price=r.min_price, prices=r.prices, updated_at=r.updated_at,
            )
            for r in rows
        )

    if tab in ("all", "materials"):
        q = select(
            PriceMaterial.id, PriceMaterial.name, PriceMaterial.unit,
            PriceMaterial.price, PriceMaterial.updated_at,
        )
        if pattern:
            q = q.where(PriceMaterial.name.ilike(pattern, escape="\\"))
        rows = (await db.execute(q)).all()
        items.extend(
            CatalogItem(
                id=r.id, kind="material", name=r.name, unit=r.unit,
                price=r.price, prices=None, updated_at=r.updated_at,
            )
            for r in rows
        )

    # Сортировка/пагинация — в Python, но уже на «лёгких» строках без embedding.
    # Единый путь для all/works/materials исключает расхождение порядка между
    # вкладками (SQL lower() vs Python .lower() дают разный collation для кириллицы).
    items = _apply_sort(items, sort)
    total = len(items)
    start = (page - 1) * page_size
    page_items = items[start: start + page_size]

    return CatalogResponse(items=page_items, total=total)


# ---------------------------------------------------------------------------
# POST /prices/catalog/works
# ---------------------------------------------------------------------------

@router.post("/catalog/works", response_model=CatalogItem, status_code=status.HTTP_201_CREATED)
async def create_work(
    body: CreateWorkBody,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_manager_user),
):
    prices = body.prices or {}
    positive = [v for v in prices.values() if v and v > 0]
    min_price = min(positive) if positive else None

    embedding = await _generate_embedding_safe(body.name)

    work = PriceWork(
        name=body.name,
        unit=body.unit,
        prices=prices,
        min_price=min_price,
        embedding=embedding,
        updated_at=datetime.now(timezone.utc),
    )
    db.add(work)
    await db.commit()
    await db.refresh(work)
    await _reload_cache(db)
    logger.info("Created work", id=work.id, name=work.name)
    return _work_to_item(work)


# ---------------------------------------------------------------------------
# POST /prices/catalog/materials
# ---------------------------------------------------------------------------

@router.post("/catalog/materials", response_model=CatalogItem, status_code=status.HTTP_201_CREATED)
async def create_material(
    body: CreateMaterialBody,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_manager_user),
):
    embedding = await _generate_embedding_safe(body.name)

    material = PriceMaterial(
        name=body.name,
        unit=body.unit,
        price=body.price,
        embedding=embedding,
        updated_at=datetime.now(timezone.utc),
    )
    db.add(material)
    await db.commit()
    await db.refresh(material)
    await _reload_cache(db)
    logger.info("Created material", id=material.id, name=material.name)
    return _material_to_item(material)


# ---------------------------------------------------------------------------
# PUT /prices/catalog/works/{id}
# ---------------------------------------------------------------------------

@router.put("/catalog/works/{work_id}", response_model=CatalogItem)
async def update_work(
    work_id: int,
    body: UpdateWorkBody,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_manager_user),
):
    result = await db.execute(select(PriceWork).where(PriceWork.id == work_id))
    work = result.scalar_one_or_none()
    if not work:
        raise HTTPException(status_code=404, detail="Работа не найдена")

    name_changed = body.name is not None and body.name != work.name

    if body.name is not None:
        work.name = body.name
    if body.unit is not None:
        work.unit = body.unit
    if body.prices is not None:
        work.prices = body.prices
        positive = [v for v in body.prices.values() if v and v > 0]
        work.min_price = min(positive) if positive else None

    if name_changed:
        work.embedding = await _generate_embedding_safe(work.name)

    work.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(work)
    await _reload_cache(db)
    return _work_to_item(work)


# ---------------------------------------------------------------------------
# PUT /prices/catalog/materials/{id}
# ---------------------------------------------------------------------------

@router.put("/catalog/materials/{material_id}", response_model=CatalogItem)
async def update_material(
    material_id: int,
    body: UpdateMaterialBody,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_manager_user),
):
    result = await db.execute(select(PriceMaterial).where(PriceMaterial.id == material_id))
    material = result.scalar_one_or_none()
    if not material:
        raise HTTPException(status_code=404, detail="Материал не найден")

    name_changed = body.name is not None and body.name != material.name

    if body.name is not None:
        material.name = body.name
    if body.unit is not None:
        material.unit = body.unit
    if body.price is not None:
        material.price = body.price

    if name_changed:
        material.embedding = await _generate_embedding_safe(material.name)

    material.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(material)
    await _reload_cache(db)
    return _material_to_item(material)


# ---------------------------------------------------------------------------
# DELETE /prices/catalog/works/{id}
# ---------------------------------------------------------------------------

@router.delete("/catalog/works/{work_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_work(
    work_id: int,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_manager_user),
):
    result = await db.execute(select(PriceWork).where(PriceWork.id == work_id))
    work = result.scalar_one_or_none()
    if not work:
        raise HTTPException(status_code=404, detail="Работа не найдена")
    await db.delete(work)
    await db.commit()
    await _reload_cache(db)


# ---------------------------------------------------------------------------
# DELETE /prices/catalog/materials/{id}
# ---------------------------------------------------------------------------

@router.delete("/catalog/materials/{material_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_material(
    material_id: int,
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_manager_user),
):
    result = await db.execute(select(PriceMaterial).where(PriceMaterial.id == material_id))
    material = result.scalar_one_or_none()
    if not material:
        raise HTTPException(status_code=404, detail="Материал не найден")
    await db.delete(material)
    await db.commit()
    await _reload_cache(db)


# ---------------------------------------------------------------------------
# GET /prices/catalog/template
# ---------------------------------------------------------------------------

@router.get("/catalog/template")
async def download_template(
    type: str = Query(..., pattern="^(works|materials)$"),
    _user=Depends(get_current_user),
):
    wb = openpyxl.Workbook()
    ws = wb.active

    from openpyxl.styles import Font, PatternFill, Alignment
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="2563EB")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

    if type == "works":
        ws.title = "Работы"
        headers = ["Наименование", "Ед. изм.", "Подрядчик 1", "Подрядчик 2", "Подрядчик 3"]
        ws.column_dimensions["A"].width = 50
        ws.column_dimensions["B"].width = 12
        ws.column_dimensions["C"].width = 18
        ws.column_dimensions["D"].width = 18
        ws.column_dimensions["E"].width = 18
        # Example row
        ws.append(["Кладка кирпича", "м²", 1500, 1400, ""])
    else:
        ws.title = "Материалы"
        headers = ["Наименование", "Ед. изм.", "Цена"]
        ws.column_dimensions["A"].width = 50
        ws.column_dimensions["B"].width = 12
        ws.column_dimensions["C"].width = 18
        # Example row
        ws.append(["Кирпич керамический М100", "шт", 18.5])

    # Write headers in row 1 (push example to row 2)
    ws.insert_rows(1)
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
    ws.row_dimensions[1].height = 22

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f"template_{type}.xlsx"
    encoded = quote(filename)
    return Response(
        content=buf.read(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
    )


# ---------------------------------------------------------------------------
# GET /prices/catalog/export
# ---------------------------------------------------------------------------

@router.get("/catalog/export")
async def export_catalog(
    tab: str = Query("all", pattern="^(all|works|materials)$"),
    search: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    search_term = search.strip() if search else None
    pattern = f"%{_escape_like(search_term)}%" if search_term else None

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Каталог расценок"

    from openpyxl.styles import Font, PatternFill, Alignment
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="2563EB")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

    headers = ["Тип", "Наименование", "Ед. изм.", "Цена (мин.)", "Подрядчики / детали", "Дата обновления"]
    col_widths = [12, 50, 12, 15, 40, 22]
    for col, (h, w) in enumerate(zip(headers, col_widths), 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = w
    ws.row_dimensions[1].height = 22

    row = 2

    if tab in ("all", "works"):
        q = select(
            PriceWork.name, PriceWork.unit, PriceWork.min_price,
            PriceWork.prices, PriceWork.updated_at,
        )
        if pattern:
            q = q.where(PriceWork.name.ilike(pattern, escape="\\"))
        works = (await db.execute(q)).all()
        for w in works:
            contractors = "; ".join(f"{k}: {v}" for k, v in (w.prices or {}).items())
            ws.cell(row=row, column=1, value="Работа")
            ws.cell(row=row, column=2, value=w.name)
            ws.cell(row=row, column=3, value=w.unit or "")
            ws.cell(row=row, column=4, value=w.min_price)
            ws.cell(row=row, column=5, value=contractors)
            ws.cell(row=row, column=6, value=w.updated_at.strftime("%d.%m.%Y %H:%M") if w.updated_at else "")
            row += 1

    if tab in ("all", "materials"):
        q = select(
            PriceMaterial.name, PriceMaterial.unit,
            PriceMaterial.price, PriceMaterial.updated_at,
        )
        if pattern:
            q = q.where(PriceMaterial.name.ilike(pattern, escape="\\"))
        materials = (await db.execute(q)).all()
        for m in materials:
            ws.cell(row=row, column=1, value="Материал")
            ws.cell(row=row, column=2, value=m.name)
            ws.cell(row=row, column=3, value=m.unit or "")
            ws.cell(row=row, column=4, value=m.price)
            ws.cell(row=row, column=5, value="")
            ws.cell(row=row, column=6, value=m.updated_at.strftime("%d.%m.%Y %H:%M") if m.updated_at else "")
            row += 1

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = "catalog_export.xlsx"
    encoded = quote(filename)
    return Response(
        content=buf.read(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
    )
