"""Запрос КП: постановка, позиции-снимки, вложения, статусы, чистка.

План: plans/2026-09-14-zapros-kp.md, фаза 2.

Правила, ради которых сервис устроен так, а не иначе:

* **Позиции — снимок.** Строки перечитываются на сервере из сохранённой версии
  документа (черновик не берётся), сворачиваются в позиции и копируются в
  `kp_request_items`. Правка документа запрос не меняет: поставщику отправлено
  конкретное, а `row_id` между стадиями не стабилен.
* **Ключ одинаковой позиции — тот же, что у свёртки дублей на экране**
  (`frontend/src/components/editor/collapse.ts`): тип + наименование + единица
  без учёта регистра и лишних пробелов, ё и е — разные буквы. Человек выделил
  одну свёрнутую строку — в запрос должна уйти одна позиция. Паритет закреплён
  общим файлом примеров `frontend/src/utils/collapseKey.fixtures.json`.
* **Вычет объём не увеличивает:** складываются только неотрицательные объёмы
  (правило №17 — строка-вычет стоимости не даёт).
* **Запрос адресован роли.** Нет ни одного активного сотрудника роли — запрос
  некому получить, отправка отклоняется целиком (422).
* **Смена статуса атомарна.** Проверка «из какого статуса» — в самом `UPDATE`,
  а не в прочитанном объекте: двое, нажавшие «Взять в работу» одновременно,
  оба прочли `new`, но строку обновит только первый.
* **Окончательное удаление чистит явно.** Каскад БД в тестах (SQLite без
  `foreign_keys`) не срабатывает, а файлы S3 каскадом не удаляются нигде —
  поэтому строки удаляются запросами, а префикс `kp/{request_id}/` — после
  коммита.
"""
from __future__ import annotations

import re
import uuid as _uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

import structlog
from fastapi import HTTPException, status
from sqlalchemy import and_, case, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.kp_request import (
    CATEGORIES, CATEGORY_MATERIAL, CATEGORY_WORK, SOURCE_KINDS, STATUS_CANCELLED,
    STATUS_DONE, STATUS_IN_PROGRESS, STATUS_NEW, STATUSES,
    KpOffer, KpOfferPrice, KpRequest, KpRequestFile, KpRequestItem,
)
from app.models.project import Project
from app.models.user import User
from app.models.workflow_card import WorkflowCard
from app.services import storage_service
from app.utils.auth import current_user_id
from app.utils.owner_names import owner_names
from app.utils.permissions import (
    KP_CATEGORY_ROLE, PRODUCTION_ROLES, ROLE_CONTRACTOR, ROLE_SUPPLY,
    can_manage_kp, can_view_kp, can_work_kp, is_production,
)
from app.utils.source_numbers import SOURCE_NO_HEADER

logger = structlog.get_logger()

# --- Вложения ---------------------------------------------------------------

# Лимит файла КП — свой, по спецификации (50 МБ): общий MAX_FILE_SIZE_MB задач
# на проде меньше (20 МБ в docker-compose.yml). Один на вложения и файлы КП.
KP_MAX_FILE_MB = 50
MAX_FILE_BYTES = KP_MAX_FILE_MB * 1024 * 1024
MAX_FILES = settings.MAX_FILES_PER_REQUEST


def too_large(name: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        detail=f"Файл «{name}» больше {KP_MAX_FILE_MB} МБ",
    )


def too_many_files() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"К запросу можно приложить не больше {MAX_FILES} файлов",
    )

# Тип файла определяется по расширению, а не по заголовку браузера: для .doc и
# .xls браузеры присылают что угодно, вплоть до application/octet-stream.
ATTACHMENT_TYPES = {
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}

ROLE_TITLES = {
    ROLE_SUPPLY: "Менеджер снабжения",
    ROLE_CONTRACTOR: "Менеджер по работе с подрядчиками",
}
CATEGORY_TITLES = {CATEGORY_MATERIAL: "материалам", CATEGORY_WORK: "работам"}

UNKNOWN = "unknown"

