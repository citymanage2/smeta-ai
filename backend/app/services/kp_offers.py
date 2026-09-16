"""КП к запросу: файлы, условия, цены матрицей, выбор КП, завершение.

План: plans/2026-09-14-zapros-kp.md, фаза 4. Приведение цен — только
`kp_pricing`; постановка, видимость и статусы запроса — `kp_requests`.

Правила:

* **Правка идёт через «замок» на строке запроса.** Любое изменение КП, цены или
  выбора начинается с `UPDATE kp_requests … WHERE status IN (…)`: проверка
  статуса живёт в самом запросе к базе, а строка запроса блокируется до
  коммита. Поэтому «Завершить» и правка цены коллегой не проскакивают друг мимо
  друга: кто второй — ждёт первого и получает актуальный статус (409 после
  завершения), а завершение видит черновик, добавленный до него.
* **Загрузка КП в новый запрос берёт его в работу** — тем же атомарным `UPDATE`
  (критерий 14): кто взял, не перезаписывается, если запрос уже в работе.
* **Ручная цена сразу подтверждена, ИИ-цена — черновик** (критерий 18).
  «Завершить» не пропускает черновики и пустой отчёт (критерий 22).
* **НДС выбирается человеком явно.** Режим «с НДС / без НДС» обязателен при
  загрузке: молчаливое «без НДС» по умолчанию завысило бы цены на 22 %.
* **Файл КП — только через роутер** с проверкой роли; ключ S3 наружу не
  отдаётся. Удаление КП удаляет его объект после коммита.
* **КП с файлом сразу ставится на ИИ-разбор** (фаза 6, `kp_parser`) той же
  транзакцией; черновики разбора пишутся через тот же «замок».
"""
from __future__ import annotations

import uuid as _uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import HTTPException, status
from sqlalchemy import case, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.models.kp_request import (
    CATEGORY_WORK, STATUS_DONE, STATUS_IN_PROGRESS, STATUS_NEW,
    KpOffer, KpOfferPrice, KpRequest, KpRequestItem,
)
from app.services import kp_parser, kp_pricing, kp_requests
from app.services import storage_service
from app.utils.auth import current_user_id
from app.utils.owner_names import owner_names
from app.utils.permissions import can_work_kp, is_production

logger = structlog.get_logger()

MAX_FILE_BYTES = settings.MAX_FILE_SIZE_MB * 1024 * 1024
MAX_PDF_PAGES = 100

# Тип — по расширению: браузеры присылают для .xls что угодно.
OFFER_FILE_TYPES = {
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}

_SUPPLIER_LEN = 500
_UNIT_LEN = 64


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


def _offer_not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="КП не найдено")


# ---------------------------------------------------------------------------
# Проверка входа (до любой записи)
# ---------------------------------------------------------------------------

@dataclass
class OfferFile:
    file_name: str
    mime_type: str
    data: bytes


def _pdf_pages(data: bytes) -> int:
    from app.utils.pdf_ocr_extractor import get_pdf_page_count

    return get_pdf_page_count(data)


async def check_offer_file(name: Optional[str], data: bytes) -> OfferFile:
    """Тип, размер и число страниц PDF — до записи в S3 и до разбора ИИ."""
    name = (name or "file").replace("\\", "/").split("/")[-1] or "file"
    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    mime = OFFER_FILE_TYPES.get(ext)
    if mime is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Тип файла «{name}» не поддерживается. Допустимые форматы КП: PDF, XLSX, XLS, JPG, PNG",
        )
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Файл «{name}» больше {settings.MAX_FILE_SIZE_MB} МБ",
        )
    if ext == ".pdf":
        try:
            pages = await run_in_threadpool(_pdf_pages, data)
        except ValueError:
            raise _unprocessable(f"Файл «{name}» не открывается как PDF — проверьте файл или введите цены вручную")
        if pages > MAX_PDF_PAGES:
            raise _unprocessable(
                f"В PDF «{name}» {pages} стр., допускается не больше {MAX_PDF_PAGES} — разделите файл"
            )
    return OfferFile(file_name=name[:255], mime_type=mime, data=data)


