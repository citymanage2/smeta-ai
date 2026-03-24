"""Optimization service — finds cheaper alternatives for smeta items via Claude."""
import json
from datetime import date, datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog

from app.models.estimate_item import EstimateItem
from app.models.task import Task
from app.services.claude_service import call_claude
from app.services import price_service
from app.services.snapshot_service import save_snapshot

logger = structlog.get_logger()

SYSTEM_OPTIMIZATION = (
    "Ты — опытный сметчик-оптимизатор строительных смет в России.\n"
    "Твоя задача — реально и обоснованно снизить себестоимость сметы.\n\n"
    "Правила:\n"
    "1. Предлагай только реальные аналоги, доступные в Екатеринбурге\n"
    "2. Снижение должно быть обоснованным — указывай источник цены\n"
    "3. Не предлагай замены, которые ухудшают качество или нарушают нормативы\n"
    "4. Для работ — проверяй только нормативную базу ГЭСН-2017/ФСНБ-2022 и ФЕР Свердловской обл.\n"
    "5. Возвращай ТОЛЬКО валидный JSON-массив без пояснений\n"
    "6. Поле saving_reason — конкретным и убедительным (1-2 предложения)\n"
    "7. confidence: high = уверен в цене, medium = приблизительно, low = под вопросом\n"
    "8. Если дешевле найти не удалось — НЕ включай позицию в ответ\n"
    "IMPORTANT: Return ONLY a raw JSON array. First char [, last char ]."
)

OPTIMIZATION_BATCH = 10  # items per Claude call


def _compute_item_cost(item: EstimateItem) -> float:
    qty = item.quantity or 0
    price = (item.work_price or 0) + (item.mat_price or 0)
    return qty * price


async def get_optimization_plan(
    task_id: str,
    db: AsyncSession,
    optimize_materials: bool = True,
    optimize_works: bool = True,
    optimize_other: bool = False,
    custom_prompt: str | None = None,
) -> dict:
    """Return a plan preview without executing changes."""
    items_result = await db.execute(
        select(EstimateItem)
        .where(EstimateItem.task_id == task_id)
        .order_by(EstimateItem.position)
    )
    items = items_result.scalars().all()
    if not items:
        return {
            "plan": "Нет позиций для оптимизации. Убедитесь, что смета рассчитана.",
            "top_cost_items": [],
            "potential_savings_pct": 0,
        }

    # Filter items to optimize
    target_items = _filter_items(items, optimize_materials, optimize_works, optimize_other)
    total_cost = sum(_compute_item_cost(i) for i in items)
    target_cost = sum(_compute_item_cost(i) for i in target_items)

    # Top items by cost
    sorted_items = sorted(target_items, key=_compute_item_cost, reverse=True)
    top_items = [
        {
            "id": i.id,
            "name": i.name,
            "type": i.type,
            "cost": round(_compute_item_cost(i), 2),
            "pct": round(_compute_item_cost(i) / total_cost * 100, 1) if total_cost else 0,
        }
        for i in sorted_items[:10]
    ]

    mat_count = sum(1 for i in target_items if i.type == "Материал")
    work_count = sum(1 for i in target_items if i.type == "Работа")

    plan_lines = []
    if mat_count:
        mat_cost = sum(_compute_item_cost(i) for i in target_items if i.type == "Материал")
        plan_lines.append(f"• {mat_count} позиций материалов на сумму {mat_cost:,.0f} ₽")
    if work_count:
        work_cost = sum(_compute_item_cost(i) for i in target_items if i.type == "Работа")
        plan_lines.append(f"• {work_count} позиций работ на сумму {work_cost:,.0f} ₽")
    if custom_prompt:
        plan_lines.append(f"• Дополнительные требования: {custom_prompt}")

    plan_text = "Будет пересчитано:\n" + "\n".join(plan_lines) if plan_lines else "Нет позиций для пересчёта."

    # Rough estimate: materials ~15-20% savings potential, works ~5-10%
    potential_pct = 0.0
    if target_cost > 0:
        mat_savings = sum(_compute_item_cost(i) for i in target_items if i.type == "Материал") * 0.15
        work_savings = sum(_compute_item_cost(i) for i in target_items if i.type == "Работа") * 0.07
        potential_pct = round((mat_savings + work_savings) / total_cost * 100, 1) if total_cost else 0

    return {
        "plan": plan_text,
        "top_cost_items": top_items,
        "potential_savings_pct": potential_pct,
        "items_count": len(target_items),
        "total_cost": round(total_cost, 2),
    }


