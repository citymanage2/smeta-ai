"""Цены из КП в оптимизацию: предпросмотр и применение.

План: plans/2026-09-14-zapros-kp.md, фаза 8 (проблемы 8, 28–31, 35; критерии 30–37).

* **Цена позиции** — `kp_pricing.best_for_item` (выбранное КП, иначе минимум
  подтверждённых), приведённая к единице **строки**: позиция запроса могла быть
  в «кг», а строка оптимизации — в «т». Несводимая единица цену не даёт.
* **Сопоставление** позиции со строками версии — три шага, первый сработавший
  побеждает: `row_id` из `source_row_ids` (только если запрос поставлен с этой
  же оптимизации — у другой задачи те же id значат другое — и наименование
  строки то же: строку, заменённую аналогом, цена из КП не получает) → № исходной сметы +
  наименование → тип + наименование + единица. Лист позиции, если известен,
  сужает шаги 2 и 3. Тип строки обязан совпасть с типом позиции на каждом шаге:
  цену работы в поле материала класть нельзя. Все строки одного наименования на
  шаге получают цену; разные наименования или листы — «неоднозначно», само не
  берётся — выбирает человек.
* **Несколько запросов на строку** — минимальная из цен по каждому запросу.
* **Предпросмотр ничего не пишет.** Применение пересчитывает план в своей
  транзакции и сверяет `preview_hash`: изменилось что-то между предпросмотром и
  нажатием — 409, человек смотрит заново.
* **Применение — одна транзакция:** заявка `rev` исходной версии → пересчёт и
  сверка → клон «Цены из КП» → цены в клон → история `kp_prices` → отметка
  запросов. Любой отказ откатывает всё: версии-сироты не бывает.
* **Цена без коэффициента** (правило №3 CLAUDE.md): в строке версии лежит
  исходная цена, коэффициент версии копируется и применяется при показе.
* **Автоматическая операция** (правило №9): сигналов журнала корректировок нет.
* «Цена работы включает материалы» — цена материала строки **не меняется**,
  пометка в `kp_ref.includes_materials` и в примечании.
"""
from __future__ import annotations

import copy
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.estimate_version import EstimateVersion
from app.models.history import TaskHistory
from app.models.kp_request import STATUS_DONE, KpRequest, KpRequestItem
from app.services import kp_offers, kp_pricing
from app.services.price_service import normalize_text
from app.utils.auth import current_user_id
from app.utils.estimate_rows import row_cost
from app.utils.price_coercion import coerce_price

OPERATION_TYPE = "kp_prices"
VERSION_NAME = "Цены из КП"
KIND = "optimization"

MATCH_ROW_ID = "row_id"
MATCH_SOURCE_NO = "source_no"
MATCH_NAME_UNIT = "name_unit"

_PRICE_FIELD = {"material": "price_material", "work": "price_work"}


def _text(value: Any) -> str:
    return normalize_text(str(value if value is not None else ""))


def _sheet(value: Any) -> Optional[str]:
    text = str(value).strip() if value is not None else ""
    return text or None


def _date_iso(value: Any) -> Optional[str]:
    return value.isoformat() if isinstance(value, (date, datetime)) else None


def _date_ru(value: Any) -> Optional[str]:
    return value.strftime("%d.%m.%Y") if isinstance(value, (date, datetime)) else None


# ---------------------------------------------------------------------------
# Сопоставление позиции со строками версии
# ---------------------------------------------------------------------------

def _eligible(row: Any, item_type: str) -> bool:
    return (
        isinstance(row, dict)
        and str(row.get("type") or "").strip().lower() == item_type
        and bool(_text(row.get("name")))
        and row.get("id") is not None
    )


