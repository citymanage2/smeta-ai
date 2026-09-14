"""ИИ-разбор файла КП: цены по позициям запроса — черновиком.

План: plans/2026-09-14-zapros-kp.md, фаза 6 (критерии 16–17 спецификации).
Приведение цен (НДС, единица) — не здесь, а в `kp_pricing`: разбор пишет цену
**как в файле** — за единицу КП, с НДС или без по условиям КП.

Правила:

* **Разбор — в фоне** (job `kp.parse_offer`), ставится той же транзакцией, что
  и само КП (или «Разобрать заново»): иначе КП осиротело бы в `queued` без job.
* **ИИ сопоставляет только с позициями запроса.** В промпт позиции уходят
  короткими id («1», «2», …), без UUID базы; id, которого нет в списке, —
  отбрасывается, выдумать позицию нельзя.
* **Распознанная цена — черновик** (`source=ai`, `confirmed=false`), пока человек
  не подтвердит или не исправит (критерий 18). Ручная цена и подтверждённая
  человеком цена ИИ разбором **не перезаписываются**; повторный разбор заменяет
  только неподтверждённые черновики.
* **«Только сумма»** — цена = сумма / количество, уверенность низкая.
* **Догадки заполняют только пустые поля КП** (поставщик, дата). Режим НДС и
  ставку человек выбирает при загрузке — пустыми они не бывают, поэтому догадки
  о них, как и «включает материалы» (только для работ; отметку ставит человек),
  лежат подсказкой в `parse_hints`.
* **Запись — через «замок» запроса** (`kp_offers._lock`): завершение и разбор не
  проскакивают друг мимо друга. Запрос успели завершить или отменить — цены не
  пишутся, разбор `failed` с причиной.
* **Ошибка — текстом**, ручной ввод цен доступен всегда; платный вызов сам не
  повторяется (job завершается), повтор — кнопкой.
* **Брошенный разбор** (`processing` дольше `ABANDONED_AFTER`, воркер
  перезапущен) при чтении карточки становится `failed` — как
  `analogs_service._looks_abandoned`; его можно запустить заново.
* **Стоимость** — журнал вызовов API (правило №13, строка без `task_id`) и
  `parse_cost` у КП (сумма всех разборов этого КП).
"""
from __future__ import annotations

import asyncio
import io
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

import structlog
from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.models.kp_request import (
    CATEGORY_WORK, STATUS_IN_PROGRESS, KpOffer, KpOfferPrice, KpRequest, KpRequestItem,
)
from app.services import kp_pricing, storage_service
from app.services.claude_service import call_claude
from app.utils.auth import current_user_id
from app.utils.json_utils import extract_json

logger = structlog.get_logger()

JOB_KIND = "kp.parse_offer"

PARSE_QUEUED = "queued"
PARSE_PROCESSING = "processing"
PARSE_PARSED = "parsed"
PARSE_FAILED = "failed"

# Дольше самого долгого разумного разбора (100 страниц PDF — минуты) и не
# меньше видимости job в очереди: живой разбор не должен считаться брошенным.
ABANDONED_AFTER = timedelta(minutes=15)
ABANDONED_ERROR = (
    "Разбор прервался: обработчик не ответил. Запустите разбор заново или введите цены вручную."
)
# Потолок ожидания ответа ИИ — заметно меньше ABANDONED_AFTER.
CALL_TIMEOUT_S = 540.0
MAX_PDF_PAGES = 100
# Текст таблицы в промпте: ~150 тыс. символов — десятки тысяч токенов.
MAX_SHEET_CHARS = 150_000

_CONFIDENCE = ("high", "medium", "low")
_NAME_LEN = 1000
_UNIT_LEN = 64
_SUPPLIER_LEN = 500
_ERROR_LEN = 500


class OfferFileError(ValueError):
    """Файл КП нельзя отдать ИИ — текст для человека."""


# ---------------------------------------------------------------------------
# Постановка разбора
# ---------------------------------------------------------------------------

