"""Analogue service — finds cheaper material analogues via web search."""
import json
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog

from app.models.estimate_item import EstimateItem
from app.models.task import Task
from app.services.claude_service import call_claude
from app.services.snapshot_service import save_snapshot

logger = structlog.get_logger()

SYSTEM_ANALOGUES = (
    "Ты — эксперт по строительным материалам и закупкам в Екатеринбурге.\n"
    "Твоя задача — найти более дешёвые аналоги конкретного материала.\n\n"
    "Правила:\n"
    "1. Предлагай только реально доступные материалы в Екатеринбурге (СТД Петрович, Мегастрой, Леруа и др.)\n"
    "2. Аналог должен соответствовать техническим характеристикам оригинала (ГОСТ, класс, марка)\n"
    "3. Указывай реального поставщика и актуальную цену\n"
    "4. Возвращай ТОЛЬКО валидный JSON-объект. Первый символ {, последний }.\n"
)


async def find_analogues(
    task_id: str,
    item_id: str,
    db: AsyncSession,
) -> dict:
    """Find cheaper analogues for a specific estimate item."""
    item_result = await db.execute(
        select(EstimateItem).where(
            EstimateItem.id == item_id,
            EstimateItem.task_id == task_id,
        )
    )
    item = item_result.scalar_one_or_none()
    if not item:
        raise ValueError(f"Item {item_id} not found in task {task_id}")

    current_price = (item.work_price or 0) + (item.mat_price or 0)

    prompt = (
        f"Найди 3 более дешёвых аналога для строительного материала:\n"
        f"Наименование: {item.name}\n"
        f"Единица измерения: {item.unit or 'шт'}\n"
        f"Текущая цена: {current_price} руб/{item.unit or 'шт'}\n\n"
        "Регион: Екатеринбург, Свердловская область\n"
        "Период: актуальные цены 2024-2025\n\n"
        "Верни JSON-объект:\n"
        "{\n"
        '  "item_id": "' + item_id + '",\n'
        '  "original": {"name": "...", "price": ..., "unit": "..."},\n'
        '  "analogues": [\n'
        '    {\n'
        '      "name": "...",\n'
        '      "price": ...,\n'
        '      "unit": "...",\n'
        '      "supplier": "...",\n'
        '      "saving_pct": ...,\n'
        '      "note": "соответствие характеристикам",\n'
        '      "source_url": "..."\n'
        '    }\n'
        '  ]\n'
        "}\n"
        "Если аналогов не найдено — верни пустой массив analogues.\n"
        "ТОЛЬКО JSON, без пояснений."
    )

    try:
        response = await call_claude(
            [{"role": "user", "content": prompt}],
            system_prompt=SYSTEM_ANALOGUES,
            use_web_search=True,
        )
        response = response.strip()
        start = response.find("{")
        end = response.rfind("}")
        if start != -1 and end != -1:
            data = json.loads(response[start:end + 1])
        else:
            data = {"item_id": item_id, "original": {}, "analogues": []}

        # Ensure original is populated
        data.setdefault("original", {})
        data["original"].update({
            "name": item.name,
            "price": current_price,
            "unit": item.unit or "",
        })
        data["item_id"] = item_id
        return data

    except Exception as e:
        logger.error("Analogue search failed", item_id=item_id, error=str(e))
        return {
            "item_id": item_id,
            "original": {"name": item.name, "price": current_price, "unit": item.unit or ""},
            "analogues": [],
        }


async def apply_analogue(
    task_id: str,
    item_id: str,
    analogue_name: str,
    analogue_price: float,
    analogue_note: str,
    supplier: str,
    db: AsyncSession,
) -> dict:
    """Apply an analogue to an estimate item. Saves snapshot first."""
    item_result = await db.execute(
        select(EstimateItem).where(
            EstimateItem.id == item_id,
            EstimateItem.task_id == task_id,
        )
    )
    item = item_result.scalar_one_or_none()
    if not item:
        raise ValueError(f"Item {item_id} not found in task {task_id}")

    # Save snapshot before modification
    await save_snapshot(
        task_id=task_id,
        db=db,
        change_description=f"Аналог для '{item.name}': {analogue_name}",
        change_type="analogue_applied",
        created_by="user",
    )

    # Store original info in extra if this is the first replacement
    if not item.is_analogue:
        item.extra = {
            **(item.extra or {}),
            "original_name": item.name,
            "original_price": (item.work_price or 0) + (item.mat_price or 0),
            "original_unit": item.unit,
        }

    # Update item
    original_id = item.original_item_id or item.id  # track chain
    if item.type == "Работа":
        item.work_price = analogue_price
    else:
        item.mat_price = analogue_price

    item.name = analogue_name
    item.is_analogue = True
    item.analogue_note = f"{analogue_note} | Поставщик: {supplier}" if supplier else analogue_note
    item.original_item_id = original_id if original_id != item.id else None
    item.updated_at = datetime.now(timezone.utc)

    # Recalculate totals in extra
    qty = item.quantity or 0
    item.extra = {**(item.extra or {}), "supplier": supplier}

    await db.commit()
    await db.refresh(item)

    # Return updated summary
    return {
        "id": item.id,
        "name": item.name,
        "price": analogue_price,
        "unit": item.unit,
        "quantity": item.quantity,
        "total": round(analogue_price * qty, 2),
        "is_analogue": True,
        "analogue_note": item.analogue_note,
        "original_name": (item.extra or {}).get("original_name"),
        "original_price": (item.extra or {}).get("original_price"),
    }


async def revert_analogue(
    task_id: str,
    item_id: str,
    db: AsyncSession,
) -> dict:
    """Revert analogue back to original item data."""
    item_result = await db.execute(
        select(EstimateItem).where(
            EstimateItem.id == item_id,
            EstimateItem.task_id == task_id,
        )
    )
    item = item_result.scalar_one_or_none()
    if not item:
        raise ValueError(f"Item {item_id} not found")

    if not item.is_analogue:
        raise ValueError("This item is not an analogue — nothing to revert")

    extra = item.extra or {}
    orig_name = extra.get("original_name")
    orig_price = extra.get("original_price", 0)

    if not orig_name:
        raise ValueError("Original item data not stored — cannot revert")

    # Save snapshot before revert
    await save_snapshot(
        task_id=task_id,
        db=db,
        change_description=f"Откат аналога '{item.name}' → '{orig_name}'",
        change_type="analogue_reverted",
        created_by="user",
    )

    item.name = orig_name
    if item.type == "Работа":
        item.work_price = orig_price
    else:
        item.mat_price = orig_price
    item.is_analogue = False
    item.analogue_note = None
    item.original_item_id = None
    item.extra = {k: v for k, v in extra.items()
                  if k not in ("original_name", "original_price", "original_unit", "supplier")}
    item.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(item)

    return {
        "id": item.id,
        "name": item.name,
        "price": orig_price,
        "is_analogue": False,
    }