def _match(item: KpRequestItem, request: KpRequest, rows: list, task_id: str) -> tuple[str, list]:
    """(шаг, строки) — первый шаг, давший хотя бы одну строку; ([], '') — не найдено."""
    item_type = item.item_type
    candidates = [r for r in rows if _eligible(r, item_type)]

    name = _text(item.name)
    if request.source_task_id and str(request.source_task_id) == str(task_id):
        # id строки переживает замену позиции аналогом: оптимизация пишет другое
        # наименование в ту же строку. Цена из КП назначена за позицию запроса,
        # поэтому без совпадения наименования row_id не доказательство.
        ids = {str(x) for x in (item.source_row_ids or [])}
        found = [r for r in candidates if str(r.get("id")) in ids and _text(r.get("name")) == name]
        if found:
            return MATCH_ROW_ID, found

    sheet = _sheet(item.sheet)

    def narrow(found: list) -> list:
        if sheet is None:
            return found
        return [r for r in found if _sheet(r.get("sheet")) == sheet]

    source_no = str(item.source_no).strip() if item.source_no else ""
    if source_no:
        found = narrow([
            r for r in candidates
            if str(r.get("source_no") or "").strip() == source_no and _text(r.get("name")) == name
        ])
        if found:
            return MATCH_SOURCE_NO, found

    unit = _text(item.unit)
    found = narrow([
        r for r in candidates
        if _text(r.get("name")) == name and _text(r.get("unit")) == unit
    ])
    if found:
        return MATCH_NAME_UNIT, found
    return "", []


def _is_ambiguous(step: str, found: list) -> bool:
    names = {_text(r.get("name")) for r in found}
    if len(names) > 1:
        return True
    # Позиция из свёртки по всем листам законно состоит из строк разных листов:
    # на шаге row_id их выбрал сам человек.
    if step == MATCH_ROW_ID:
        return False
    return len({_sheet(r.get("sheet")) for r in found}) > 1


# ---------------------------------------------------------------------------
# План: что куда ляжет
# ---------------------------------------------------------------------------

@dataclass
class Plan:
    rows: list                      # строки версии, как есть
    assigned: dict = field(default_factory=dict)   # row_id → [кандидат]
    ambiguous: list = field(default_factory=list)
    not_found: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    no_price: int = 0


def _item_out(item: KpRequestItem, request: KpRequest, best: dict) -> dict:
    return {
        "request_id": str(request.id), "item_id": str(item.id), "item_type": item.item_type,
        "name": item.name, "unit": item.unit, "sheet": item.sheet, "source_no": item.source_no,
        "price": best["price"], "supplier": best["supplier_name"],
        "offer_date": _date_iso(best["offer_date"]), "offers_count": best["offers_count"],
        "includes_materials": best["includes_materials"],
    }


def _candidate(item, request, row: dict, offers: list, prices: list, step: str) -> Optional[dict]:
    """Цена позиции для конкретной строки — в единице строки. None — единица не сводится."""
    unit = row.get("unit") if str(row.get("unit") or "").strip() else item.unit
    proxy = SimpleNamespace(unit=unit, selected_offer_id=item.selected_offer_id)
    best = kp_pricing.best_for_item(proxy, offers, prices)
    if best is None:
        return None
    return {
        "row_id": str(row["id"]), "request_id": str(request.id), "item_id": str(item.id),
        "offer_id": best["offer_id"], "supplier": best["supplier_name"],
        "offer_date": _date_iso(best["offer_date"]), "offers_count": best["offers_count"],
        "includes_materials": bool(best["includes_materials"]),
        "price": best["price"], "match": step,
    }


async def _done_requests(db: AsyncSession, card_id: str) -> list[KpRequest]:
    return list((await db.execute(
        select(KpRequest)
        .where(KpRequest.card_id == card_id, KpRequest.status == STATUS_DONE,
               KpRequest.deleted_at.is_(None))
        .order_by(KpRequest.completed_at, KpRequest.created_at, KpRequest.id)
    )).scalars().all())


