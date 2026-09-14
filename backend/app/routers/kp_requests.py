"""Запросы КП у отдела производства работ — HTTP-обвязка.

План: plans/2026-09-14-zapros-kp.md, фазы 2 и 4. Логика — `services/kp_requests.py`
(постановка, статусы, вложения автора) и `services/kp_offers.py` (КП, цены,
выбор, завершение); права — `utils/permissions.can_view_kp / can_work_kp /
can_manage_kp`.

Роутер подключается в `main.py` **без** `forbid_production_roles`: это
единственный, кроме входа, раздел отдела производства. Все его пути лежат под
префиксами `permissions.PRODUCTION_ALLOWED_PREFIXES` — тест перебора маршрутов
(`tests/test_kp_roles_access.py`) закрывает всё остальное.

Роль пользователя внутри роутера — **из БД**, а не из токена: токен живёт
сутками, а сменённая роль (снабжение → подрядчики) не должна ждать перелогина,
чтобы закрыть запросы прежней роли.
"""
from __future__ import annotations

import io
import json
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.schemas.kp_request import (
    KpCellOut,
    KpCompleteIn,
    KpCountersResponse,
    KpCreatePayload,
    KpCreateResponse,
    KpFilesResponse,
    KpOfferOut,
    KpOfferPatch,
    KpPreviewRequest,
    KpPriceIn,
    KpSelectOfferIn,
    KpPreviewResponse,
    KpRequestBrief,
    KpRequestDetail,
)
from app.services import kp_offers, kp_parser
from app.services import kp_requests as svc
from app.services import storage_service
from app.utils.auth import current_user_id, get_current_user, get_download_user
from app.utils.owner_names import owner_names
from app.utils.permissions import KP_CATEGORY_ROLE, is_production

router = APIRouter(tags=["kp-requests"])


async def _effective_user(payload: dict, db: AsyncSession) -> dict:
    """Пользователь с действующей ролью.

    Роль из БД; производственная роль токена побеждает непроизводственную роль
    базы — та же безопасная сторона, что у `forbid_production_roles`: понижение
    до производства закрывает продажи сразу, обратное — после перелогина.
    Деактивированный сотрудник — 401.
    """
    user = dict(payload)
    uid = current_user_id(payload)
    if uid is None:
        return user
    row = (await db.execute(select(User.role, User.is_active).where(User.id == uid))).one_or_none()
    if row is None:
        return user
    db_role, active = row
    if not active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Учётная запись отключена",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not (is_production(payload.get("role")) and not is_production(db_role)):
        user["role"] = db_role
    return user


async def get_kp_user(
    payload: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> dict:
    return await _effective_user(payload, db)


async def get_kp_download_user(
    payload: dict = Depends(get_download_user), db: AsyncSession = Depends(get_db),
) -> dict:
    return await _effective_user(payload, db)


def _content_disposition(filename: str) -> str:
    ascii_name = filename.encode("ascii", errors="replace").decode("ascii")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}"


async def _read_uploads(files: list[UploadFile]) -> list[tuple[str, bytes]]:
    out = []
    for f in files or []:
        out.append((f.filename or "file", await f.read()))
    return out


# --- Постановка --------------------------------------------------------------

@router.post("/kp-requests/preview", response_model=KpPreviewResponse)
async def preview_kp_request(
    body: KpPreviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_kp_user),
):
    """Как выделение разложится по запросам. Ничего не пишет."""
    svc.ensure_sales(current_user)
    doc, version, rows = await svc.load_document_rows(
        db, body.card_id, body.kind, body.version_id, current_user,
    )
    split = svc.split_selection(doc.row_format, rows, body.row_ids)
    counts = await svc.active_employees(db)

    def group(category: str) -> dict:
        role = KP_CATEGORY_ROLE[category]
        return {"category": category, "target_role": role,
                "employees": counts.get(role, 0), "items": split[category]}

    return {
        "version_id": str(version.id),
        "groups": {
            "material": group("material"),
            "work": group("work"),
            "unknown": {"category": "unknown", "items": split["unknown"]},
        },
        "skipped": split["skipped"],
        "missing_row_ids": split["missing"],
    }