def parse_job(offer_id: str, owner_id: Optional[int]) -> Job:
    """Job разбора — добавляется в сессию вызывающим, коммитится вместе с КП."""
    return Job(kind=JOB_KIND, payload={"offer_id": str(offer_id)}, owner_id=owner_id,
               priority=0, status="queued")


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def is_abandoned(offer: Any, now: Optional[datetime] = None) -> bool:
    """Разбор числится идущим, но за ним никого нет."""
    if getattr(offer, "parse_status", None) != PARSE_PROCESSING:
        return False
    started = _aware(getattr(offer, "parse_started_at", None))
    if started is None:
        return True
    return (now or datetime.now(timezone.utc)) - started >= ABANDONED_AFTER


async def expire_abandoned(db: AsyncSession, offers: list[KpOffer]) -> None:
    """При чтении: брошенный разбор → `failed`. Условие повторяется в `UPDATE`,
    чтобы не затереть разбор, который воркер успел закончить."""
    now = datetime.now(timezone.utc)
    stale = [o for o in offers if is_abandoned(o, now)]
    if not stale:
        return
    cutoff = now - ABANDONED_AFTER
    await db.execute(
        update(KpOffer)
        .where(
            KpOffer.id.in_([str(o.id) for o in stale]),
            KpOffer.parse_status == PARSE_PROCESSING,
            (KpOffer.parse_started_at.is_(None)) | (KpOffer.parse_started_at <= cutoff),
        )
        .values(parse_status=PARSE_FAILED, parse_error=ABANDONED_ERROR)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    for offer in stale:
        await db.refresh(offer)
    logger.warning("kp_parse_abandoned", offers=[str(o.id) for o in stale])


async def restart(db: AsyncSession, offer_id: str, current_user: dict) -> KpOffer:
    """«Разобрать заново»: только сотрудник роли, пока запрос в работе."""
    from app.services import kp_offers

    offer, request = await kp_offers.get_offer(db, offer_id, current_user)
    kp_offers.ensure_work(request, current_user)
    if not offer.storage_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="У КП нет файла — разбирать нечего, цены вводятся вручную",
        )
    await kp_offers._lock(db, str(request.id), (STATUS_IN_PROGRESS,))
    await kp_offers._ensure_offer_alive(db, str(offer.id))
    await db.refresh(offer)
    if offer.parse_status == PARSE_QUEUED or (
        offer.parse_status == PARSE_PROCESSING and not is_abandoned(offer)
    ):
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Разбор этого КП уже идёт")
    offer.parse_status = PARSE_QUEUED
    offer.parse_error = None
    db.add(parse_job(str(offer.id), current_user_id(current_user)))
    await db.commit()
    await db.refresh(offer)
    logger.info("kp_parse_restarted", offer_id=str(offer.id), request_id=str(request.id))
    return offer


# ---------------------------------------------------------------------------
# Файл → то, что уходит в ИИ
# ---------------------------------------------------------------------------

def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).replace("\t", " ").replace("\n", " ").strip()


def spreadsheet_text(data: bytes) -> str:
    """Книга Excel текстом: все листы, пустые строки прочь, объём ограничен."""
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 — наружу уходит человеческий текст
        raise OfferFileError(
            "Файл не читается как таблица Excel. Файл старого формата XLS сохраните как XLSX "
            "или введите цены вручную"
        ) from exc
    parts: list[str] = []
    size = 0
    truncated = False
    try:
        for ws in wb.worksheets:
            header = f"=== Лист: {ws.title} ==="
            parts.append(header)
            size += len(header) + 1
            for row in ws.iter_rows(values_only=True):
                cells = [_cell_text(v) for v in row]
                if not any(cells):
                    continue
                line = "\t".join(cells).rstrip("\t")
                if size + len(line) + 1 > MAX_SHEET_CHARS:
                    truncated = True
                    break
                parts.append(line)
                size += len(line) + 1
            if truncated:
                break
    finally:
        wb.close()
    text = "\n".join(parts)
    if truncated:
        text += (
            f"\n[… файл обрезан: показаны первые {MAX_SHEET_CHARS} символов — "
            "цены дальше введите вручную]"
        )
    return text