# Ширина колонок снимка (VARCHAR) — длиннее значение обрезается, а не роняет запись.
_UNIT_LEN = 64
_SHEET_LEN = 128
_SOURCE_NO_LEN = 64


@dataclass
class UploadedFile:
    """Файл из multipart, уже прочитанный и проверенный."""

    file_name: str
    mime_type: str
    data: bytes


def check_attachments(files: list[tuple[str, bytes]], existing: int = 0) -> list[UploadedFile]:
    """Проверить вложения автора: число, тип, размер. Ничего не пишет.

    Проверка идёт до любой записи: иначе запрос создался бы, а файл — нет.
    """
    if existing + len(files) > MAX_FILES:
        raise too_many_files()
    checked: list[UploadedFile] = []
    for name, data in files:
        name = (name or "file").replace("\\", "/").split("/")[-1] or "file"
        ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
        mime = ATTACHMENT_TYPES.get(ext)
        if mime is None:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=(
                    f"Тип файла «{name}» не поддерживается. "
                    "Допустимые форматы: PDF, XLSX, XLS, DOC, DOCX, JPG, PNG"
                ),
            )
        if len(data) > MAX_FILE_BYTES:
            raise too_large(name)
        checked.append(UploadedFile(file_name=name[:255], mime_type=mime, data=data))
    return checked


# ---------------------------------------------------------------------------
# Ключ свёртки — зеркало collapse.ts
# ---------------------------------------------------------------------------

# JS `\s` + BOM: `trim()` и `/\s+/g` в браузере считают пробелом и U+FEFF.
_WS = re.compile(r"[\s﻿]+")


def _js_string(value: Any) -> str:
    """`String(value ?? '')` из JS: целое число без «.0», null — пусто."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _norm(value: Any) -> str:
    return _WS.sub(" ", _js_string(value)).strip(" ").lower()


def collapse_key(name: Any, unit: Any, kind: Optional[str]) -> Optional[str]:
    """Ключ одинаковой позиции — ровно как `collapseKey` в `collapse.ts`.

    Раздел и строка без наименования ключа не имеют (`None`).
    """
    if kind == "section":
        return None
    normalized = _norm(name)
    if normalized == "":
        return None
    return f"{kind or ''}|{normalized}|{_norm(unit)}"


# ---------------------------------------------------------------------------
# Строка документа → позиция
# ---------------------------------------------------------------------------

# Колонки плоского документа опознаются теми же словами, что в genericAdapter.
_GENERIC_TYPE_COL = "Тип"
_GENERIC_NAME_COL = "Наименование"
_UNIT_KEYWORDS = ("ед. изм", "ед.изм", "ед изм", "единица")
_QTY_KEYWORDS = ("кол-во", "количество", "кол.", "объем", "объём", "кол")

_GENERIC_KIND = {"Работа": "work", "Материал": "material", "Раздел": "section"}
_ESTIMATE_KIND = {
    "Работа": "work", "work": "work",
    "Материал": "material", "material": "material",
    "Раздел": "section", "section": "section",
}


def _matches(column: str, keywords: Iterable[str]) -> bool:
    lower = str(column).strip().lower()
    return any(lower.startswith(k) for k in keywords)


def _number(value: Any) -> Optional[float]:
    """Объём числом; текст вроде «по проекту» числом не становится."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(" ", "").replace("\xa0", "").replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _row_key(row: dict, row_format: str) -> Optional[str]:
    key = row.get("row_id") if row_format == "generic" else row.get("id")
    return str(key) if key is not None else None


def _position(row: dict, row_format: str) -> dict:
    """Тип, наименование, единица, объём, лист и № исходной сметы строки."""
    if row_format == "generic":
        cells = row.get("cells") if isinstance(row.get("cells"), dict) else {}
        kind = _GENERIC_KIND.get(str(cells.get(_GENERIC_TYPE_COL) or "").strip())
        if _GENERIC_NAME_COL in cells:
            name = cells.get(_GENERIC_NAME_COL)
        else:
            name = next(
                (v for k, v in cells.items() if str(k).strip().lower().startswith("наименование")),
                None,
            )
        unit = next((v for k, v in cells.items() if _matches(k, _UNIT_KEYWORDS)), None)
        qty = next((v for k, v in cells.items() if _matches(k, _QTY_KEYWORDS)), None)
        source_no = cells.get(SOURCE_NO_HEADER)
    else:
        kind = _ESTIMATE_KIND.get(str(row.get("type") or "").strip())
        name = row.get("name")
        unit = row.get("unit")
        qty = row.get("qty")
        source_no = row.get("source_no")
    return {
        "kind": kind,
        "name": _js_string(name).strip(),
        "unit": _js_string(unit).strip(),
        "qty": _number(qty),
        "sheet": _js_string(row.get("sheet")).strip() or None,
        "source_no": _js_string(source_no).strip() or None,
    }


