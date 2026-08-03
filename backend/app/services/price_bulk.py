"""Пакетная запись позиций сметы в прайс — «Добавить в прайс».

Фаза 10 плана `plans/2026-08-02-edinyy-redaktor-tablic.md`.

Прайс общий на всех и участвует в расчёте будущих смет, поэтому запись сюда —
не безобидное действие. Правила, которые это ограничивают:

- работы попадают к псевдо-подрядчику «Из смет», а не в прайс подрядчика;
- единицы измерения приводятся к одному написанию, а цена за «100 м2»
  пересчитывается в цену за «м2»;
- позиция без имени или без внятной цены не пишется вовсе, а попадает в сводку
  «пропущено» — молча терять данные нельзя;
- цена работы, добавленная из сметы, имеет приоритет в расчёте
  (см. `utils/price_min.py`) — решение пользователя.
"""
import asyncio
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.price import PriceMaterial, PriceWork
from app.services import price_service
from app.services.embedding_service import (
    EmbeddingUnavailableError,
    generate_embedding,
    normalize_name,
)
from app.utils.price_min import ESTIMATE_CONTRACTOR, compute_min_price
from app.utils.unit_normalizer import unit_price_factor

logger = structlog.get_logger()

# Потолок на один запрос: смета на 2000 строк целиком в прайс не отправляется —
# это не пакетное добавление, а замусоривание общего справочника.
MAX_ITEMS = 500

SKIP_NO_NAME = "без наименования"
SKIP_NO_PRICE = "без цены"
SKIP_NOT_PRICEABLE = "не работа и не материал"


async def _generate_embedding_safe(name: str) -> Optional[list]:
    """Вектор для поиска по смыслу; None — если модель недоступна.

    Позиция без вектора всё равно найдётся точным совпадением названия, поэтому
    отсутствие модели не повод отказывать в записи.
    """
    try:
        return await asyncio.to_thread(
            generate_embedding, normalize_name(name), "search_document",
        )
    except EmbeddingUnavailableError:
        return None


def _prepare(items: list) -> "tuple[dict, dict, dict]":
    """Разобрать присланное: (работы, материалы, причины пропуска).

    Работы и материалы возвращаются словарями «нормализованное имя → позиция»:
    одна и та же работа встречается в смете несколько раз, а в прайсе ей место
    одно. Побеждает последняя — как и при повторном добавлении.
    """
    works: dict = {}
    materials: dict = {}
    skipped: dict = {}

    for raw in items:
        item = raw if isinstance(raw, dict) else {}
        kind = str(item.get("kind") or "").strip().lower()
        name = str(item.get("name") or "").strip()

        if not name:
            skipped[SKIP_NO_NAME] = skipped.get(SKIP_NO_NAME, 0) + 1
            continue
        if kind not in ("work", "material"):
            skipped[SKIP_NOT_PRICEABLE] = skipped.get(SKIP_NOT_PRICEABLE, 0) + 1
            continue

        try:
            price = float(item.get("price"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            price = 0.0
        if price <= 0:
            skipped[SKIP_NO_PRICE] = skipped.get(SKIP_NO_PRICE, 0) + 1
            continue

        # Единица приводится к одному написанию, а цена за «100 м2» — к цене за «м2».
        unit, factor = unit_price_factor(item.get("unit"))
        prepared = {
            "name": name,
            "unit": unit,
            "price": round(price / factor, 2),
        }
        target = works if kind == "work" else materials
        target[normalize_name(name)] = prepared

    return works, materials, skipped


async def add_items(db: AsyncSession, items: list) -> dict:
    """Записать позиции в прайс. Возвращает сводку «добавлено / обновлено / пропущено»."""
    works, materials, skipped_reasons = _prepare(items)
    added = 0
    updated = 0
    now = datetime.now(timezone.utc)

    # Существующие позиции ищем по нормализованному имени — так же, как их ищет
    # загрузка прайса файлом. Тяжёлую колонку `embedding` не читаем: она здесь
    # не нужна, а весит по 8–10 КБ на строку.
    if works:
        rows = (await db.execute(
            select(PriceWork.id, PriceWork.name, PriceWork.unit, PriceWork.prices)
        )).all()
        existing = {normalize_name(row.name): row for row in rows}

        for key, item in works.items():
            found = existing.get(key)
            if found is None:
                db.add(PriceWork(
                    name=item["name"],
                    unit=item["unit"],
                    prices={ESTIMATE_CONTRACTOR: item["price"]},
                    min_price=item["price"],
                    embedding=await _generate_embedding_safe(item["name"]),
                    updated_at=now,
                ))
                added += 1
                continue

            # Цены подрядчиков не трогаем — переписывается только цена из смет.
            merged = dict(found.prices or {})
            merged[ESTIMATE_CONTRACTOR] = item["price"]
            await db.execute(
                update(PriceWork)
                .where(PriceWork.id == found.id)
                .values(
                    prices=merged,
                    min_price=compute_min_price(merged),
                    # Единицу существующей позиции не переписываем: цена
                    # подрядчика привязана именно к ней, и подмена «м2» на «м3»
                    # из чужой сметы молча исказила бы его прайс.
                    unit=found.unit or item["unit"],
                    updated_at=now,
                )
            )
            updated += 1

    if materials:
        rows = (await db.execute(
            select(PriceMaterial.id, PriceMaterial.name, PriceMaterial.unit)
        )).all()
        existing = {normalize_name(row.name): row for row in rows}

        for key, item in materials.items():
            found = existing.get(key)
            if found is None:
                db.add(PriceMaterial(
                    name=item["name"],
                    unit=item["unit"],
                    price=item["price"],
                    embedding=await _generate_embedding_safe(item["name"]),
                    updated_at=now,
                ))
                added += 1
                continue

            await db.execute(
                update(PriceMaterial)
                .where(PriceMaterial.id == found.id)
                .values(
                    price=item["price"],
                    # Единица прежняя — см. выше: она задаёт, за что эта цена.
                    unit=found.unit or item["unit"],
                    updated_at=now,
                )
            )
            updated += 1

    await db.commit()

    if added or updated:
        # Расчёт сметы читает прайс из памяти. Без перезагрузки кэша добавленная
        # позиция участвовала бы в расчёте только после перезапуска сервера.
        await price_service.load_cache(db)

    skipped = sum(skipped_reasons.values())
    logger.info("price_bulk_add", added=added, updated=updated, skipped=skipped)
    return {
        "added": added,
        "updated": updated,
        "skipped": skipped,
        "skipped_reasons": skipped_reasons,
    }