def build_file_content(file_name: Optional[str], mime_type: Optional[str], data: bytes) -> tuple[list[dict], str]:
    """(блоки документа/изображения, текст таблицы). Синхронно — звать в потоке."""
    from app.utils.file_parser import file_to_base64, pdf_to_content_block
    from app.utils.pdf_ocr_extractor import get_pdf_page_count

    mime = (mime_type or "").lower()
    name = file_name or "КП"
    if mime == "application/pdf":
        try:
            pages = get_pdf_page_count(data)
        except ValueError as exc:
            raise OfferFileError(f"Файл «{name}» не открывается как PDF") from exc
        if pages > MAX_PDF_PAGES:
            raise OfferFileError(f"В PDF «{name}» {pages} стр., разбираются не больше {MAX_PDF_PAGES}")
        try:
            return [pdf_to_content_block(data)], ""
        except ValueError as exc:
            raise OfferFileError(str(exc)) from exc
    if mime in ("image/jpeg", "image/png"):
        return [file_to_base64(data, mime)], ""
    if mime in (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
    ):
        return [], f"=== Файл КП: {name} ===\n{spreadsheet_text(data)}"
    raise OfferFileError(f"Формат файла «{name}» не разбирается — введите цены вручную")


# ---------------------------------------------------------------------------
# Промпт
# ---------------------------------------------------------------------------

_PROMPT = """Ты — специалист отдела снабжения строительной компании. Перед тобой коммерческое предложение (КП) {who} и позиции, по которым у него запрашивали цены.

Задача: для каждой позиции найди в КП её цену. Сопоставляй по смыслу: наименование, марка, размер, единица измерения.

Правила:
- цены — только для позиций из списка; item_id — строго id из списка; позиции, которой нет в КП, в ответе быть не должно; ничего не выдумывай;
- unit_price — цена за единицу КАК В КП: не пересчитывай единицы и не снимай НДС; unit — единица измерения в КП; name_in_offer — наименование строки КП;
- если в КП у строки только сумма без цены за единицу — total_only: true, total — сумма строки, qty — количество в КП (если указано);
- confidence: "high" — позиция совпадает однозначно; "medium" — вероятно та же, есть расхождения (марка, размер); "low" — сомнительно;
- одна строка КП может подойти нескольким позициям — укажи цену для каждой;
- supplier_guess — название поставщика из КП; date_guess — дата КП в формате ГГГГ-ММ-ДД;
- vat_mode_guess — "with_vat", если цены в КП указаны с НДС, "without_vat" — если без НДС, null — если не ясно; vat_rate_guess — ставка НДС в процентах, если указана;
- {includes_rule}
- числа — без пробелов и знака валюты, десятичный разделитель — точка; неизвестное — null.

Позиции запроса (JSON: id, name, unit, qty):
<positions>
{positions}
</positions>

Верни СТРОГО JSON без markdown:
{{"supplier_guess": null, "date_guess": null, "vat_mode_guess": null, "vat_rate_guess": null, "includes_materials_guess": null, "prices": [{{"item_id": "1", "name_in_offer": "...", "unit": "...", "unit_price": 0, "total_only": false, "total": null, "qty": null, "confidence": "high"}}]}}"""

_INCLUDES_WORK = (
    "includes_materials_guess — true, если по КП цены работ включают материалы, "
    "false — если явно без материалов, null — если не ясно"
)
_INCLUDES_MATERIAL = "includes_materials_guess — всегда null"


def build_prompt(items: list[Any], category: str) -> tuple[str, dict[str, Any]]:
    """Текст промпта и соответствие «короткий id → позиция»."""
    ids: dict[str, Any] = {}
    listing = []
    for index, item in enumerate(items, start=1):
        short = str(index)
        ids[short] = item
        listing.append({"id": short, "name": item.name, "unit": item.unit, "qty": item.qty})
    work = category == CATEGORY_WORK
    prompt = _PROMPT.format(
        who="подрядчика" if work else "поставщика",
        includes_rule=_INCLUDES_WORK if work else _INCLUDES_MATERIAL,
        positions=json.dumps(listing, ensure_ascii=False),
    )
    return prompt, ids