async def build_plan(db: AsyncSession, card_id: str, version: Any) -> Plan:
    rows = list(version.rows or [])
    plan = Plan(rows=rows)
    task_id = str(version.task_id)
    for request in await _done_requests(db, card_id):
        items = list((await db.execute(
            select(KpRequestItem).where(KpRequestItem.request_id == request.id)
            .order_by(KpRequestItem.position, KpRequestItem.id)
        )).scalars().all())
        offers = await kp_offers.load_offers(db, str(request.id))
        all_prices = await kp_offers.load_prices(db, offers)
        by_item: dict[str, list] = {}
        for p in all_prices:
            by_item.setdefault(str(p.item_id), []).append(p)

        for item in items:
            prices = by_item.get(str(item.id), [])
            best = kp_pricing.best_for_item(item, offers, prices)
            if best is None:
                plan.no_price += 1
                continue
            step, found = _match(item, request, rows, task_id)
            if not found:
                plan.not_found.append(_item_out(item, request, best))
                continue
            cands = []
            for row in found:
                cand = _candidate(item, request, row, offers, prices, step)
                if cand is None:
                    plan.skipped.append({
                        "row_id": str(row["id"]), "item_id": str(item.id), "name": row.get("name"),
                        "reason": kp_pricing.incompatible_reason(item.unit, row.get("unit")),
                    })
                    continue
                cands.append((row, cand))
            if not cands:
                continue
            if _is_ambiguous(step, found):
                out = _item_out(item, request, best)
                out["candidates"] = [
                    {"row_id": c["row_id"], "name": r.get("name"), "unit": r.get("unit"),
                     "sheet": r.get("sheet"), "source_no": r.get("source_no"), "qty": r.get("qty"),
                     "old_price": r.get(_PRICE_FIELD[item.item_type]), "new_price": c["price"],
                     "_candidate": c}
                    for r, c in cands
                ]
                plan.ambiguous.append(out)
                continue
            for _row, cand in cands:
                plan.assigned.setdefault(cand["row_id"], []).append(cand)
    return plan


def _winners(plan: Plan, extra: Optional[dict] = None) -> dict:
    """row_id → кандидат с минимальной ценой (при равенстве — раньше завершённый запрос)."""
    pooled: dict[str, list] = {k: list(v) for k, v in plan.assigned.items()}
    for row_id, cands in (extra or {}).items():
        pooled.setdefault(row_id, []).extend(cands)
    return {row_id: min(cands, key=lambda c: c["price"]) for row_id, cands in pooled.items() if cands}


def _row_changes(plan: Plan, winners: dict) -> list[dict]:
    out = []
    for row in plan.rows:
        if not isinstance(row, dict):
            continue
        win = winners.get(str(row.get("id")))
        if win is None:
            continue
        field_name = _PRICE_FIELD[str(row.get("type")).strip().lower()]
        out.append({
            "row_id": str(row["id"]), "name": row.get("name"), "unit": row.get("unit"),
            "sheet": row.get("sheet"), "source_no": row.get("source_no"), "type": row.get("type"),
            "field": field_name, "old_price": row.get(field_name), "new_price": win["price"],
            **{k: win[k] for k in ("request_id", "item_id", "offer_id", "supplier", "offer_date",
                                   "offers_count", "includes_materials", "match")},
        })
    return out