def _same_or_none(values: list[Optional[str]]) -> Optional[str]:
    first = values[0]
    return first if all(v == first for v in values) else None


def _group_to_item(members: list[tuple[str, dict]], item_type: Optional[str]) -> dict:
    first = members[0][1]
    qtys = [p["qty"] for _, p in members if p["qty"] is not None and p["qty"] >= 0]
    sheet = _same_or_none([p["sheet"] for _, p in members])
    source_no = _same_or_none([p["source_no"] for _, p in members])
    return {
        "item_type": item_type,
        "name": first["name"],
        "unit": (first["unit"] or None) and first["unit"][:_UNIT_LEN],
        # Сумма как в `roundSum` фронта: шесть знаков гасят плавающий хвост.
        "qty": round(sum(qtys), 6) if qtys else None,
        "sheet": sheet[:_SHEET_LEN] if sheet else None,
        "source_no": source_no[:_SOURCE_NO_LEN] if source_no else None,
        "source_row_ids": [key for key, _ in members],
    }


def _selected_positions(
    row_format: str, rows: list, row_ids: Iterable[str]
) -> tuple[list[tuple[str, dict]], int, list[str]]:
    """Выделенные строки в порядке документа → (позиции, пропущено, не найдено)."""
    wanted = {str(r) for r in row_ids}
    found: set[str] = set()
    positions: list[tuple[str, dict]] = []
    skipped = 0
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        key = _row_key(row, row_format)
        if key is None or key not in wanted or key in found:
            continue
        found.add(key)
        pos = _position(row, row_format)
        if pos["kind"] == "section" or not pos["name"]:
            skipped += 1
            continue
        positions.append((key, pos))
    missing = [r for r in dict.fromkeys(str(x) for x in row_ids) if r not in found]
    return positions, skipped, missing


def _group(positions: list[tuple[str, dict]], kind_of) -> list[tuple[str, list]]:
    groups: dict[str, list] = {}
    for key, pos in positions:
        ck = collapse_key(pos["name"], pos["unit"], kind_of(pos))
        if ck is None:  # раздел/пустое уже отброшены; страховка
            continue
        groups.setdefault(ck, []).append((key, pos))
    return list(groups.items())


def split_selection(row_format: str, rows: list, row_ids: Iterable[str]) -> dict:
    """Разбить выделение на материалы, работы и позиции без типа. Ничего не пишет."""
    positions, skipped, missing = _selected_positions(row_format, rows, row_ids)
    result: dict[str, Any] = {CATEGORY_MATERIAL: [], CATEGORY_WORK: [], UNKNOWN: []}
    for _, members in _group(positions, lambda p: p["kind"]):
        kind = members[0][1]["kind"]
        bucket = kind if kind in CATEGORIES else UNKNOWN
        result[bucket].append(_group_to_item(members, kind if kind in CATEGORIES else None))
    for bucket in (CATEGORY_MATERIAL, CATEGORY_WORK, UNKNOWN):
        for index, item in enumerate(result[bucket]):
            item["position"] = index
    result["skipped"] = skipped
    result["missing"] = missing
    return result