# ---------------------------------------------------------------------------
# Ответ ИИ → черновые цены и догадки
# ---------------------------------------------------------------------------

@dataclass
class ParseResult:
    # id позиции (UUID базы) → {price, unit, name_in_offer, confidence}
    prices: dict[str, dict] = field(default_factory=dict)
    dropped_unknown: int = 0
    dropped_duplicates: int = 0
    guesses: dict[str, Any] = field(default_factory=dict)


def _number(value: Any) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    for junk in (" ", " ", " ", "₽", "руб.", "руб"):
        text = text.replace(junk, "")
    text = text.replace(",", ".")
    if not text:
        return None
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _text(value: Any, limit: int) -> Optional[str]:
    if value is None or isinstance(value, (dict, list)):
        return None
    text = " ".join(str(value).split())
    return text[:limit] or None


def _price_value(value: Decimal) -> float:
    """Цена как в КП — без округления до копеек (оно одно, в `kp_pricing`)."""
    return float(value.quantize(Decimal("0.000001")))


def _guesses(data: dict) -> dict:
    out: dict[str, Any] = {}
    supplier = _text(data.get("supplier_guess"), _SUPPLIER_LEN)
    if supplier:
        out["supplier"] = supplier
    raw_date = _text(data.get("date_guess"), 32)
    if raw_date:
        try:
            parsed = date.fromisoformat(raw_date[:10])
            if 2000 <= parsed.year <= 2100:
                out["date"] = parsed
        except ValueError:
            pass
    mode = data.get("vat_mode_guess")
    if mode in kp_pricing.VAT_MODES:
        out["vat_mode"] = mode
    rate = _number(data.get("vat_rate_guess"))
    if rate is not None and 0 <= rate < 100:
        out["vat_rate"] = float(round(rate, 2))
    includes = data.get("includes_materials_guess")
    if isinstance(includes, bool):
        out["includes_materials"] = includes
    return out


def postprocess(data: Any, ids: dict[str, Any]) -> ParseResult:
    """Разобрать ответ ИИ. Чужие id, пустые и неположительные цены — прочь."""
    result = ParseResult()
    if not isinstance(data, dict):
        return result
    result.guesses = _guesses(data)
    raw_prices = data.get("prices")
    if not isinstance(raw_prices, list):
        return result
    for entry in raw_prices:
        if not isinstance(entry, dict):
            continue
        item = ids.get(str(entry.get("item_id")).strip()) if entry.get("item_id") is not None else None
        if item is None:
            result.dropped_unknown += 1
            continue
        item_id = str(item.id)
        if item_id in result.prices:
            result.dropped_duplicates += 1
            continue

        unit = _text(entry.get("unit"), _UNIT_LEN)
        confidence = entry.get("confidence") if entry.get("confidence") in _CONFIDENCE else "low"
        price = _number(entry.get("unit_price"))
        total = _number(entry.get("total"))
        if entry.get("total_only") is True or (price is None and total is not None):
            if total is None or total <= 0:
                continue
            qty = _number(entry.get("qty"))
            if qty is None or qty <= 0:
                # Количество из КП не пришло — делим на объём позиции, и цена
                # тогда за единицу позиции, а не за единицу КП.
                qty = _number(item.qty)
                unit = _text(item.unit, _UNIT_LEN)
            if qty is None or qty <= 0:
                continue
            price = total / qty
            confidence = "low"
        if price is None or price <= 0:
            continue
        result.prices[item_id] = {
            "price": _price_value(price),
            "unit": unit,
            "name_in_offer": _text(entry.get("name_in_offer"), _NAME_LEN),
            "confidence": confidence,
        }
    return result