@router.post("/kp-requests", response_model=KpCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_kp_requests(
    payload: str = Form(...),
    files: list[UploadFile] = File(default=[]),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_kp_user),
):
    """Создать по запросу на группу (материалы / работы) с вложениями автора."""
    svc.ensure_sales(current_user)
    try:
        data = KpCreatePayload.model_validate(json.loads(payload))
    except (ValueError, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Неверные данные запроса КП",
        )
    checked = svc.check_attachments(await _read_uploads(files))
    created = await svc.create_requests(
        db,
        card_id=data.card_id,
        kind=data.kind,
        version_id=data.version_id,
        author_comment=data.author_comment,
        groups=[g.model_dump() for g in data.groups],
        files=checked,
        current_user=current_user,
    )
    briefs = await svc.list_requests(db, current_user, card_id=data.card_id)
    ids = {str(r.id) for r in created}
    return {"requests": [b for b in briefs if b["id"] in ids]}


# --- Списки ------------------------------------------------------------------

@router.get("/kp-requests", response_model=list[KpRequestBrief])
async def list_kp_requests(
    card_id: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_kp_user),
):
    return await svc.list_requests(db, current_user, card_id=card_id, status_filter=status_filter)


@router.get("/kp-requests/mine", response_model=list[KpRequestBrief])
async def my_kp_requests(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_kp_user),
):
    """Производство — запросы своей роли; продажи — поставленные мной."""
    return await svc.list_requests(db, current_user, status_filter=status_filter, mine=True)


@router.get("/kp-requests/counters", response_model=KpCountersResponse)
async def kp_counters(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_kp_user),
):
    return await svc.counters(db, current_user)


@router.get("/kp-requests/{request_id}", response_model=KpRequestDetail)
async def get_kp_request(
    request_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_kp_user),
):
    request = await svc.get_visible(db, request_id, current_user)
    return await svc.detail(db, request, current_user)


# --- Статусы -----------------------------------------------------------------

@router.post("/kp-requests/{request_id}/take", response_model=KpRequestDetail)
async def take_kp_request(
    request_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_kp_user),
):
    request = await svc.take(db, request_id, current_user)
    return await svc.detail(db, request, current_user)


@router.post("/kp-requests/{request_id}/cancel", response_model=KpRequestDetail)
async def cancel_kp_request(
    request_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_kp_user),
):
    request = await svc.cancel(db, request_id, current_user)
    return await svc.detail(db, request, current_user)


@router.post("/kp-requests/{request_id}/reopen", response_model=KpRequestDetail)
async def reopen_kp_request(
    request_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_kp_user),
):
    request = await svc.reopen(db, request_id, current_user)
    return await svc.detail(db, request, current_user)


# --- Вложения автора ---------------------------------------------------------

@router.post(
    "/kp-requests/{request_id}/files",
    response_model=KpFilesResponse, status_code=status.HTTP_201_CREATED,
)
async def add_kp_request_files(
    request_id: str,
    files: list[UploadFile] = File(default=[]),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_kp_user),
):
    rows = await svc.add_files(db, request_id, await _read_uploads(files), current_user)
    names = await owner_names([r.uploaded_by for r in rows], db)
    return {"files": [svc.file_out(r, names) for r in rows]}


@router.delete("/kp-request-files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_kp_request_file(
    file_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_kp_user),
):
    await svc.delete_file(db, file_id, current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/kp-request-files/{file_id}/download")
async def download_kp_request_file(
    file_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_kp_download_user),
):
    """Скачать вложение. Токен — заголовком или `?token=` (ссылка из браузера)."""
    row, _request = await svc.get_file(db, file_id, current_user)
    data = await storage_service.load_bytes(row.storage_key)
    return StreamingResponse(
        io.BytesIO(data),
        media_type=row.mime_type or "application/octet-stream",
        headers={"Content-Disposition": _content_disposition(row.file_name)},
    )


# --- КП (фаза 4) -------------------------------------------------------------