def build_items(row_format: str, rows: list, row_ids: Iterable[str], category: str) -> list[dict]:
    """Позиции запроса категории `category` из выделенных строк.

    Позиция без типа становится позицией категории — её отнёс сюда человек.
    Позиция с типом другой категории — ошибка клиента (422), а не повод молча
    отправить работу снабженцу.
    """
    positions, _skipped, missing = _selected_positions(row_format, rows, row_ids)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Часть выделенных строк не найдена в документе — обновите страницу и выделите заново",
        )
    for _, pos in positions:
        if pos["kind"] in CATEGORIES and pos["kind"] != category:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Позиция «{pos['name']}» — не из группы по {CATEGORY_TITLES[category]}"
                ),
            )
    items = [_group_to_item(members, category) for _, members in _group(positions, lambda p: category)]
    for index, item in enumerate(items):
        item["position"] = index
    return items


# ---------------------------------------------------------------------------
# Постановка
# ---------------------------------------------------------------------------

def ensure_source_kind(kind: str) -> None:
    if kind not in SOURCE_KINDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Запрос КП ставится из перечня, полноты, сметы или оптимизации",
        )


def ensure_sales(current_user: dict) -> None:
    if is_production(current_user.get("role")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Действие доступно только отделу продаж",
        )


async def active_employees(db: AsyncSession) -> dict[str, int]:
    """Активных сотрудников по ролям производства: {роль: число}."""
    rows = (await db.execute(
        select(User.role, func.count())
        .where(User.role.in_(PRODUCTION_ROLES), User.is_active.is_(True))
        .group_by(User.role)
    )).all()
    counts = {role: 0 for role in PRODUCTION_ROLES}
    counts.update({role: int(n) for role, n in rows})
    return counts


async def load_document_rows(db: AsyncSession, card_id: str, kind: str, version_id: Optional[str], current_user: dict):
    """Сохранённые строки документа (без черновика) и сама версия."""
    from app.services import document_service as docs

    ensure_source_kind(kind)
    doc = await docs.resolve_document(db, card_id, kind, current_user)
    version = docs.pick_version(doc, version_id)
    return doc, version, docs.read_rows(doc, version)


async def create_requests(
    db: AsyncSession,
    *,
    card_id: str,
    kind: str,
    version_id: Optional[str],
    author_comment: Optional[str],
    groups: list[dict],
    files: list[UploadedFile],
    current_user: dict,
) -> list[KpRequest]:
    """Создать по запросу на группу. Всё или ничего: одна транзакция."""
    ensure_sales(current_user)
    doc, version, rows = await load_document_rows(db, card_id, kind, version_id, current_user)

    groups = [g for g in groups if g.get("row_ids")]
    if not groups:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Не выбрано ни одной позиции",
        )
    seen_categories: set[str] = set()
    seen_rows: set[str] = set()
    for g in groups:
        if g["category"] in seen_categories:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Группа позиций повторяется",
            )
        seen_categories.add(g["category"])
        for rid in g["row_ids"]:
            if str(rid) in seen_rows:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Одна и та же строка отнесена к двум группам",
                )
            seen_rows.add(str(rid))

    built = []
    for g in groups:
        items = build_items(doc.row_format, rows, g["row_ids"], g["category"])
        if not items:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"В группе по {CATEGORY_TITLES[g['category']]} нет позиций с наименованием",
            )
        built.append((g["category"], items))

    counts = await active_employees(db)
    for category, _ in built:
        role = KP_CATEGORY_ROLE[category]
        if counts.get(role, 0) == 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Нет ни одного активного сотрудника с ролью «{ROLE_TITLES[role]}» — "
                    f"запрос по {CATEGORY_TITLES[category]} некому получить"
                ),
            )

    uid = current_user_id(current_user)
    comment = (author_comment or "").strip() or None
    now = datetime.now(timezone.utc)
    created: list[KpRequest] = []
    uploaded_keys: list[str] = []
    try:
        for category, items in built:
            request = KpRequest(
                id=str(_uuid.uuid4()),
                project_id=str(doc.card.project_id),
                card_id=str(doc.card.id),
                source_kind=kind,
                source_task_id=str(doc.task.id),
                source_version_id=str(version.id),
                category=category,
                target_role=KP_CATEGORY_ROLE[category],
                status=STATUS_NEW,
                author_id=uid,
                author_comment=comment,
                created_at=now,
                updated_at=now,
            )
            db.add(request)
            for item in items:
                db.add(KpRequestItem(id=str(_uuid.uuid4()), request_id=request.id, **item))
            # Вложения — копией на каждый запрос: у запросов разные исполнители и
            # своя судьба (отмена, удаление), общий объект S3 осиротел бы.
            for f in files:
                key = storage_service.build_kp_key(request.id, "files", f.file_name)
                await storage_service.put_object(key, f.data, f.mime_type)
                uploaded_keys.append(key)
                db.add(KpRequestFile(
                    id=str(_uuid.uuid4()), request_id=request.id, file_name=f.file_name,
                    mime_type=f.mime_type, size_bytes=len(f.data), storage_key=key,
                    uploaded_by=uid, created_at=now,
                ))
            created.append(request)
        await db.commit()
    except Exception:
        await db.rollback()
        for key in uploaded_keys:
            await storage_service.delete_key_safe(key)
        raise

    logger.info(
        "kp_requests_created",
        card_id=str(doc.card.id), kind=kind,
        requests=[(r.category, len(items)) for r, (_, items) in zip(created, built)],
        files=len(files),
    )
    return created