# ---------------------------------------------------------------------------
# Разбор (обработчик job)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _ItemRef:
    id: str
    name: str
    unit: Optional[str]
    qty: Optional[float]


async def _claim(db: AsyncSession, offer_id: str) -> Optional[datetime]:
    """`queued → processing` атомарно. None — разбирать нечего (КП удалено,
    разбор уже идёт или закончен): платный вызов не повторяется."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(KpOffer)
        .where(
            KpOffer.id == offer_id,
            KpOffer.deleted_at.is_(None),
            KpOffer.storage_key.is_not(None),
            KpOffer.parse_status == PARSE_QUEUED,
        )
        .values(parse_status=PARSE_PROCESSING, parse_started_at=now, parse_error=None)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    return now if result.rowcount else None


def _mine(offer_id: str, started: datetime):
    """Условие «это всё ещё мой разбор»: после «Разобрать заново» по брошенному
    разбору старый обработчик не должен перетереть новый."""
    return (
        (KpOffer.id == offer_id)
        & (KpOffer.parse_status == PARSE_PROCESSING)
        & (KpOffer.parse_started_at == started)
    )


async def _add_cost(db: AsyncSession, offer_id: str, cost: Decimal) -> None:
    if cost <= 0:
        return
    await db.execute(
        update(KpOffer).where(KpOffer.id == offer_id)
        .values(parse_cost=func.coalesce(KpOffer.parse_cost, 0) + float(cost))
        .execution_options(synchronize_session=False)
    )


def _error_text(exc: BaseException) -> str:
    if isinstance(exc, asyncio.TimeoutError):
        reason = "ИИ не ответил за отведённое время"
    else:
        reason = (str(exc) or exc.__class__.__name__).strip()
    reason = reason[:_ERROR_LEN].rstrip(" .")
    return f"Разбор не удался: {reason}. Введите цены вручную или запустите разбор заново."


async def _fail(db: AsyncSession, offer_id: str, started: datetime, message: str, cost: Decimal) -> None:
    await db.rollback()
    await _add_cost(db, offer_id, cost)
    await db.execute(
        update(KpOffer).where(_mine(offer_id, started))
        .values(parse_status=PARSE_FAILED, parse_error=message)
        .execution_options(synchronize_session=False)
    )
    await db.commit()


async def process_offer(db: AsyncSession, offer_id: str) -> None:
    """Разобрать файл КП. Никогда не бросает: итог — `parsed` или `failed`."""
    started = await _claim(db, offer_id)
    if started is None:
        logger.info("kp_parse_skipped", offer_id=offer_id)
        return

    spent = Decimal(0)

    def on_cost(cost: Decimal) -> None:
        nonlocal spent
        spent += cost

    try:
        offer = await db.get(KpOffer, offer_id, populate_existing=True)
        request = await db.get(KpRequest, str(offer.request_id)) if offer is not None else None
        if offer is None or request is None:
            return
        request_id = str(request.id)
        category = request.category
        # Снимок позиций простыми значениями: откат ниже истекает объекты сессии.
        items = [
            _ItemRef(id=str(i.id), name=i.name, unit=i.unit, qty=i.qty)
            for i in (await db.execute(
                select(KpRequestItem).where(KpRequestItem.request_id == request_id)
                .order_by(KpRequestItem.position)
            )).scalars().all()
        ]
        storage_key, file_name, mime_type = offer.storage_key, offer.file_name, offer.mime_type
        # Не держать транзакцию открытой, пока идут S3 и ИИ.
        await db.rollback()
        if not items:
            raise OfferFileError("в запросе нет позиций")

        data = await storage_service.load_bytes(storage_key)
        blocks, sheet = await asyncio.to_thread(build_file_content, file_name, mime_type, data)
        prompt, ids = build_prompt(items, category)
        content = f"{sheet}\n\n{prompt}" if sheet else prompt
        answer = await call_claude(
            messages=[{"role": "user", "content": content}],
            image_data=blocks or None,
            processing_timeout=CALL_TIMEOUT_S,
            db=db,
            log_without_task=True,
            on_cost=on_cost,
        )
        try:
            parsed = extract_json(answer)
        except ValueError as exc:
            raise OfferFileError("ИИ ответил не таблицей цен") from exc
        result = postprocess(parsed, ids)
    except Exception as exc:  # noqa: BLE001 — причину видит человек, ручной ввод доступен
        logger.warning("kp_parse_failed", offer_id=offer_id, error=str(exc)[:300])
        await _fail(db, offer_id, started, _error_text(exc), spent)
        return

    try:
        await _write(db, offer_id, request_id, category, started, result, spent)
    except Exception as exc:  # noqa: BLE001 — иначе КП осталось бы «разбирается» до таймаута
        logger.error("kp_parse_write_failed", offer_id=offer_id, error=str(exc)[:300])
        await _fail(db, offer_id, started, _error_text(exc), spent)


async def _write(
    db: AsyncSession, offer_id: str, request_id: str, category: str,
    started: datetime, result: ParseResult, spent: Decimal,
) -> None:
    from app.services import kp_offers

    try:
        await kp_offers._lock(db, request_id, (STATUS_IN_PROGRESS,))
    except HTTPException as exc:
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            return
        await _fail(
            db, offer_id, started,
            "Запрос уже завершён или отменён — распознанные цены не записаны. "
            "Верните запрос в работу и запустите разбор заново.",
            spent,
        )
        return

    current = (await db.execute(
        select(KpOffer.supplier_name, KpOffer.offer_date).where(_mine(offer_id, started))
    )).one_or_none()
    if current is None:
        # КП удалили или разбор перезапустили, пока ждали ИИ.
        await db.rollback()
        await _add_cost(db, offer_id, spent)
        await db.commit()
        logger.info("kp_parse_superseded", offer_id=offer_id)
        return
    supplier_name, offer_date = current

    guesses = result.guesses
    hints: dict[str, Any] = {
        "prices_found": len(result.prices),
        "dropped_unknown": result.dropped_unknown,
    }
    for key in ("vat_mode", "vat_rate"):
        if key in guesses:
            hints[key] = guesses[key]
    if category == CATEGORY_WORK and "includes_materials" in guesses:
        hints["includes_materials"] = guesses["includes_materials"]
    values: dict[str, Any] = {
        "parse_status": PARSE_PARSED, "parse_error": None, "parse_hints": hints,
    }
    if not (supplier_name or "").strip() and guesses.get("supplier"):
        values["supplier_name"] = guesses["supplier"]
    if offer_date is None and guesses.get("date"):
        values["offer_date"] = guesses["date"]

    kept = set((await db.execute(
        select(KpOfferPrice.item_id).where(
            KpOfferPrice.offer_id == offer_id,
            (KpOfferPrice.source != "ai") | (KpOfferPrice.confirmed.is_(True)),
        )
    )).scalars().all())
    kept = {str(item_id) for item_id in kept}
    await db.execute(
        delete(KpOfferPrice)
        .where(
            KpOfferPrice.offer_id == offer_id,
            KpOfferPrice.source == "ai",
            KpOfferPrice.confirmed.is_(False),
        )
        .execution_options(synchronize_session=False)
    )
    written = 0
    for item_id, price in result.prices.items():
        if item_id in kept:
            continue
        db.add(KpOfferPrice(
            offer_id=offer_id, item_id=item_id, price=price["price"], unit=price["unit"],
            name_in_offer=price["name_in_offer"], includes_materials=None,
            source="ai", confidence=price["confidence"], confirmed=False,
        ))
        written += 1
    await db.execute(
        update(KpOffer).where(_mine(offer_id, started)).values(**values)
        .execution_options(synchronize_session=False)
    )
    await _add_cost(db, offer_id, spent)
    await db.commit()
    logger.info(
        "kp_parse_done", offer_id=offer_id, request_id=request_id, found=len(result.prices),
        written=written, dropped_unknown=result.dropped_unknown, cost=float(spent),
    )