def plan_hash(version: Any, plan: Plan) -> str:
    payload = {
        "version_id": str(version.id),
        "assigned": {k: sorted(v, key=lambda c: (c["request_id"], c["item_id"]))
                     for k, v in sorted(plan.assigned.items())},
        "ambiguous": [
            {**{k: v for k, v in a.items() if k != "candidates"},
             "candidates": [c["_candidate"] for c in a["candidates"]]}
            for a in plan.ambiguous
        ],
        "not_found": plan.not_found,
        "skipped": plan.skipped,
        "rows": plan.rows,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _public_ambiguous(plan: Plan) -> list:
    return [
        {**a, "candidates": [{k: v for k, v in c.items() if k != "_candidate"}
                             for c in a["candidates"]]}
        for a in plan.ambiguous
    ]


# ---------------------------------------------------------------------------
# Документ и версия-источник
# ---------------------------------------------------------------------------

def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


def _latest(doc: Any) -> Optional[Any]:
    alive = [v for v in doc.versions if not v.is_rolled_back]
    return max(alive, key=lambda v: v.version_number) if alive else None


async def _source(db: AsyncSession, card_id: str, version_id: str, current_user: dict):
    """Документ оптимизации и версия-источник — обязана быть последней неоткатанной.

    `resolve_document` считает активной первую неоткатанную (V0), а цены из КП
    ложатся поверх последней: источник выбирается явно (проблема 30 плана).
    """
    from app.services import document_service as docs
    from app.services import kp_requests

    kp_requests.ensure_sales(current_user)
    doc = await docs.resolve_document(db, card_id, KIND, current_user)
    docs.ensure_writable(doc, current_user)
    version = docs.pick_version(doc, version_id)
    latest = _latest(doc)
    if latest is None or str(latest.id) != str(version.id):
        raise _conflict(
            "Цены из КП применяются к последней версии оптимизации — откройте её и повторите"
        )
    return doc, version


async def preview(db: AsyncSession, card_id: str, version_id: str, current_user: dict) -> dict:
    """Что изменится. Ничего не пишет."""
    _doc, version = await _source(db, card_id, version_id, current_user)
    plan = await build_plan(db, card_id, version)
    rows = _row_changes(plan, _winners(plan))
    return {
        "version_id": str(version.id),
        "rev": int(version.rev or 0),
        "preview_hash": plan_hash(version, plan),
        "rows": rows,
        "ambiguous": _public_ambiguous(plan),
        "not_found": plan.not_found,
        "skipped": plan.skipped,
        "no_price_count": plan.no_price,
        "includes_materials_count": sum(1 for r in rows if r["includes_materials"]),
    }


def _chosen(plan: Plan, choices: Optional[dict]) -> dict:
    """Выбор человека по неоднозначным позициям → row_id → [кандидат]. Чужая строка — 422."""
    choices = choices or {}
    by_item = {a["item_id"]: a for a in plan.ambiguous}
    unknown = [k for k in choices if k not in by_item]
    if unknown:
        raise _unprocessable("Выбор строки дан для позиции, которая не требует выбора")
    extra: dict[str, list] = {}
    for item_id, picked in choices.items():
        if picked is None:
            continue
        ids = [picked] if isinstance(picked, str) else picked
        if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
            raise _unprocessable("Выбор строки: ожидается id строки или список id")
        allowed = {c["row_id"]: c["_candidate"] for c in by_item[item_id]["candidates"]}
        if any(x not in allowed for x in ids):
            raise _unprocessable(
                f"Строка не подходит позиции «{by_item[item_id]['name']}» — выберите из предложенных"
            )
        for x in dict.fromkeys(ids):
            extra.setdefault(x, []).append(allowed[x])
    return extra


def _note(win: dict) -> str:
    note = f"{_NOTE_PREFIX} {win['supplier'] or 'без названия'}"
    offer_date = win.get("offer_date")
    if offer_date:
        note += f" от {_date_ru(date.fromisoformat(str(offer_date)[:10]))}"
    if win["includes_materials"]:
        note += ", цена включает материалы"
    return note


_NOTE_PREFIX = "Из КП:"
_NOTE_SEP = "; "


def _merge_note(previous: Any, note: str) -> str:
    """Пометка КП дописывается к примечанию оптимизации, а не затирает его.

    Прежняя пометка КП (повторное применение) заменяется новой — не копится.
    """
    text = str(previous).strip() if previous is not None else ""
    parts = [p for p in (x.strip() for x in text.split(_NOTE_SEP)) if p]
    kept = [p for p in parts if not p.startswith(_NOTE_PREFIX)]
    return _NOTE_SEP.join([*kept, note])


def _apply_to_rows(rows: list, winners: dict) -> list:
    out = copy.deepcopy(rows)
    for row in out:
        if not isinstance(row, dict):
            continue
        win = winners.get(str(row.get("id")))
        if win is None:
            continue
        field_name = _PRICE_FIELD[str(row.get("type")).strip().lower()]
        # Работа «включает материалы»: пишем только цену работы, материал не трогаем.
        row[field_name] = win["price"]
        row["cost"] = row_cost(
            row.get("qty"), coerce_price(row.get("price_work")), coerce_price(row.get("price_material")),
        )
        # `field` и `price` — какую цену и какой записали: пометка действует, пока
        # цена строки та же (`utils/kp_marks.kp_ref_active`, зеркально на фронте).
        row["kp_ref"] = {
            **{k: win[k] for k in (
                "request_id", "offer_id", "supplier", "offer_date", "offers_count",
                "includes_materials",
            )},
            "field": field_name,
            "price": win["price"],
        }
        row["optimization_note"] = _merge_note(row.get("optimization_note"), _note(win))
    return out


async def apply(
    db: AsyncSession,
    card_id: str,
    version_id: str,
    client_rev: int,
    preview_hash: str,
    choices: Optional[dict],
    current_user: dict,
) -> dict:
    """Новая версия «Цены из КП» от последней неоткатанной — одной транзакцией."""
    from app.services import document_service as docs
    from app.services.estimate_versions_service import clone_version

    doc, version = await _source(db, card_id, version_id, current_user)
    task_id, source_id = str(doc.task.id), str(version.id)

    # Заявка на ревизию исходной версии: правка коллеги после предпросмотра —
    # конфликт, а не молча потерянная правка (у последней версии её не будет).
    stale = int(version.rev or 0) != client_rev
    if stale or await docs._claim_rev(db, doc, source_id, client_rev) == 0:
        await db.rollback()
        raise await docs._stale_rev_error(db, task_id, KIND)

    try:
        await db.refresh(version)
        # Пока шёл предпросмотр, могли зафиксировать версию новее: цены легли бы
        # не поверх последней. Проверяем уже внутри транзакции записи.
        newer = (await db.execute(
            select(EstimateVersion.id).where(
                EstimateVersion.task_id == task_id,
                EstimateVersion.file_slot == version.file_slot,
                EstimateVersion.is_rolled_back.is_(False),
                EstimateVersion.version_number > version.version_number,
            ).limit(1)
        )).scalar_one_or_none()
        if newer is not None:
            raise _conflict(
                "Цены из КП применяются к последней версии оптимизации — откройте её и повторите"
            )
        plan = await build_plan(db, card_id, version)
        if plan_hash(version, plan) != preview_hash:
            raise _conflict(
                "Цены КП или строки оптимизации изменились после предпросмотра — "
                "откройте предпросмотр заново"
            )
        winners = _winners(plan, _chosen(plan, choices))
        if not winners:
            raise _unprocessable("Нет строк, которым можно поставить цену из КП")

        old_rows = list(version.rows or [])
        new_rows = _apply_to_rows(old_rows, winners)
        clone = await clone_version(db, version, VERSION_NAME)
        clone.rows = new_rows

        user_name = await docs.user_display_name(db, current_user)
        changes = docs.diff_rows(old_rows, new_rows, doc.row_format)
        db.add(TaskHistory(
            id=str(uuid.uuid4()),
            task_id=task_id,
            operation_type=OPERATION_TYPE,
            slot=doc.file_slot,
            description=f"{user_name}: Цены из КП: {len(winners)} строк (версия «{VERSION_NAME}»)",
            previous_value={"rows": old_rows},
            new_value={"changes": changes[:docs.MAX_DETAILED_CHANGES], "changes_count": len(changes),
                       "version_id": str(clone.id), "source_version_id": source_id},
            user_id=current_user_id(current_user),
            user_name=user_name,
            document_kind=KIND,
        ))
        await db.flush()
        await docs._trim_history(db, task_id, KIND)

        applied_requests = sorted({w["request_id"] for w in winners.values()})
        now = datetime.now(timezone.utc)
        await db.execute(
            update(KpRequest)
            .where(KpRequest.id.in_(applied_requests))
            .values(applied_at=now, applied_version_id=str(clone.id))
            .execution_options(synchronize_session=False)
        )
        clone_id, clone_number = str(clone.id), clone.version_number
        await db.commit()
    except BaseException:
        await db.rollback()
        raise

    return {
        "version_id": clone_id,
        "version_number": clone_number,
        "source_version_id": source_id,
        "applied_rows": len(winners),
        "changes_count": len(changes),
        "request_ids": applied_requests,
    }