# ---------------------------------------------------------------------------
# Чтение
# ---------------------------------------------------------------------------

def _not_found() -> HTTPException:
    # Чужой запрос неотличим от несуществующего.
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Запрос КП не найден")


def _valid_uuid(value: str) -> bool:
    try:
        _uuid.UUID(str(value))
        return True
    except (TypeError, ValueError):
        return False


async def get_visible(db: AsyncSession, request_id: str, current_user: dict) -> KpRequest:
    if not _valid_uuid(request_id):
        raise _not_found()
    request = await db.get(KpRequest, str(request_id))
    if request is None or request.deleted_at is not None or not can_view_kp(request, current_user):
        raise _not_found()
    return request


def _visible_query(current_user: dict):
    """Запросы, видимые пользователю, у живых карточек и проектов."""
    query = (
        select(KpRequest, Project.name, WorkflowCard.name)
        .join(WorkflowCard, WorkflowCard.id == KpRequest.card_id)
        .join(Project, Project.id == KpRequest.project_id)
        .where(
            KpRequest.deleted_at.is_(None),
            WorkflowCard.deleted_at.is_(None),
            Project.deleted_at.is_(None),
        )
    )
    role = current_user.get("role")
    if is_production(role):
        query = query.where(KpRequest.target_role == role)
    return query


def ensure_status_filter(value: Optional[str]) -> None:
    if value is not None and value not in STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Неизвестный статус запроса",
        )


async def _counts(db: AsyncSession, model, request_ids: list[str], extra=None) -> dict[str, int]:
    if not request_ids:
        return {}
    query = (
        select(model.request_id, func.count())
        .where(model.request_id.in_(request_ids))
        .group_by(model.request_id)
    )
    if extra is not None:
        query = query.where(extra)
    return {str(rid): int(n) for rid, n in (await db.execute(query)).all()}


async def briefs(db: AsyncSession, rows: list[tuple]) -> list[dict]:
    """(запрос, имя проекта, имя карточки) → краткие записи. Без N+1: счётчики
    и имена — тремя запросами на весь список."""
    ids = [str(r.id) for r, _, _ in rows]
    items = await _counts(db, KpRequestItem, ids)
    files = await _counts(db, KpRequestFile, ids, KpRequestFile.deleted_at.is_(None))
    names = await owner_names(
        [uid for r, _, _ in rows for uid in (r.author_id, r.taken_by_id, r.completed_by_id)], db,
    )
    return [
        _brief(r, project_name, card_name, names, items.get(str(r.id), 0), files.get(str(r.id), 0))
        for r, project_name, card_name in rows
    ]


