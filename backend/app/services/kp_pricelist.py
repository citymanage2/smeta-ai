"""Цены из КП в прайс — при завершении запроса (план 2026-09-14-zapros-kp.md, фаза 7).

Критерии спецификации 23–28. Решение пользователя 14.09.2026: подтверждённые
цены из КП пишутся в прайс напрямую при завершении запроса; у работы ключ
«КП: <поставщик>», и в расчёте сметы он важнее «Из смет» (`utils/price_min.py`).

Правила:

* **Запись — только через `price_bulk.add_items`.** Единицы (правило №8), дата
  «Цена от» (№15) и ключ «та же позиция» (№19) одни на все пути записи прайса.
  Цена приводится к виду прайса только `kp_pricing` (без НДС, в единице позиции).
* **Наименование и единица — позиции запроса**, а не КП: так цена найдётся в
  следующей смете (критерий 24).
* **Материал** — итоговая цена позиции (`kp_pricing.best_for_item`: выбранное КП,
  иначе минимум) перезаписывает цену материала.
* **Работа** — каждая подтверждённая приведённая цена каждого КП пишется
  отдельным подрядчиком «КП: <поставщик>»; «Из смет» и прочие ключи целы. У двух
  КП одного поставщика по одной позиции ключ один — берётся меньшая цена.
  Цена «включает материалы» в прайс работ **не пишется** (критерий 25).
* **Сводка не молчит:** всё, что не записано, названо причиной.
* **Отдельная транзакция после завершения.** Векторы новых позиций считаются
  медленно, а завершение не должно ждать их и не должно откатываться из-за
  сбоя прайса (критерий 28): завершение коммитится первым, запись — следом,
  сбой → `pricelist_status = failed` и кнопка «Записать в прайс ещё раз».
* **Повторная запись снимает свои прежние ключи.** Запрос вернули в работу,
  переименовали поставщика, завершили снова — ключ «КП: Старое имя» с прежней
  ценой иначе остался бы в прайсе и мог стать минимумом. Ключ, записанный этим
  запросом раньше (`pricelist_summary.written`) и не записанный сейчас,
  удаляется, **только если его значение с тех пор не изменилось**: иначе его
  переписал другой запрос, и это уже не наша цена. И не удаляется, если тот же
  ключ с тем же значением записал другой завершённый запрос: цена ещё его. Цена материала не
  удаляется: у позиции прайса одна цена, прежней мы не знаем.
* **«Замок» на строке запроса** (`kp_offers._lock` со статусом `done`): два
  повтора и «Вернуть в работу» не проскакивают мимо записи.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kp_request import CATEGORY_WORK, STATUS_DONE, KpRequest, KpRequestItem
from app.models.price import PriceWork
from app.services import kp_pricing, price_bulk, price_service
from app.services.embedding_service import normalize_name
from app.utils.price_change import MONEY_EPS, prices_changed
from app.utils.price_min import compute_min_price, kp_contractor

logger = structlog.get_logger()

PRICELIST_DONE = "done"
PRICELIST_FAILED = "failed"

SKIP_NO_PRICE = "нет подтверждённой цены из КП"
SKIP_UNIT_INCOMPATIBLE = "единица КП не сводится с позицией"
SKIP_INCLUDES_MATERIALS = "цена включает материалы"
SKIP_NO_SUPPLIER = "не указан поставщик"

_ERROR_LEN = 500


def _bump(skipped: dict, reason: str) -> None:
    skipped[reason] = skipped.get(reason, 0) + 1


async def _load_request(db: AsyncSession, request_id: str) -> KpRequest:
    return (await db.execute(
        select(KpRequest).where(KpRequest.id == request_id)
        .execution_options(populate_existing=True)
    )).scalar_one()


def _material_entry(item: KpRequestItem, offers: list, prices: list, skipped: dict) -> Optional[dict]:
    best = kp_pricing.best_for_item(item, offers, prices)
    if best is None:
        _bump(skipped, _no_price_reason(item, offers, prices))
        return None
    return {"kind": "material", "name": item.name, "unit": item.unit, "price": best["price"]}


def _no_price_reason(item: KpRequestItem, offers: list, prices: list) -> str:
    """Почему у позиции нет цены: единица не сводится или цены просто нет."""
    by_offer = {str(p.offer_id): p for p in prices}
    for offer in offers:
        row = by_offer.get(str(offer.id))
        if row is None or not row.confirmed:
            continue
        _value, _status, reason = kp_pricing.normalized(
            row.price, row.unit, item.unit, offer.vat_mode, offer.vat_rate,
        )
        if reason:
            return SKIP_UNIT_INCOMPATIBLE
    return SKIP_NO_PRICE


def _work_entries(item: KpRequestItem, offers: list, prices: list, skipped: dict) -> list[dict]:
    by_offer = {str(p.offer_id): p for p in prices}
    per_contractor: dict[str, float] = {}
    confirmed_any = False
    for offer in offers:
        row = by_offer.get(str(offer.id))
        if row is None or not row.confirmed:
            continue
        confirmed_any = True
        value, _status, reason = kp_pricing.normalized(
            row.price, row.unit, item.unit, offer.vat_mode, offer.vat_rate,
        )
        if value is None:
            _bump(skipped, SKIP_UNIT_INCOMPATIBLE if reason else SKIP_NO_PRICE)
            continue
        if kp_pricing.effective_includes_materials(row, offer):
            _bump(skipped, SKIP_INCLUDES_MATERIALS)
            continue
        supplier = (offer.supplier_name or "").strip()
        if not supplier:
            _bump(skipped, SKIP_NO_SUPPLIER)
            continue
        key = kp_contractor(supplier)
        if key not in per_contractor or value < per_contractor[key]:
            per_contractor[key] = value
    if not confirmed_any:
        _bump(skipped, SKIP_NO_PRICE)
    return [
        {"kind": "work", "name": item.name, "unit": item.unit, "price": price, "contractor": key}
        for key, price in per_contractor.items()
    ]


def _same_value(a: Any, b: Any) -> bool:
    try:
        return abs(float(a) - float(b)) <= MONEY_EPS
    except (TypeError, ValueError):
        return False


async def _owned_by_others(db: AsyncSession, request_id: str) -> dict:
    """(имя, подрядчик) → значения, записанные другими завершёнными запросами."""
    summaries = (await db.execute(
        select(KpRequest.pricelist_summary).where(
            KpRequest.id != request_id,
            KpRequest.status == STATUS_DONE,
            KpRequest.deleted_at.is_(None),
            KpRequest.pricelist_summary.is_not(None),
        )
    )).scalars().all()
    owned: dict[tuple, list] = {}
    for summary in summaries:
        written = summary.get("written") if isinstance(summary, dict) else None
        for w in written or []:
            if isinstance(w, dict) and w.get("kind") == "work" and w.get("contractor"):
                owned.setdefault((w.get("name_key"), w["contractor"]), []).append(w.get("value"))
    return owned


async def _retire_stale(
    db: AsyncSession, request_id: str, previous: list, current: list, now: datetime,
) -> int:
    """Снять ключи работ, записанные этим запросом раньше и не записанные сейчас,
    если их значение с тех пор не менялось и тот же ключ с тем же значением не
    записал другой завершённый запрос. Возвращает число снятых ключей."""
    fresh = {(w["name_key"], w["contractor"]) for w in current if w.get("kind") == "work"}
    stale: dict[str, list[dict]] = {}
    for w in previous or []:
        if not isinstance(w, dict) or w.get("kind") != "work" or not w.get("contractor"):
            continue
        if (w.get("name_key"), w["contractor"]) in fresh:
            continue
        stale.setdefault(str(w.get("name_key")), []).append(w)
    if not stale:
        return 0

    others = await _owned_by_others(db, request_id)
    rows = (await db.execute(
        select(PriceWork.id, PriceWork.name, PriceWork.unit, PriceWork.prices)
    )).all()
    retired = 0
    for row in rows:
        entries = stale.get(normalize_name(row.name))
        if not entries:
            continue
        prices = dict(row.prices or {})
        changed = False
        for w in entries:
            if w["contractor"] not in prices:
                continue
            if not _same_value(prices[w["contractor"]], w.get("value")):
                continue  # ключ переписали — это уже не наша цена
            shared = others.get((w.get("name_key"), w["contractor"]), [])
            if any(_same_value(prices[w["contractor"]], v) for v in shared):
                continue  # та же цена другого завершённого запроса — она ещё чья-то
            del prices[w["contractor"]]
            changed = True
            retired += 1
        if not changed:
            continue
        values: dict[str, Any] = {"prices": prices, "min_price": compute_min_price(prices)}
        if prices_changed(row.prices, prices, row.unit, row.unit):
            values["updated_at"] = now
        await db.execute(update(PriceWork).where(PriceWork.id == row.id).values(**values))
    return retired


async def write(db: AsyncSession, request_id: str) -> KpRequest:
    """Записать цены завершённого запроса в прайс одной транзакцией.

    Бросает 409, если запрос не завершён; прочие ошибки — после отката.
    """
    from app.services import kp_offers  # kp_offers опирается на kp_requests, как и мы

    rid = str(request_id)
    try:
        await kp_offers._lock(db, rid, (STATUS_DONE,))
        request = await _load_request(db, rid)
        items = list((await db.execute(
            select(KpRequestItem).where(KpRequestItem.request_id == rid)
            .order_by(KpRequestItem.position)
        )).scalars().all())
        offers = await kp_offers.load_offers(db, rid)
        prices = await kp_offers.load_prices(db, offers)
        by_item: dict[str, list] = {}
        for p in prices:
            by_item.setdefault(str(p.item_id), []).append(p)

        skipped: dict[str, int] = {}
        entries: list[dict] = []
        for item in items:
            item_prices = by_item.get(str(item.id), [])
            if request.category == CATEGORY_WORK:
                entries.extend(_work_entries(item, offers, item_prices, skipped))
            else:
                entry = _material_entry(item, offers, item_prices, skipped)
                if entry:
                    entries.append(entry)

        result = {"added": 0, "updated": 0, "skipped_reasons": {}, "written_prices": []}
        if entries:
            result = await price_bulk.add_items(db, entries, commit=False, with_written=True)
        for reason, n in (result.get("skipped_reasons") or {}).items():
            skipped[reason] = skipped.get(reason, 0) + n

        now = datetime.now(timezone.utc)
        written = result.get("written_prices") or []
        previous = (request.pricelist_summary or {}).get("written") or []
        retired = await _retire_stale(db, rid, previous, written, now)

        summary = {
            "added": int(result.get("added") or 0),
            "updated": int(result.get("updated") or 0),
            "skipped": skipped,
            "retired": retired,
            "written": written,
        }
        await db.execute(
            update(KpRequest).where(KpRequest.id == rid).values(
                pricelist_status=PRICELIST_DONE, pricelist_summary=summary,
                pricelist_error=None, pricelist_written_at=now,
            ).execution_options(synchronize_session=False)
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    if summary["added"] or summary["updated"] or retired:
        try:
            # Расчёт сметы читает прайс из памяти (как в `price_bulk.add_items`).
            await price_service.load_cache(db)
        except Exception as exc:  # запись уже в базе — кэш догонит при следующей загрузке
            logger.warning("kp_pricelist_cache_reload_failed", request_id=rid, error=str(exc))

    logger.info("kp_pricelist_written", request_id=rid, added=summary["added"],
                updated=summary["updated"], skipped=sum(skipped.values()), retired=retired)
    return await _load_request(db, rid)


async def write_safe(db: AsyncSession, request_id: str) -> KpRequest:
    """`write`, который не бросает: сбой записи не отменяет завершение (критерий 28).

    Запрос уже не завершён (коллега вернул в работу) — ничего не пишем и не
    отмечаем сбоем. Иначе ошибка → `pricelist_status = failed` с текстом.
    Возвращает запрос, перечитанный из базы.
    """
    rid = str(request_id)
    try:
        return await write(db, rid)
    except HTTPException as exc:
        if exc.status_code == 409:
            logger.info("kp_pricelist_skipped_not_done", request_id=rid)
            return await _load_request(db, rid)
        raise  # 404: запрос удалён окончательно — отмечать сбой некуда
    except Exception as exc:
        error = str(exc) or type(exc).__name__
    logger.error("kp_pricelist_failed", request_id=rid, error=error)
    try:
        await db.execute(
            update(KpRequest)
            .where(KpRequest.id == rid, KpRequest.status == STATUS_DONE)
            .values(pricelist_status=PRICELIST_FAILED, pricelist_error=error[:_ERROR_LEN])
            .execution_options(synchronize_session=False)
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.error("kp_pricelist_mark_failed_error", request_id=rid, error=str(exc))
    return await _load_request(db, rid)