def parse_vat_mode(value: Any) -> str:
    mode = str(value or "").strip()
    if mode not in kp_pricing.VAT_MODES:
        raise _unprocessable("Укажите, цены в КП с НДС или без НДС")
    return mode


def parse_vat_rate(value: Any) -> Optional[float]:
    """Ставка НДС: 0 ≤ ставка < 100. Пусто — None (дальше подставится 22 %)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        rate = float(str(value).strip().replace(",", "."))
    except ValueError:
        raise _unprocessable("Ставка НДС должна быть числом")
    if not (0 <= rate < 100) or rate != rate:
        raise _unprocessable("Ставка НДС — от 0 до 100 %")
    return round(rate, 2)


def parse_offer_date(value: Any) -> Optional[date]:
    if value is None or isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise _unprocessable("Дата КП — в формате ГГГГ-ММ-ДД")


def _vat_fields(mode: str, rate: Optional[float]) -> dict:
    if mode == kp_pricing.VAT_WITHOUT:
        return {"vat_mode": mode, "vat_rate": None}
    return {"vat_mode": mode, "vat_rate": rate if rate is not None else float(kp_pricing.DEFAULT_VAT_RATE)}


def _ensure_includes_materials(request: KpRequest, value: Optional[bool]) -> None:
    if value and request.category != CATEGORY_WORK:
        raise _unprocessable("Отметка «цена включает материалы» — только для запроса по работам")


# ---------------------------------------------------------------------------
# Доступ и «замок» на запросе
# ---------------------------------------------------------------------------

def ensure_work(request: KpRequest, current_user: dict) -> None:
    """Исполнять запрос (КП, цены, завершение) — только сотрудник его роли.
    Чужая роль сюда не доходит: `get_visible` уже ответил 404."""
    if not can_work_kp(request, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="КП и цены вносит отдел производства работ",
        )


async def _lock(
    db: AsyncSession, request_id: str, statuses: tuple[str, ...], *,
    take: bool = False, take_uid: Optional[int] = None,
) -> None:
    """Атомарно проверить статус запроса и заблокировать его строку до коммита.

    `take` — взять новый запрос в работу этим же `UPDATE` (подпись — `take_uid`):
    «кто взял» ставится только у нового, у запроса в работе остаётся прежней.
    """
    now = datetime.now(timezone.utc)
    values: dict[str, Any] = {"updated_at": now}
    if take:
        is_new = KpRequest.status == STATUS_NEW
        values.update(
            status=case((is_new, STATUS_IN_PROGRESS), else_=KpRequest.status),
            taken_by_id=case((is_new, take_uid), else_=KpRequest.taken_by_id),
            taken_at=case((is_new, now), else_=KpRequest.taken_at),
        )
    result = await db.execute(
        update(KpRequest)
        .where(KpRequest.id == request_id, KpRequest.status.in_(statuses))
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:
        raise await kp_requests._conflict(db, request_id)


async def _ensure_offer_alive(db: AsyncSession, offer_id: str) -> None:
    """После «замка»: КП могли удалить, пока мы ждали строку запроса. Иначе
    правка ушла бы в пустоту (StaleDataError) или в цену без КП (нарушение FK)."""
    alive = (await db.execute(
        select(KpOffer.id).where(KpOffer.id == offer_id, KpOffer.deleted_at.is_(None))
    )).scalar_one_or_none()
    if alive is None:
        await db.rollback()
        raise _offer_not_found()


async def get_offer(db: AsyncSession, offer_id: str, current_user: dict) -> tuple[KpOffer, KpRequest]:
    if not kp_requests._valid_uuid(offer_id):
        raise _offer_not_found()
    offer = await db.get(KpOffer, str(offer_id))
    if offer is None or offer.deleted_at is not None:
        raise _offer_not_found()
    try:
        request = await kp_requests.get_visible(db, offer.request_id, current_user)
    except HTTPException:
        raise _offer_not_found()
    return offer, request


async def _get_item(db: AsyncSession, item_id: str, request_id: Optional[str] = None) -> KpRequestItem:
    if not kp_requests._valid_uuid(item_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Позиция запроса не найдена")
    item = await db.get(KpRequestItem, str(item_id))
    if item is None or (request_id is not None and str(item.request_id) != str(request_id)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Позиция запроса не найдена")
    return item


# ---------------------------------------------------------------------------
# КП
# ---------------------------------------------------------------------------

async def create_offer(
    db: AsyncSession,
    request_id: str,
    *,
    current_user: dict,
    supplier_name: Optional[str],
    offer_date: Any,
    vat_mode: Any,
    vat_rate: Any,
    includes_materials: bool,
    file: Optional[tuple[str, bytes]],
) -> KpOffer:
    request = await kp_requests.get_visible(db, request_id, current_user)
    ensure_work(request, current_user)

    supplier = (supplier_name or "").strip()[:_SUPPLIER_LEN]
    fields = _vat_fields(parse_vat_mode(vat_mode), parse_vat_rate(vat_rate))
    parsed_date = parse_offer_date(offer_date)
    _ensure_includes_materials(request, includes_materials)
    checked = await check_offer_file(*file) if file is not None else None
    if checked is None and not supplier:
        raise _unprocessable("Приложите файл КП или укажите поставщика")

    uid = current_user_id(current_user)
    offer_id = str(_uuid.uuid4())
    key = None
    try:
        # Файл — до «замка»: строку запроса незачем держать заблокированной,
        # пока в S3 едут 50 МБ. Не удалась запись в базу — объект удаляется.
        if checked is not None:
            key = storage_service.build_kp_key(request.id, "offers", checked.file_name)
            await storage_service.put_object(key, checked.data, checked.mime_type)
        await _lock(db, str(request.id), (STATUS_NEW, STATUS_IN_PROGRESS), take=True, take_uid=uid)
        offer = KpOffer(
            id=offer_id, request_id=str(request.id), supplier_name=supplier, offer_date=parsed_date,
            includes_materials=bool(includes_materials), created_by=uid,
            created_at=datetime.now(timezone.utc),
            file_name=checked.file_name if checked else None,
            mime_type=checked.mime_type if checked else None,
            size_bytes=len(checked.data) if checked else None,
            storage_key=key,
            parse_status=kp_parser.PARSE_QUEUED if checked else None,
            **fields,
        )
        db.add(offer)
        if checked is not None:
            # Разбор ИИ (фаза 6) ставится этой же транзакцией: КП без job
            # осталось бы «в очереди» навсегда.
            await db.flush()
            db.add(kp_parser.parse_job(offer_id, uid))
        await db.commit()
    except Exception:
        await db.rollback()
        await storage_service.delete_key_safe(key)
        raise
    # Статус мог смениться «замком» в обход объекта сессии.
    await db.refresh(request)
    logger.info("kp_offer_created", request_id=str(request.id), offer_id=offer_id, has_file=key is not None)
    return offer


async def update_offer(db: AsyncSession, offer_id: str, changes: dict, current_user: dict) -> KpOffer:
    """Частичная правка условий КП: только переданные поля."""
    offer, request = await get_offer(db, offer_id, current_user)
    ensure_work(request, current_user)

    values: dict[str, Any] = {}
    if "supplier_name" in changes:
        values["supplier_name"] = (changes["supplier_name"] or "").strip()[:_SUPPLIER_LEN]
    if "offer_date" in changes:
        values["offer_date"] = parse_offer_date(changes["offer_date"])
    if "includes_materials" in changes:
        _ensure_includes_materials(request, changes["includes_materials"])
        values["includes_materials"] = bool(changes["includes_materials"])
    if "vat_mode" in changes or "vat_rate" in changes:
        mode = parse_vat_mode(changes["vat_mode"]) if "vat_mode" in changes else offer.vat_mode
        if "vat_rate" in changes:
            rate = parse_vat_rate(changes["vat_rate"])
        else:
            # Смена «без НДС» → «с НДС» без ставки — ставка по умолчанию.
            rate = offer.vat_rate if mode == offer.vat_mode else None
        values.update(_vat_fields(mode, rate))

    if values.get("supplier_name", offer.supplier_name) == "" and not offer.storage_key:
        raise _unprocessable("У КП без файла должен быть указан поставщик")

    await _lock(db, str(request.id), (STATUS_IN_PROGRESS,))
    await _ensure_offer_alive(db, str(offer.id))
    for field, value in values.items():
        setattr(offer, field, value)
    await db.commit()
    await db.refresh(offer)
    return offer


async def delete_offer(db: AsyncSession, offer_id: str, current_user: dict) -> None:
    """Удалить КП вместе с его ценами и выбором. Только до завершения."""
    offer, request = await get_offer(db, offer_id, current_user)
    ensure_work(request, current_user)
    await _lock(db, str(request.id), (STATUS_IN_PROGRESS,))
    await _ensure_offer_alive(db, str(offer.id))
    key = offer.storage_key
    oid = str(offer.id)
    await db.execute(
        update(KpRequestItem).where(KpRequestItem.selected_offer_id == oid)
        .values(selected_offer_id=None).execution_options(synchronize_session=False)
    )
    await db.execute(
        delete(KpOfferPrice).where(KpOfferPrice.offer_id == oid)
        .execution_options(synchronize_session=False)
    )
    await db.delete(offer)
    await db.commit()
    await storage_service.delete_key_safe(key)
    logger.info("kp_offer_deleted", request_id=str(request.id), offer_id=oid)


async def offer_file(db: AsyncSession, offer_id: str, current_user: dict) -> KpOffer:
    offer, _request = await get_offer(db, offer_id, current_user)
    if not offer.storage_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="У КП нет файла")
    return offer


# ---------------------------------------------------------------------------
# Цены
# ---------------------------------------------------------------------------

def price_out(item: KpRequestItem, offer: KpOffer, row: KpOfferPrice) -> dict:
    return {"item_id": str(item.id), **kp_pricing.cell(item, offer, row)}


async def _price_row(db: AsyncSession, offer_id: str, item_id: str) -> Optional[KpOfferPrice]:
    return (await db.execute(
        select(KpOfferPrice).where(KpOfferPrice.offer_id == offer_id, KpOfferPrice.item_id == item_id)
    )).scalar_one_or_none()


async def set_price(
    db: AsyncSession, offer_id: str, item_id: str, *, price: float, unit: Optional[str],
    includes_materials: Optional[bool], current_user: dict,
) -> dict:
    """Ручная цена: сразу подтверждена. Черновик ИИ в той же ячейке заменяется."""
    offer, request = await get_offer(db, offer_id, current_user)
    ensure_work(request, current_user)
    item = await _get_item(db, item_id, request.id)
    if price is None or not (price > 0):
        raise _unprocessable("Цена должна быть больше нуля")
    _ensure_includes_materials(request, includes_materials)
    unit = (unit or "").strip()[:_UNIT_LEN] or None

    await _lock(db, str(request.id), (STATUS_IN_PROGRESS,))
    await _ensure_offer_alive(db, str(offer.id))
    row = await _price_row(db, str(offer.id), str(item.id))
    if row is None:
        row = KpOfferPrice(id=str(_uuid.uuid4()), offer_id=str(offer.id), item_id=str(item.id), price=price)
        db.add(row)
    row.price = float(price)
    row.unit = unit
    row.includes_materials = includes_materials
    row.source = "manual"
    row.confidence = None
    row.confirmed = True
    await db.commit()
    await db.refresh(row)
    return price_out(item, offer, row)


async def confirm_price(db: AsyncSession, offer_id: str, item_id: str, current_user: dict) -> dict:
    """Подтвердить черновую цену как есть (источник остаётся «ИИ»)."""
    offer, request = await get_offer(db, offer_id, current_user)
    ensure_work(request, current_user)
    item = await _get_item(db, item_id, request.id)
    await _lock(db, str(request.id), (STATUS_IN_PROGRESS,))
    await _ensure_offer_alive(db, str(offer.id))
    row = await _price_row(db, str(offer.id), str(item.id))
    if row is None:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Цены нет")
    row.confirmed = True
    await db.commit()
    await db.refresh(row)
    return price_out(item, offer, row)


async def delete_price(db: AsyncSession, offer_id: str, item_id: str, current_user: dict) -> None:
    offer, request = await get_offer(db, offer_id, current_user)
    ensure_work(request, current_user)
    item = await _get_item(db, item_id, request.id)
    await _lock(db, str(request.id), (STATUS_IN_PROGRESS,))
    await _ensure_offer_alive(db, str(offer.id))
    row = await _price_row(db, str(offer.id), str(item.id))
    if row is None:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Цены нет")
    await db.delete(row)
    await db.commit()


# ---------------------------------------------------------------------------
# Выбор КП у позиции
# ---------------------------------------------------------------------------

def _select_statuses(current_user: dict) -> tuple[str, ...]:
    """Производство выбирает, пока запрос в работе; продажи — и после
    завершения: выбор КП для оптимизации — их решение (критерий 19)."""
    if is_production(current_user.get("role")):
        return (STATUS_IN_PROGRESS,)
    return (STATUS_IN_PROGRESS, STATUS_DONE)


async def select_offer(
    db: AsyncSession, item_id: str, offer_id: Optional[str], current_user: dict,
) -> KpRequest:
    item = await _get_item(db, item_id)
    try:
        request = await kp_requests.get_visible(db, item.request_id, current_user)
    except HTTPException:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Позиция запроса не найдена")
    if is_production(current_user.get("role")):
        ensure_work(request, current_user)
    if offer_id is not None:
        if not kp_requests._valid_uuid(offer_id):
            raise _unprocessable("КП не из этого запроса")
        offer = await db.get(KpOffer, str(offer_id))
        if offer is None or offer.deleted_at is not None or str(offer.request_id) != str(request.id):
            raise _unprocessable("КП не из этого запроса")
    await _lock(db, str(request.id), _select_statuses(current_user))
    if offer_id is not None:
        await _ensure_offer_alive(db, str(offer_id))
    item.selected_offer_id = str(offer_id) if offer_id else None
    await db.commit()
    await db.refresh(request)
    return request


# ---------------------------------------------------------------------------
# Завершение
# ---------------------------------------------------------------------------

async def _draft_prices(db: AsyncSession, request_id: str) -> list[tuple[str, str]]:
    rows = (await db.execute(
        select(KpRequestItem.name, KpOffer.supplier_name, KpOffer.file_name)
        .select_from(KpOfferPrice)
        .join(KpOffer, KpOffer.id == KpOfferPrice.offer_id)
        .join(KpRequestItem, KpRequestItem.id == KpOfferPrice.item_id)
        .where(
            KpOffer.request_id == request_id,
            KpOffer.deleted_at.is_(None),
            KpOfferPrice.confirmed.is_(False),
        )
        .order_by(KpRequestItem.position, KpOffer.created_at)
    )).all()
    return [(name, supplier or file_name or "КП без названия") for name, supplier, file_name in rows]


async def _parsing_offers(db: AsyncSession, request_id: str) -> list[str]:
    """Поставщики КП, чей ИИ-разбор ещё идёт (в очереди или в работе, не брошен)."""
    offers = (await db.execute(
        select(KpOffer)
        .where(
            KpOffer.request_id == request_id,
            KpOffer.deleted_at.is_(None),
            KpOffer.parse_status.in_((kp_parser.PARSE_QUEUED, kp_parser.PARSE_PROCESSING)),
        )
        .order_by(KpOffer.created_at, KpOffer.id)
    )).scalars().all()
    now = datetime.now(timezone.utc)
    return [
        o.supplier_name or o.file_name or "КП без названия"
        for o in offers if not kp_parser.is_abandoned(o, now)
    ]


async def complete(db: AsyncSession, request_id: str, report: Optional[str], current_user: dict) -> KpRequest:
    """«Завершить»: отчёт обязателен, черновых цен нет; атомарно.

    Новый запрос завершается и без «Взять в работу» (КП могло не прийти ни
    одного — отчёт «никто не ответил»); завершивший тогда подписан и взявшим.
    Черновики проверяются **после** `UPDATE`: строка запроса уже заблокирована,
    и цена, добавленная коллегой до этого момента, будет видна.
    """
    request = await kp_requests.get_visible(db, request_id, current_user)
    ensure_work(request, current_user)
    text = (report or "").strip()
    if not text:
        raise _unprocessable("Напишите отчёт: кто ответил, сроки поставки, доставка")

    uid = current_user_id(current_user)
    now = datetime.now(timezone.utc)
    rid = str(request.id)
    result = await db.execute(
        update(KpRequest)
        .where(KpRequest.id == rid, KpRequest.status.in_((STATUS_NEW, STATUS_IN_PROGRESS)))
        .values(
            status=STATUS_DONE, report=text, completed_by_id=uid, completed_at=now, updated_at=now,
            taken_by_id=func.coalesce(KpRequest.taken_by_id, uid),
            taken_at=func.coalesce(KpRequest.taken_at, now),
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:
        raise await kp_requests._conflict(db, rid)

    # Идущий разбор допишет черновики после завершения — их никто не увидит.
    parsing = await _parsing_offers(db, rid)
    if parsing:
        await db.rollback()
        raise _unprocessable(f"Дождитесь разбора КП: {', '.join(parsing)}")

    drafts = await _draft_prices(db, rid)
    if drafts:
        await db.rollback()
        listed = "; ".join(f"«{name}» — {supplier}" for name, supplier in drafts[:20])
        more = f" и ещё {len(drafts) - 20}" if len(drafts) > 20 else ""
        raise _unprocessable(f"Не подтверждены цены ({len(drafts)}): {listed}{more}")

    await db.commit()
    await db.refresh(request)
    logger.info("kp_request_completed", request_id=rid, by=uid)
    return request


# ---------------------------------------------------------------------------
# Карточка запроса: КП и матрица
# ---------------------------------------------------------------------------

def offer_out(offer: KpOffer, names: dict) -> dict:
    return {
        "id": str(offer.id),
        "supplier_name": offer.supplier_name,
        "offer_date": offer.offer_date,
        "vat_mode": offer.vat_mode,
        "vat_rate": offer.vat_rate,
        "includes_materials": bool(offer.includes_materials),
        "file_name": offer.file_name,
        "mime_type": offer.mime_type,
        "size_bytes": offer.size_bytes,
        "has_file": bool(offer.storage_key),
        "parse_status": offer.parse_status,
        "parse_error": offer.parse_error,
        "parse_started_at": offer.parse_started_at,
        "parse_hints": offer.parse_hints,
        "created_by": offer.created_by,
        "created_by_name": names.get(offer.created_by),
        "created_at": offer.created_at,
    }


async def load_offers(db: AsyncSession, request_id: str) -> list[KpOffer]:
    return list((await db.execute(
        select(KpOffer)
        .where(KpOffer.request_id == request_id, KpOffer.deleted_at.is_(None))
        .order_by(KpOffer.created_at, KpOffer.id)
    )).scalars().all())


async def load_prices(db: AsyncSession, offers: list[KpOffer]) -> list[KpOfferPrice]:
    if not offers:
        return []
    return list((await db.execute(
        select(KpOfferPrice).where(KpOfferPrice.offer_id.in_([str(o.id) for o in offers]))
    )).scalars().all())


def permissions(request: KpRequest, current_user: dict) -> dict:
    production = is_production(current_user.get("role"))
    can_work = can_work_kp(request, current_user)
    return {
        "can_edit_offers": can_work and request.status in (STATUS_NEW, STATUS_IN_PROGRESS),
        "can_complete": can_work and request.status in (STATUS_NEW, STATUS_IN_PROGRESS),
        "can_select_offer": (
            (can_work and request.status == STATUS_IN_PROGRESS)
            or (not production and request.status in (STATUS_IN_PROGRESS, STATUS_DONE))
        ),
    }


async def offers_matrix(db: AsyncSession, request: KpRequest, items: list[KpRequestItem]) -> dict:
    """КП запроса и строки матрицы по позициям — три запроса на карточку, без N+1."""
    offers = await load_offers(db, str(request.id))
    await kp_parser.expire_abandoned(db, offers)
    prices = await load_prices(db, offers)
    by_item: dict[str, list[KpOfferPrice]] = {}
    for p in prices:
        by_item.setdefault(str(p.item_id), []).append(p)
    names = await owner_names([o.created_by for o in offers], db)
    return {
        "offers": [offer_out(o, names) for o in offers],
        "matrix": {str(i.id): kp_pricing.item_matrix(i, offers, by_item.get(str(i.id), [])) for i in items},
    }