def _brief(r: KpRequest, project_name, card_name, names, items_count, files_count) -> dict:
    return {
        "id": str(r.id),
        "project_id": str(r.project_id),
        "project_name": project_name,
        "card_id": str(r.card_id),
        "card_name": card_name,
        "source_kind": r.source_kind,
        "category": r.category,
        "target_role": r.target_role,
        "status": r.status,
        "author_id": r.author_id,
        "author_name": names.get(r.author_id),
        "author_comment": r.author_comment,
        "taken_by_id": r.taken_by_id,
        "taken_by_name": names.get(r.taken_by_id),
        "taken_at": r.taken_at,
        "completed_by_id": r.completed_by_id,
        "completed_by_name": names.get(r.completed_by_id),
        "completed_at": r.completed_at,
        "applied_at": r.applied_at,
        "items_count": items_count,
        "files_count": files_count,
        "created_at": r.created_at,
        "updated_at": r.updated_at,
    }


async def list_requests(
    db: AsyncSession, current_user: dict, *, card_id: Optional[str] = None,
    status_filter: Optional[str] = None, mine: bool = False, limit: int = 500,
) -> list[dict]:
    ensure_status_filter(status_filter)
    query = _visible_query(current_user)
    if card_id is not None:
        if not _valid_uuid(card_id):
            return []
        query = query.where(KpRequest.card_id == card_id)
    if status_filter is not None:
        query = query.where(KpRequest.status == status_filter)
    if mine and not is_production(current_user.get("role")):
        # У продаж «мои» — поставленные мной; у производства — адресованные роли.
        query = query.where(KpRequest.author_id == current_user_id(current_user))
    rows = (await db.execute(query.order_by(KpRequest.created_at.desc()).limit(limit))).all()
    return await briefs(db, [tuple(r) for r in rows])


async def counters(db: AsyncSession, current_user: dict) -> dict:
    base = _visible_query(current_user).with_only_columns(KpRequest.id)
    role = current_user.get("role")
    if is_production(role):
        new = (await db.execute(
            select(func.count()).select_from(base.where(KpRequest.status == STATUS_NEW).subquery())
        )).scalar() or 0
        return {"new": int(new), "done_not_applied": {}}
    sub = base.where(KpRequest.status == STATUS_DONE, KpRequest.applied_at.is_(None)) \
        .with_only_columns(KpRequest.card_id).subquery()
    rows = (await db.execute(select(sub.c.card_id, func.count()).group_by(sub.c.card_id))).all()
    return {"new": 0, "done_not_applied": {str(card): int(n) for card, n in rows}}


def file_out(f: KpRequestFile, names: dict) -> dict:
    return {
        "id": str(f.id),
        "file_name": f.file_name,
        "mime_type": f.mime_type,
        "size_bytes": f.size_bytes,
        "uploaded_by": f.uploaded_by,
        "uploaded_by_name": names.get(f.uploaded_by),
        "created_at": f.created_at,
    }


async def detail(db: AsyncSession, request: KpRequest, current_user: dict) -> dict:
    project = await db.get(Project, str(request.project_id))
    card = await db.get(WorkflowCard, str(request.card_id))
    items = (await db.execute(
        select(KpRequestItem).where(KpRequestItem.request_id == request.id)
        .order_by(KpRequestItem.position)
    )).scalars().all()
    files = (await db.execute(
        select(KpRequestFile)
        .where(KpRequestFile.request_id == request.id, KpRequestFile.deleted_at.is_(None))
        .order_by(KpRequestFile.created_at, KpRequestFile.file_name)
    )).scalars().all()
    names = await owner_names(
        [request.author_id, request.taken_by_id, request.completed_by_id]
        + [f.uploaded_by for f in files],
        db,
    )
    # КП и матрица цен (фаза 4). Импорт здесь: kp_offers сам опирается на этот модуль.
    from app.services import kp_offers

    offers = await kp_offers.offers_matrix(db, request, list(items))
    matrix = offers["matrix"]
    out = _brief(
        request, project.name if project else None, card.name if card else None,
        names, len(items), len(files),
    )
    out.update({
        "source_task_id": request.source_task_id,
        "source_version_id": request.source_version_id,
        "report": request.report,
        "pricelist_status": request.pricelist_status,
        "pricelist_summary": request.pricelist_summary,
        "pricelist_error": request.pricelist_error,
        "pricelist_written_at": request.pricelist_written_at,
        "applied_version_id": request.applied_version_id,
        "items": [
            {
                "id": str(i.id), "position": i.position, "item_type": i.item_type,
                "name": i.name, "unit": i.unit, "qty": i.qty, "sheet": i.sheet,
                "source_no": i.source_no, "source_row_ids": list(i.source_row_ids or []),
                "selected_offer_id": i.selected_offer_id,
                **matrix[str(i.id)],
            }
            for i in items
        ],
        "files": [file_out(f, names) for f in files],
        "offers": offers["offers"],
        "permissions": {
            "can_work": can_work_kp(request, current_user),
            "can_manage": can_manage_kp(request, current_user),
            "can_edit_files": not is_production(current_user.get("role")),
            **kp_offers.permissions(request, current_user),
        },
    })
    return out