@router.post(
    "/kp-requests/{request_id}/offers",
    response_model=KpOfferOut, status_code=status.HTTP_201_CREATED,
)
async def create_kp_offer(
    request_id: str,
    vat_mode: Optional[str] = Form(default=None),
    vat_rate: Optional[str] = Form(default=None),
    supplier_name: Optional[str] = Form(default=None),
    offer_date: Optional[str] = Form(default=None),
    includes_materials: bool = Form(default=False),
    file: Optional[UploadFile] = File(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_kp_user),
):
    """Загрузить КП (файл и условия). Новый запрос этим же берётся в работу."""
    upload = (file.filename or "file", await file.read()) if file is not None else None
    offer = await kp_offers.create_offer(
        db, request_id, current_user=current_user, supplier_name=supplier_name,
        offer_date=offer_date, vat_mode=vat_mode, vat_rate=vat_rate,
        includes_materials=includes_materials, file=upload,
    )
    names = await owner_names([offer.created_by], db)
    return kp_offers.offer_out(offer, names)


@router.patch("/kp-offers/{offer_id}", response_model=KpOfferOut)
async def update_kp_offer(
    offer_id: str,
    body: KpOfferPatch,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_kp_user),
):
    changes = {field: getattr(body, field) for field in body.model_fields_set}
    offer = await kp_offers.update_offer(db, offer_id, changes, current_user)
    names = await owner_names([offer.created_by], db)
    return kp_offers.offer_out(offer, names)


@router.delete("/kp-offers/{offer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_kp_offer(
    offer_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_kp_user),
):
    await kp_offers.delete_offer(db, offer_id, current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/kp-offers/{offer_id}/download")
async def download_kp_offer(
    offer_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_kp_download_user),
):
    """Скачать файл КП. Токен — заголовком или `?token=`."""
    offer = await kp_offers.offer_file(db, offer_id, current_user)
    data = await storage_service.load_bytes(offer.storage_key)
    return StreamingResponse(
        io.BytesIO(data),
        media_type=offer.mime_type or "application/octet-stream",
        headers={"Content-Disposition": _content_disposition(offer.file_name or "kp")},
    )


@router.post("/kp-offers/{offer_id}/parse", response_model=KpOfferOut)
async def reparse_kp_offer(
    offer_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_kp_user),
):
    """«Разобрать заново»: поставить ИИ-разбор файла КП в очередь (фаза 6).
    Ручные и подтверждённые цены повторный разбор не трогает."""
    offer = await kp_parser.restart(db, offer_id, current_user)
    names = await owner_names([offer.created_by], db)
    return kp_offers.offer_out(offer, names)


# --- Цены в КП ---------------------------------------------------------------

@router.put("/kp-offers/{offer_id}/prices/{item_id}", response_model=KpCellOut)
async def set_kp_offer_price(
    offer_id: str,
    item_id: str,
    body: KpPriceIn,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_kp_user),
):
    """Ручная цена позиции в КП — сразу подтверждена."""
    return await kp_offers.set_price(
        db, offer_id, item_id, price=body.price, unit=body.unit,
        includes_materials=body.includes_materials, current_user=current_user,
    )


@router.post("/kp-offers/{offer_id}/prices/{item_id}/confirm", response_model=KpCellOut)
async def confirm_kp_offer_price(
    offer_id: str,
    item_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_kp_user),
):
    return await kp_offers.confirm_price(db, offer_id, item_id, current_user)


@router.delete("/kp-offers/{offer_id}/prices/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_kp_offer_price(
    offer_id: str,
    item_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_kp_user),
):
    await kp_offers.delete_price(db, offer_id, item_id, current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/kp-request-items/{item_id}/selected-offer", response_model=KpRequestDetail)
async def select_kp_offer(
    item_id: str,
    body: KpSelectOfferIn,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_kp_user),
):
    """Отметить КП выбранным у позиции (`offer_id: null` — снять выбор)."""
    request = await kp_offers.select_offer(db, item_id, body.offer_id, current_user)
    return await svc.detail(db, request, current_user)


# --- Завершение --------------------------------------------------------------

@router.post("/kp-requests/{request_id}/complete", response_model=KpRequestDetail)
async def complete_kp_request(
    request_id: str,
    body: KpCompleteIn,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_kp_user),
):
    request = await kp_offers.complete(db, request_id, body.report, current_user)
    return await svc.detail(db, request, current_user)