async def execute_optimization(
    task_id: str,
    db: AsyncSession,
    optimize_materials: bool = True,
    optimize_works: bool = True,
    optimize_other: bool = False,
    custom_prompt: str | None = None,
) -> dict:
    """Execute optimization: create snapshot, call Claude, update items."""
    items_result = await db.execute(
        select(EstimateItem)
        .where(EstimateItem.task_id == task_id)
        .order_by(EstimateItem.position)
    )
    items = items_result.scalars().all()
    if not items:
        raise ValueError("Нет позиций для оптимизации")

    # Save snapshot BEFORE making any changes
    await save_snapshot(
        task_id=task_id,
        db=db,
        change_description="Перед оптимизацией сметы",
        change_type="before_optimization",
        created_by="auto",
    )

    target_items = _filter_items(items, optimize_materials, optimize_works, optimize_other)

    # Sort by cost desc — focus on expensive items first
    sorted_targets = sorted(target_items, key=_compute_item_cost, reverse=True)

    # Load price context
    await price_service.load_cache(db)
    works_lines = [f"- {w['name']} | {w.get('unit','')} | {w.get('min_price','')} руб."
                   for w in price_service._works_cache[:200]]
    mats_lines = [f"- {m['name']} | {m.get('unit','')} | {m.get('price','')} руб."
                  for m in price_service._materials_cache[:200]]
    price_context = (
        "Прайс работ:\n" + "\n".join(works_lines[:100]) + "\n\n" +
        "Прайс материалов:\n" + "\n".join(mats_lines[:100])
    )
    current_date = date.today().strftime("%d.%m.%Y")

    total_saving = 0.0
    recommendations: list[dict] = []

    # Process in batches
    for batch_start in range(0, len(sorted_targets), OPTIMIZATION_BATCH):
        batch = sorted_targets[batch_start: batch_start + OPTIMIZATION_BATCH]
        batch_recs = await _optimize_batch(batch, price_context, current_date, custom_prompt)
        recommendations.extend(batch_recs)

    # Apply recommendations
    recs_by_id = {r["item_id"]: r for r in recommendations}
    for item in items:
        rec = recs_by_id.get(item.id)
        if not rec:
            continue
        orig_price = (item.work_price or 0) + (item.mat_price or 0)
        new_price = float(rec.get("recommended_price", orig_price))
        saving = float(rec.get("saving_amount", orig_price - new_price))
        if saving <= 0:
            continue
        total_saving += saving * (item.quantity or 1)

        # Update in place
        if item.type == "Работа":
            item.work_price = new_price
        else:
            item.mat_price = new_price

        old_notes = item.notes or ""
        item.notes = f"[ОПТИМИЗИРОВАНО] {rec.get('saving_reason', '')} | {old_notes}".strip(" |")
        item.updated_at = datetime.now(timezone.utc)

    # Update task estimate_status
    task_result = await db.execute(select(Task).where(Task.id == task_id))
    task = task_result.scalar_one_or_none()
    if task:
        task.estimate_status = "optimized"
        task.estimate_status_updated_at = datetime.now(timezone.utc)
        task.estimate_status_updated_by = "auto"

    await db.commit()

    total_cost = sum(_compute_item_cost(i) for i in items)
    logger.info(
        "Optimization complete",
        task_id=task_id,
        recommendations=len(recommendations),
        total_saving=total_saving,
    )
    return {
        "recommendations_count": len(recommendations),
        "total_saving": round(total_saving, 2),
        "saving_pct": round(total_saving / total_cost * 100, 1) if total_cost else 0,
    }


def _filter_items(
    items: list[EstimateItem],
    optimize_materials: bool,
    optimize_works: bool,
    optimize_other: bool,
) -> list[EstimateItem]:
    result = []
    for item in items:
        if item.type == "Материал" and optimize_materials:
            result.append(item)
        elif item.type == "Работа" and optimize_works:
            result.append(item)
        elif item.type not in ("Материал", "Работа") and optimize_other:
            result.append(item)
    return result


async def _optimize_batch(
    items: list[EstimateItem],
    price_context: str,
    current_date: str,
    custom_prompt: str | None,
) -> list[dict]:
    """Ask Claude to find cheaper alternatives for a batch of items."""
    items_json = json.dumps(
        [
            {
                "item_id": i.id,
                "type": i.type,
                "name": i.name,
                "unit": i.unit,
                "quantity": i.quantity,
                "current_price": (i.work_price or 0) + (i.mat_price or 0),
            }
            for i in items
        ],
        ensure_ascii=False,
        indent=2,
    )

    extra = f"\n\nДополнительные требования: {custom_prompt}" if custom_prompt else ""
    prompt = (
        f"{price_context}\n\n"
        f"Текущая дата: {current_date}\n"
        f"Регион: Екатеринбург, Свердловская область\n\n"
        f"Список позиций для оптимизации:\n{items_json}\n\n"
        "Для каждой позиции, где можно снизить цену, верни объект в JSON-массиве:\n"
        '{"item_id": "...", "original_price": ..., "recommended_price": ..., '
        '"saving_amount": ..., "saving_reason": "...", "confidence": "high|medium|low", '
        '"source": "price_list|web_search"}\n\n'
        "Если для позиции дешевле не нашлось — не включай её.\n"
        "Возвращай ТОЛЬКО JSON-массив.[ ... ]" + extra
    )

    try:
        response = await call_claude(
            [{"role": "user", "content": prompt}],
            system_prompt=SYSTEM_OPTIMIZATION,
            use_web_search=True,
        )
        # parse array
        response = response.strip()
        if response.startswith("["):
            data = json.loads(response)
        else:
            # try to find array within response
            start = response.find("[")
            end = response.rfind("]")
            if start != -1 and end != -1:
                data = json.loads(response[start:end + 1])
            else:
                data = []
        return [r for r in data if isinstance(r, dict) and "item_id" in r]
    except Exception as e:
        logger.error("Optimization batch failed", error=str(e))
        return []