# ---------------------------------------------------------------------------
# Статусы
# ---------------------------------------------------------------------------

_STATUS_CONFLICT = {
    STATUS_NEW: "Запрос ещё не взят в работу",
    STATUS_DONE: "Запрос уже завершён",
    STATUS_CANCELLED: "Запрос отменён",
}


async def _conflict(db: AsyncSession, request_id: str) -> HTTPException:
    """409 с актуальным состоянием. Читаем колонками — объект сессии мог устареть."""
    row = (await db.execute(
        select(KpRequest.status, KpRequest.taken_by_id).where(KpRequest.id == request_id)
    )).one_or_none()
    await db.rollback()
    if row is None:
        return _not_found()
    current, taken_by = row
    if current == STATUS_IN_PROGRESS:
        names = await owner_names([taken_by], db) if taken_by else {}
        who = names.get(taken_by)
        message = f"Запрос уже взят в работу: {who}" if who else "Запрос уже в работе"
    else:
        message = _STATUS_CONFLICT.get(current, "Состояние запроса изменилось")
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)


async def _transition(db: AsyncSession, request: KpRequest, where, values: dict) -> KpRequest:
    request_id = str(request.id)
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(KpRequest)
        .where(KpRequest.id == request_id, where)
        .values(updated_at=now, **values)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:
        raise await _conflict(db, request_id)
    await db.commit()
    await db.refresh(request)
    return request


async def take(db: AsyncSession, request_id: str, current_user: dict) -> KpRequest:
    """«Взять в работу»: атомарно `new → in_progress`, кто взял — подписью."""
    request = await get_visible(db, request_id, current_user)
    if not can_work_kp(request, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Взять запрос в работу может сотрудник отдела производства работ",
        )
    return await _transition(
        db, request, KpRequest.status == STATUS_NEW,
        {"status": STATUS_IN_PROGRESS, "taken_by_id": current_user_id(current_user),
         "taken_at": datetime.now(timezone.utc)},
    )


def _ensure_manage(request: KpRequest, current_user: dict, action: str) -> None:
    if not can_manage_kp(request, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{action} запрос может его автор или руководитель отдела продаж",
        )


async def cancel(db: AsyncSession, request_id: str, current_user: dict) -> KpRequest:
    request = await get_visible(db, request_id, current_user)
    _ensure_manage(request, current_user, "Отменить")
    return await _transition(
        db, request, KpRequest.status.in_((STATUS_NEW, STATUS_IN_PROGRESS)),
        {"status": STATUS_CANCELLED},
    )


async def reopen(db: AsyncSession, request_id: str, current_user: dict) -> KpRequest:
    """Вернуть в работу завершённый или отменённый запрос.

    Отменённый, который никто не брал, возвращается новым — иначе он висел бы
    «в работе» без исполнителя.
    """
    request = await get_visible(db, request_id, current_user)
    _ensure_manage(request, current_user, "Вернуть в работу")
    return await _transition(
        db, request, KpRequest.status.in_((STATUS_DONE, STATUS_CANCELLED)),
        {
            "status": case(
                (and_(KpRequest.status == STATUS_CANCELLED, KpRequest.taken_by_id.is_(None)), STATUS_NEW),
                else_=STATUS_IN_PROGRESS,
            ),
            "completed_by_id": None,
            "completed_at": None,
        },
    )


# ---------------------------------------------------------------------------
# Вложения
# ---------------------------------------------------------------------------

async def add_files(
    db: AsyncSession, request_id: str, files: list[tuple[str, bytes]], current_user: dict,
) -> list[KpRequestFile]:
    request = await get_visible(db, request_id, current_user)
    ensure_sales(current_user)
    existing = (await db.execute(
        select(func.count()).select_from(KpRequestFile)
        .where(KpRequestFile.request_id == request.id, KpRequestFile.deleted_at.is_(None))
    )).scalar() or 0
    if not files:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Файлы не выбраны")
    checked = check_attachments(files, existing=int(existing))
    uid = current_user_id(current_user)
    rows: list[KpRequestFile] = []
    keys: list[str] = []
    try:
        for f in checked:
            key = storage_service.build_kp_key(request.id, "files", f.file_name)
            await storage_service.put_object(key, f.data, f.mime_type)
            keys.append(key)
            row = KpRequestFile(
                id=str(_uuid.uuid4()), request_id=request.id, file_name=f.file_name,
                mime_type=f.mime_type, size_bytes=len(f.data), storage_key=key,
                uploaded_by=uid, created_at=datetime.now(timezone.utc),
            )
            db.add(row)
            rows.append(row)
        await db.commit()
    except Exception:
        await db.rollback()
        for key in keys:
            await storage_service.delete_key_safe(key)
        raise
    return rows


async def get_file(db: AsyncSession, file_id: str, current_user: dict) -> tuple[KpRequestFile, KpRequest]:
    if not _valid_uuid(file_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")
    row = await db.get(KpRequestFile, str(file_id))
    if row is None or row.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")
    try:
        request = await get_visible(db, row.request_id, current_user)
    except HTTPException:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")
    return row, request


async def delete_file(db: AsyncSession, file_id: str, current_user: dict) -> None:
    row, _request = await get_file(db, file_id, current_user)
    ensure_sales(current_user)
    key = row.storage_key
    await db.delete(row)
    await db.commit()
    await storage_service.delete_key_safe(key)


# ---------------------------------------------------------------------------
# Окончательное удаление карточек и проектов
# ---------------------------------------------------------------------------

async def _purge(db: AsyncSession, condition) -> list[str]:
    ids = [str(i) for i in (await db.execute(select(KpRequest.id).where(condition))).scalars().all()]
    if not ids:
        return []
    offer_ids = select(KpOffer.id).where(KpOffer.request_id.in_(ids))
    item_ids = select(KpRequestItem.id).where(KpRequestItem.request_id.in_(ids))
    for stmt in (
        delete(KpOfferPrice).where(
            KpOfferPrice.offer_id.in_(offer_ids) | KpOfferPrice.item_id.in_(item_ids)
        ),
        delete(KpRequestItem).where(KpRequestItem.request_id.in_(ids)),
        delete(KpOffer).where(KpOffer.request_id.in_(ids)),
        delete(KpRequestFile).where(KpRequestFile.request_id.in_(ids)),
        delete(KpRequest).where(KpRequest.id.in_(ids)),
    ):
        await db.execute(stmt.execution_options(synchronize_session=False))
    return ids


async def purge_for_cards(db: AsyncSession, card_ids: list[str]) -> list[str]:
    """Удалить запросы карточек со всеми строками. Коммит — у вызывающего;
    файлы S3 — `delete_storage` после коммита. Возвращает id запросов."""
    ids = [str(c) for c in card_ids if c]
    if not ids:
        return []
    return await _purge(db, KpRequest.card_id.in_(ids))


async def purge_for_projects(db: AsyncSession, project_ids: list[str]) -> list[str]:
    ids = [str(p) for p in project_ids if p]
    if not ids:
        return []
    return await _purge(db, KpRequest.project_id.in_(ids))


async def delete_storage(request_ids: list[str]) -> None:
    """Файлы запросов в S3. После коммита и без исключений: удаление в базе уже
    случилось, сбой хранилища его не отменяет — остаток виден в логе."""
    for rid in request_ids:
        try:
            await storage_service.delete_prefix(storage_service.kp_prefix(rid))
        except storage_service.StorageError:
            logger.warning("kp_storage_cleanup_failed", request_id=rid)
