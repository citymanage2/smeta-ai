"""Запрос КП: модель, постановка, вложения, доступ (план 2026-09-14-zapros-kp.md, фаза 2).

Покрывает критерии спецификации 4–14 в части сервера:
* выделение делится на материалы (снабжение) и работы (подрядчики), позицию без
  типа распределяет человек; разделы и безымянные строки не попадают;
* одинаковые позиции — одна позиция запроса, ключ как у свёртки дублей на
  экране (общий файл примеров с фронтом), вычеты объём не увеличивают;
* нет активных сотрудников роли — отправка невозможна (422);
* позиции — снимок, правка документа запрос не меняет;
* производство видит только запросы своей роли, чужой — 404;
* «Взять в работу» атомарно: второй получает 409;
* окончательное удаление карточки/проекта удаляет запросы и их файлы в S3.
"""
import json
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.models.estimate_version import EstimateVersion
from app.models.kp_request import (
    KpOffer, KpOfferPrice, KpRequest, KpRequestFile, KpRequestItem,
)
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.models.workflow_card import WorkflowCard
from app.services import kp_requests as kp
from app.services import storage_service
from app.utils import permissions as perm
from app.utils.auth import create_access_token, hash_password

FIXTURES = (
    Path(__file__).resolve().parents[2]
    / "frontend" / "src" / "utils" / "collapseKey.fixtures.json"
)

PDF = ("spec.pdf", b"%PDF-1.4 spec", "application/pdf")
DOCX = (
    "tz.docx", b"PK docx",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
)


# bcrypt медленный: один хэш на все фикстуры файла.
_PASSWORD_HASH = hash_password("x1234")


def _auth(user_id: int, role: str) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id, role, f'u{user_id}')}"}


# ---------------------------------------------------------------------------
# Ключ свёртки — общий с фронтом
# ---------------------------------------------------------------------------

def test_collapse_key_matches_frontend_fixtures():
    if not FIXTURES.exists():  # pragma: no cover — сборка бэкенда без фронта
        pytest.skip("нет файла примеров фронта")
    cases = json.loads(FIXTURES.read_text(encoding="utf-8"))["cases"]
    assert len(cases) >= 10
    for case in cases:
        assert kp.collapse_key(case["name"], case["unit"], case["kind"]) == case["key"], case


def test_yolka_and_elka_are_different_positions_like_on_screen():
    """`collapse.ts` не меняет ё на е — сервер тоже: иначе на экране две строки,
    а в запросе одна."""
    assert kp.collapse_key("Ёлка", "шт", "material") != kp.collapse_key("Елка", "шт", "material")


# ---------------------------------------------------------------------------
# Разбор выделения (чистая логика)
# ---------------------------------------------------------------------------

def _g(row_id, kind, name, unit="м2", qty=1, sheet=None, source_no=None, **extra):
    cells = {"Тип": kind, "Наименование": name, "Ед. изм.": unit, "Кол-во": qty}
    if source_no is not None:
        cells = {"№ в исходной смете": source_no, **cells}
    cells.update(extra)
    row = {"row_id": row_id, "cells": cells}
    if sheet is not None:
        row["sheet"] = sheet
    return row


def test_split_selection_mixed_generic():
    rows = [
        _g("r1", "Работа", "Штукатурка стен", "м2", 10),
        _g("r2", "Материал", "Штукатурка гипсовая", "кг", 300),
        _g("r3", "", "Непонятная позиция", "шт", 2),
        _g("r4", "Работа", "Не выделена", "м2", 5),
    ]
    split = kp.split_selection("generic", rows, ["r1", "r2", "r3"])
    assert [i["name"] for i in split["work"]] == ["Штукатурка стен"]
    assert [i["name"] for i in split["material"]] == ["Штукатурка гипсовая"]
    assert [i["name"] for i in split["unknown"]] == ["Непонятная позиция"]
    assert split["material"][0]["unit"] == "кг"
    assert split["material"][0]["qty"] == 300
    assert split["material"][0]["source_row_ids"] == ["r2"]


def test_duplicates_merge_with_sum_and_negative_not_added():
    rows = [
        _g("r1", "Работа", "Штукатурка стен", "м2", 10, sheet="Лист1"),
        _g("r2", "Работа", "  штукатурка   СТЕН ", "М2", 5.5, sheet="Лист1"),
        _g("r3", "Работа", "Штукатурка стен", "м2", -2, sheet="Лист1"),
        _g("r4", "Работа", "Штукатурка стен", "м3", 1, sheet="Лист1"),
    ]
    split = kp.split_selection("generic", rows, ["r1", "r2", "r3", "r4"])
    work = split["work"]
    assert len(work) == 2
    assert work[0]["name"] == "Штукатурка стен"
    assert work[0]["qty"] == 15.5
    assert work[0]["source_row_ids"] == ["r1", "r2", "r3"]
    assert work[0]["sheet"] == "Лист1"
    assert work[1]["unit"] == "м3"


def test_yolka_elka_not_merged_in_selection():
    rows = [
        _g("r1", "Материал", "Ёлка", "шт", 1),
        _g("r2", "Материал", "Елка", "шт", 2),
    ]
    split = kp.split_selection("generic", rows, ["r1", "r2"])
    assert len(split["material"]) == 2


def test_sections_and_empty_names_dropped():
    rows = [
        {"id": "s1", "type": "section", "name": "Раздел 1. Кровля"},
        {"id": "e1", "type": "work", "name": "   ", "unit": "м2", "qty": 1},
        {"id": "w1", "type": "work", "name": "Монтаж кровли", "unit": "м2", "qty": 100},
    ]
    split = kp.split_selection("estimate", rows, ["s1", "e1", "w1"])
    assert [i["name"] for i in split["work"]] == ["Монтаж кровли"]
    assert split["material"] == [] and split["unknown"] == []
    assert split["skipped"] == 2


def test_source_no_and_sheet_kept_only_when_same():
    rows = [
        {"id": "a", "type": "material", "name": "Кабель", "unit": "м", "qty": 10,
         "sheet": "ОПС", "source_no": "12"},
        {"id": "b", "type": "material", "name": "Кабель", "unit": "м", "qty": 5,
         "sheet": "СОТ", "source_no": "12"},
        {"id": "c", "type": "Материал", "name": "Датчик", "unit": "шт", "qty": 3,
         "sheet": "ОПС", "source_no": "7"},
    ]
    split = kp.split_selection("estimate", rows, ["a", "b", "c"])
    cable, sensor = split["material"]
    assert cable["qty"] == 15
    assert cable["sheet"] is None
    assert cable["source_no"] == "12"
    assert sensor["sheet"] == "ОПС" and sensor["source_no"] == "7"


def test_only_negative_qty_gives_empty_qty():
    rows = [{"id": "a", "type": "work", "name": "Вычет", "unit": "м", "qty": -3}]
    split = kp.split_selection("estimate", rows, ["a"])
    assert split["work"][0]["qty"] is None


def test_generic_qty_text_parsed():
    rows = [_g("r1", "Материал", "Песок", "м3", "1 200,5")]
    split = kp.split_selection("generic", rows, ["r1"])
    assert split["material"][0]["qty"] == 1200.5


def test_items_ordered_by_document_not_by_selection():
    rows = [
        _g("r1", "Работа", "Первая", "м2", 1),
        _g("r2", "Работа", "Вторая", "м2", 1),
    ]
    split = kp.split_selection("generic", rows, ["r2", "r1"])
    assert [i["name"] for i in split["work"]] == ["Первая", "Вторая"]


# ---------------------------------------------------------------------------
# Окружение API
# ---------------------------------------------------------------------------

_MODELS = (KpOfferPrice, KpRequestItem, KpOffer, KpRequestFile, KpRequest,
           EstimateVersion, WorkflowCard, Task, Project, User)


async def _wipe(db):
    for model in _MODELS:
        await db.execute(model.__table__.delete())
    await db.commit()


def _list_rows():
    return [
        _g("r1", "Работа", "Штукатурка стен", "м2", 10, sheet="АР"),
        _g("r2", "Материал", "Штукатурка гипсовая", "кг", 300, sheet="АР"),
        _g("r3", "", "Сетка армирующая", "м2", 50, sheet="АР"),
        _g("r4", "Работа", "штукатурка стен", "м2", 4, sheet="АР"),
    ]


@pytest_asyncio.fixture
async def kp_env(db_session, fake_s3):
    await _wipe(db_session)

    def user(name, role, active=True):
        return User(username=name, role=role, full_name=name.upper(), is_active=active,
                    password_hash=_PASSWORD_HASH)

    users = {
        "pm1": user("pm1", "project_manager"),
        "pm2": user("pm2", "project_manager"),
        "head": user("head", "head_of_sales"),
        "supply1": user("supply1", "supply_manager"),
        "supply2": user("supply2", "supply_manager"),
        "contractor1": user("contractor1", "contractor_manager"),
        "contractor_off": user("contractor_off", "contractor_manager", active=False),
    }
    db_session.add_all(users.values())
    await db_session.flush()

    project = Project(name="Объект КП", owner_id=users["pm1"].id)
    db_session.add(project)
    await db_session.flush()

    task = Task(
        owner_id=users["pm1"].id, user_role="project_manager", task_type="LIST_FROM_GRAND",
        status="completed", input_files=[], input_file_data=[], chat_history=[],
        project_id=str(project.id),
    )
    db_session.add(task)
    await db_session.flush()

    card = WorkflowCard(project_id=str(project.id), name="АР", stage="list",
                        list_task_id=str(task.id))
    db_session.add(card)
    version = EstimateVersion(
        task_id=str(task.id), version_number=0, version_label="original",
        version_display_name="V0 — Оригинал", rows=_list_rows(),
        file_slot="result", task_type="LIST_FROM_GRAND",
    )
    db_session.add(version)
    await db_session.commit()

    env = {name: u.id for name, u in users.items()}
    env.update(project_id=str(project.id), card_id=str(card.id), task_id=str(task.id),
               version_id=str(version.id))
    yield env
    await _wipe(db_session)


def _payload(env, groups, comment="Нужны цены до пятницы", kind="list", version_id=None):
    return {"payload": json.dumps({
        "card_id": env["card_id"], "kind": kind,
        "version_id": version_id or env["version_id"],
        "author_comment": comment, "groups": groups,
    })}


async def _create(client, env, groups, files=(), user="pm1", role="project_manager", **kw):
    return await client.post(
        "/kp-requests",
        headers=_auth(env[user], role),
        data=_payload(env, groups, **kw),
        files=[("files", f) for f in files],
    )


MIXED = [
    {"category": "work", "row_ids": ["r1", "r4"]},
    {"category": "material", "row_ids": ["r2", "r3"]},
]


# ---------------------------------------------------------------------------
# Предпросмотр
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_preview_groups_and_employee_counts_and_writes_nothing(async_client, db_session, kp_env):
    resp = await async_client.post(
        "/kp-requests/preview",
        headers=_auth(kp_env["pm1"], "project_manager"),
        json={"card_id": kp_env["card_id"], "kind": "list",
              "version_id": kp_env["version_id"], "row_ids": ["r1", "r2", "r3", "r4"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    groups = body["groups"]
    assert groups["material"]["target_role"] == "supply_manager"
    assert groups["material"]["employees"] == 2
    # Неактивный подрядчик не считается.
    assert groups["work"]["employees"] == 1
    assert [i["name"] for i in groups["work"]["items"]] == ["Штукатурка стен"]
    assert groups["work"]["items"][0]["qty"] == 14
    assert [i["name"] for i in groups["unknown"]["items"]] == ["Сетка армирующая"]
    assert groups["unknown"]["items"][0]["source_row_ids"] == ["r3"]
    assert body["version_id"] == kp_env["version_id"]
    count = (await db_session.execute(select(func.count()).select_from(KpRequest))).scalar()
    assert count == 0


@pytest.mark.asyncio
async def test_preview_forbidden_for_production(async_client, kp_env):
    resp = await async_client.post(
        "/kp-requests/preview",
        headers=_auth(kp_env["supply1"], "supply_manager"),
        json={"card_id": kp_env["card_id"], "kind": "list", "row_ids": ["r1"]},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_preview_summary_section_not_supported(async_client, kp_env):
    resp = await async_client.post(
        "/kp-requests/preview",
        headers=_auth(kp_env["pm1"], "project_manager"),
        json={"card_id": kp_env["card_id"], "kind": "summary-section", "row_ids": ["r1"]},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Создание
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mixed_selection_creates_two_requests_with_roles(async_client, db_session, kp_env, fake_s3):
    resp = await _create(async_client, kp_env, MIXED, files=[PDF, DOCX])
    assert resp.status_code == 201, resp.text
    created = resp.json()["requests"]
    assert {r["category"]: r["target_role"] for r in created} == {
        "work": "contractor_manager", "material": "supply_manager",
    }

    reqs = (await db_session.execute(select(KpRequest))).scalars().all()
    assert len(reqs) == 2
    for r in reqs:
        assert r.status == "new"
        assert r.author_id == kp_env["pm1"]
        assert r.project_id == kp_env["project_id"]
        assert r.source_kind == "list"
        assert r.source_task_id == kp_env["task_id"]
        assert r.source_version_id == kp_env["version_id"]
        assert r.author_comment == "Нужны цены до пятницы"

    by_cat = {r.category: r for r in reqs}
    work_items = (await db_session.execute(
        select(KpRequestItem).where(KpRequestItem.request_id == by_cat["work"].id)
    )).scalars().all()
    assert [(i.name, i.qty, i.item_type, i.source_row_ids) for i in work_items] == [
        ("Штукатурка стен", 14, "work", ["r1", "r4"]),
    ]
    mat_items = (await db_session.execute(
        select(KpRequestItem).where(KpRequestItem.request_id == by_cat["material"].id)
        .order_by(KpRequestItem.position)
    )).scalars().all()
    # Позиция без типа, отнесённая человеком к материалам, становится материалом.
    assert [(i.name, i.item_type) for i in mat_items] == [
        ("Штукатурка гипсовая", "material"), ("Сетка армирующая", "material"),
    ]
    assert [i.position for i in mat_items] == [0, 1]

    # Вложения — у каждого запроса свои объекты под его префиксом.
    files = (await db_session.execute(select(KpRequestFile))).scalars().all()
    assert len(files) == 4
    for f in files:
        assert f.storage_key.startswith(f"kp/{f.request_id}/")
        assert f.storage_key in fake_s3.store
        assert f.uploaded_by == kp_env["pm1"]
    assert {f.file_name for f in files} == {"spec.pdf", "tz.docx"}


@pytest.mark.asyncio
async def test_no_active_employees_of_role_is_422(async_client, db_session, kp_env):
    await db_session.execute(
        User.__table__.update().where(User.id == kp_env["contractor1"]).values(is_active=False)
    )
    await db_session.commit()
    resp = await _create(async_client, kp_env, MIXED)
    assert resp.status_code == 422
    assert "подрядчик" in resp.json()["detail"].lower()
    # Ничего не создано — ни запроса по материалам, ни по работам.
    count = (await db_session.execute(select(func.count()).select_from(KpRequest))).scalar()
    assert count == 0


@pytest.mark.asyncio
async def test_known_type_in_wrong_category_is_422(async_client, kp_env):
    resp = await _create(async_client, kp_env, [{"category": "material", "row_ids": ["r1"]}])
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_row_in_two_groups_is_422(async_client, kp_env):
    resp = await _create(async_client, kp_env, [
        {"category": "work", "row_ids": ["r3"]},
        {"category": "material", "row_ids": ["r3"]},
    ])
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_missing_row_is_422(async_client, kp_env):
    resp = await _create(async_client, kp_env, [{"category": "work", "row_ids": ["r1", "gone"]}])
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_empty_groups_is_422(async_client, kp_env):
    resp = await _create(async_client, kp_env, [{"category": "work", "row_ids": []}])
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_unsupported_attachment_type_rejected(async_client, db_session, kp_env):
    resp = await _create(async_client, kp_env, MIXED, files=[("run.exe", b"MZ", "application/octet-stream")])
    assert resp.status_code == 415
    count = (await db_session.execute(select(func.count()).select_from(KpRequest))).scalar()
    assert count == 0


@pytest.mark.asyncio
async def test_too_many_attachments_rejected(async_client, kp_env):
    files = [(f"f{i}.pdf", b"%PDF", "application/pdf") for i in range(11)]
    resp = await _create(async_client, kp_env, MIXED, files=files)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_attachment_size_limit(async_client, kp_env, monkeypatch):
    monkeypatch.setattr(kp, "MAX_FILE_BYTES", 10)
    resp = await _create(async_client, kp_env, MIXED, files=[("big.pdf", b"%PDF" * 10, "application/pdf")])
    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_production_cannot_create(async_client, kp_env):
    resp = await _create(async_client, kp_env, MIXED, user="supply1", role="supply_manager")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_snapshot_does_not_change_after_document_edit(async_client, db_session, kp_env):
    resp = await _create(async_client, kp_env, [{"category": "work", "row_ids": ["r1", "r4"]}])
    request_id = resp.json()["requests"][0]["id"]

    # Правка документа: другое наименование и объём.
    edited = _list_rows()
    edited[0]["cells"]["Наименование"] = "Шпаклёвка"
    edited[0]["cells"]["Кол-во"] = 999
    await db_session.execute(
        EstimateVersion.__table__.update()
        .where(EstimateVersion.id == kp_env["version_id"]).values(rows=edited)
    )
    await db_session.commit()

    detail = await async_client.get(f"/kp-requests/{request_id}", headers=_auth(kp_env["pm2"], "project_manager"))
    assert detail.status_code == 200
    items = detail.json()["items"]
    assert [(i["name"], i["qty"]) for i in items] == [("Штукатурка стен", 14)]


@pytest.mark.asyncio
async def test_optimization_rows_snapshot(async_client, db_session, kp_env):
    """Смета/оптимизация: типизированные строки, лист и № исходной сметы."""
    task = Task(
        owner_id=kp_env["pm1"], user_role="project_manager", task_type="ESTIMATE_OPTIMIZATION",
        status="completed", input_files=[], input_file_data=[], chat_history=[],
        project_id=kp_env["project_id"],
    )
    db_session.add(task)
    await db_session.flush()
    card = await db_session.get(WorkflowCard, kp_env["card_id"])
    card.optimization_task_id = str(task.id)
    rows = [
        {"id": "o1", "type": "section", "name": "Кровля"},
        {"id": "o2", "type": "work", "name": "Монтаж кровли", "unit": "м2", "qty": 120,
         "sheet": "КР", "source_no": "3"},
        {"id": "o3", "type": "material", "name": "Профлист С21", "unit": "м2", "qty": 130,
         "sheet": "КР", "source_no": "4"},
    ]
    v0 = EstimateVersion(task_id=str(task.id), version_number=0, version_label="v0",
                         version_display_name="V0", rows=rows, file_slot="result",
                         task_type="ESTIMATE_OPTIMIZATION")
    db_session.add(v0)
    await db_session.commit()

    resp = await _create(
        async_client, kp_env, [{"category": "material", "row_ids": ["o1", "o3"]}],
        kind="optimization", version_id=str(v0.id),
    )
    assert resp.status_code == 201, resp.text
    request_id = resp.json()["requests"][0]["id"]
    req = await db_session.get(KpRequest, request_id)
    assert req.source_kind == "optimization"
    assert req.source_task_id == str(task.id)
    items = (await db_session.execute(
        select(KpRequestItem).where(KpRequestItem.request_id == request_id)
    )).scalars().all()
    assert [(i.name, i.unit, i.qty, i.sheet, i.source_no) for i in items] == [
        ("Профлист С21", "м2", 130, "КР", "4"),
    ]


# ---------------------------------------------------------------------------
# Видимость по роли
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def two_requests(async_client, kp_env):
    resp = await _create(async_client, kp_env, MIXED, files=[PDF])
    assert resp.status_code == 201, resp.text
    by_cat = {r["category"]: r["id"] for r in resp.json()["requests"]}
    return by_cat


@pytest.mark.asyncio
async def test_supply_does_not_see_work_request(async_client, kp_env, two_requests):
    resp = await async_client.get(
        f"/kp-requests/{two_requests['work']}", headers=_auth(kp_env["supply1"], "supply_manager"),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_supply_sees_colleagues_supply_request(async_client, kp_env, two_requests):
    for who in ("supply1", "supply2"):
        resp = await async_client.get(
            f"/kp-requests/{two_requests['material']}", headers=_auth(kp_env[who], "supply_manager"),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["category"] == "material"
        assert body["project_name"] == "Объект КП"
        assert body["card_name"] == "АР"
        assert body["author_name"] == "PM1"
        assert [f["file_name"] for f in body["files"]] == ["spec.pdf"]
        assert "storage_key" not in json.dumps(body)


@pytest.mark.asyncio
async def test_role_from_db_decides_not_token(async_client, db_session, kp_env, two_requests):
    """Роль сменили залогиненному снабженцу на подрядчика: старый токен не
    открывает запросы снабжения."""
    await db_session.execute(
        User.__table__.update().where(User.id == kp_env["supply1"]).values(role="contractor_manager")
    )
    await db_session.commit()
    headers = _auth(kp_env["supply1"], "supply_manager")
    assert (await async_client.get(f"/kp-requests/{two_requests['material']}", headers=headers)).status_code == 404
    assert (await async_client.get(f"/kp-requests/{two_requests['work']}", headers=headers)).status_code == 200


@pytest.mark.asyncio
async def test_sales_see_all_requests(async_client, kp_env, two_requests):
    for rid in two_requests.values():
        resp = await async_client.get(f"/kp-requests/{rid}", headers=_auth(kp_env["pm2"], "project_manager"))
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_mine_by_role_and_status(async_client, kp_env, two_requests):
    resp = await async_client.get("/kp-requests/mine", headers=_auth(kp_env["supply2"], "supply_manager"))
    assert resp.status_code == 200
    items = resp.json()
    assert [r["id"] for r in items] == [two_requests["material"]]
    assert items[0]["items_count"] == 2
    assert items[0]["files_count"] == 1
    assert items[0]["project_name"] == "Объект КП"
    assert items[0]["author_name"] == "PM1"

    resp = await async_client.get("/kp-requests/mine?status=in_progress",
                                  headers=_auth(kp_env["supply2"], "supply_manager"))
    assert resp.json() == []

    resp = await async_client.get("/kp-requests/mine", headers=_auth(kp_env["contractor1"], "contractor_manager"))
    assert [r["id"] for r in resp.json()] == [two_requests["work"]]


@pytest.mark.asyncio
async def test_list_by_card_for_sales_and_filtered_for_production(async_client, kp_env, two_requests):
    resp = await async_client.get(f"/kp-requests?card_id={kp_env['card_id']}",
                                  headers=_auth(kp_env["pm2"], "project_manager"))
    assert resp.status_code == 200
    assert {r["id"] for r in resp.json()} == set(two_requests.values())

    resp = await async_client.get(f"/kp-requests?card_id={kp_env['card_id']}",
                                  headers=_auth(kp_env["contractor1"], "contractor_manager"))
    assert [r["id"] for r in resp.json()] == [two_requests["work"]]


@pytest.mark.asyncio
async def test_counters(async_client, db_session, kp_env, two_requests):
    resp = await async_client.get("/kp-requests/counters", headers=_auth(kp_env["supply1"], "supply_manager"))
    assert resp.status_code == 200
    assert resp.json()["new"] == 1

    await db_session.execute(
        KpRequest.__table__.update().where(KpRequest.id == two_requests["work"]).values(status="done")
    )
    await db_session.commit()
    resp = await async_client.get("/kp-requests/counters", headers=_auth(kp_env["pm1"], "project_manager"))
    assert resp.json()["done_not_applied"] == {kp_env["card_id"]: 1}
    resp = await async_client.get("/kp-requests/counters", headers=_auth(kp_env["contractor1"], "contractor_manager"))
    assert resp.json()["new"] == 0
    assert resp.json()["done_not_applied"] == {}


@pytest.mark.asyncio
async def test_deleted_card_hidden_from_lists_and_back_after_restore(async_client, db_session, kp_env, two_requests):
    from datetime import datetime, timezone
    await db_session.execute(
        WorkflowCard.__table__.update().where(WorkflowCard.id == kp_env["card_id"])
        .values(deleted_at=datetime.now(timezone.utc))
    )
    await db_session.commit()
    headers = _auth(kp_env["supply1"], "supply_manager")
    assert (await async_client.get("/kp-requests/mine", headers=headers)).json() == []
    assert (await async_client.get("/kp-requests/counters", headers=headers)).json()["new"] == 0

    await db_session.execute(
        WorkflowCard.__table__.update().where(WorkflowCard.id == kp_env["card_id"]).values(deleted_at=None)
    )
    await db_session.commit()
    assert len((await async_client.get("/kp-requests/mine", headers=headers)).json()) == 1


@pytest.mark.asyncio
async def test_deleted_project_hidden_from_lists(async_client, db_session, kp_env, two_requests):
    from datetime import datetime, timezone
    await db_session.execute(
        Project.__table__.update().where(Project.id == kp_env["project_id"])
        .values(deleted_at=datetime.now(timezone.utc))
    )
    await db_session.commit()
    resp = await async_client.get("/kp-requests/mine", headers=_auth(kp_env["contractor1"], "contractor_manager"))
    assert resp.json() == []


# ---------------------------------------------------------------------------
# Взять в работу, отменить, вернуть
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_take_sets_in_progress_and_taker(async_client, db_session, kp_env, two_requests):
    resp = await async_client.post(f"/kp-requests/{two_requests['material']}/take",
                                   headers=_auth(kp_env["supply1"], "supply_manager"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "in_progress"
    assert body["taken_by_name"] == "SUPPLY1"
    assert body["taken_at"]

    # Коллега видит, у кого запрос, и может его открыть.
    resp = await async_client.get(f"/kp-requests/{two_requests['material']}",
                                  headers=_auth(kp_env["supply2"], "supply_manager"))
    assert resp.status_code == 200
    assert resp.json()["taken_by_name"] == "SUPPLY1"


@pytest.mark.asyncio
async def test_second_take_is_409(async_client, kp_env, two_requests):
    url = f"/kp-requests/{two_requests['material']}/take"
    first = await async_client.post(url, headers=_auth(kp_env["supply1"], "supply_manager"))
    second = await async_client.post(url, headers=_auth(kp_env["supply2"], "supply_manager"))
    assert first.status_code == 200
    assert second.status_code == 409
    assert "SUPPLY1" in second.json()["detail"]


@pytest.mark.asyncio
async def test_take_is_atomic_against_stale_state(db_session, kp_env, async_client, two_requests):
    """Двое нажали одновременно: оба прочли `new`. Проверка статуса обязана
    быть в самом UPDATE, а не в прочитанном объекте."""
    rid = two_requests["material"]
    stale = await db_session.get(KpRequest, rid)
    assert stale.status == "new"
    # Коллега успел взять — в обход объекта сессии.
    await db_session.execute(
        KpRequest.__table__.update().where(KpRequest.id == rid)
        .values(status="in_progress", taken_by_id=kp_env["supply2"])
    )
    assert stale.status == "new"  # объект в сессии устарел

    user = {"sub": str(kp_env["supply1"]), "role": "supply_manager"}
    with pytest.raises(Exception) as exc:
        await kp.take(db_session, rid, user)
    assert getattr(exc.value, "status_code", None) == 409
    await db_session.rollback()


@pytest.mark.asyncio
async def test_take_foreign_role_404_and_sales_403(async_client, kp_env, two_requests):
    resp = await async_client.post(f"/kp-requests/{two_requests['work']}/take",
                                   headers=_auth(kp_env["supply1"], "supply_manager"))
    assert resp.status_code == 404
    resp = await async_client.post(f"/kp-requests/{two_requests['work']}/take",
                                   headers=_auth(kp_env["pm1"], "project_manager"))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_cancel_by_author_and_head_not_by_other_pm_or_production(async_client, kp_env, two_requests):
    url = f"/kp-requests/{two_requests['work']}/cancel"
    assert (await async_client.post(url, headers=_auth(kp_env["pm2"], "project_manager"))).status_code == 403
    assert (await async_client.post(url, headers=_auth(kp_env["contractor1"], "contractor_manager"))).status_code == 403
    resp = await async_client.post(url, headers=_auth(kp_env["pm1"], "project_manager"))
    assert resp.status_code == 200 and resp.json()["status"] == "cancelled"
    # Повторная отмена — конфликт состояния.
    assert (await async_client.post(url, headers=_auth(kp_env["pm1"], "project_manager"))).status_code == 409

    url2 = f"/kp-requests/{two_requests['material']}/cancel"
    resp = await async_client.post(url2, headers=_auth(kp_env["head"], "head_of_sales"))
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_reopen_done_request(async_client, db_session, kp_env, two_requests):
    rid = two_requests["work"]
    url = f"/kp-requests/{rid}/reopen"
    # Новый запрос возвращать нечего.
    assert (await async_client.post(url, headers=_auth(kp_env["pm1"], "project_manager"))).status_code == 409
    await db_session.execute(
        KpRequest.__table__.update().where(KpRequest.id == rid)
        .values(status="done", taken_by_id=kp_env["contractor1"], completed_by_id=kp_env["contractor1"])
    )
    await db_session.commit()
    assert (await async_client.post(url, headers=_auth(kp_env["pm2"], "project_manager"))).status_code == 403
    assert (await async_client.post(url, headers=_auth(kp_env["contractor1"], "contractor_manager"))).status_code == 403
    resp = await async_client.post(url, headers=_auth(kp_env["pm1"], "project_manager"))
    assert resp.status_code == 200
    assert resp.json()["status"] == "in_progress"


# ---------------------------------------------------------------------------
# Вложения
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_attachment_download_by_role(async_client, kp_env, two_requests):
    detail = (await async_client.get(f"/kp-requests/{two_requests['material']}",
                                     headers=_auth(kp_env["supply1"], "supply_manager"))).json()
    file_id = detail["files"][0]["id"]

    token = create_access_token(kp_env["supply2"], "supply_manager")
    resp = await async_client.get(f"/kp-request-files/{file_id}/download?token={token}")
    assert resp.status_code == 200
    assert resp.content == PDF[1]
    assert "attachment" in resp.headers["content-disposition"]

    resp = await async_client.get(f"/kp-request-files/{file_id}/download",
                                  headers=_auth(kp_env["contractor1"], "contractor_manager"))
    assert resp.status_code == 404

    resp = await async_client.get(f"/kp-request-files/{file_id}/download")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_add_and_delete_attachment_later(async_client, db_session, kp_env, two_requests, fake_s3):
    rid = two_requests["material"]
    resp = await async_client.post(
        f"/kp-requests/{rid}/files", headers=_auth(kp_env["pm2"], "project_manager"),
        files=[("files", DOCX)],
    )
    assert resp.status_code == 201, resp.text
    added = resp.json()["files"]
    assert [f["file_name"] for f in added] == ["tz.docx"]

    # Производство вложения автора не удаляет и не добавляет.
    resp = await async_client.delete(f"/kp-request-files/{added[0]['id']}",
                                     headers=_auth(kp_env["supply1"], "supply_manager"))
    assert resp.status_code == 403
    resp = await async_client.post(
        f"/kp-requests/{rid}/files", headers=_auth(kp_env["supply1"], "supply_manager"),
        files=[("files", DOCX)],
    )
    assert resp.status_code == 403

    row = await db_session.get(KpRequestFile, added[0]["id"])
    key = row.storage_key
    resp = await async_client.delete(f"/kp-request-files/{added[0]['id']}",
                                     headers=_auth(kp_env["pm1"], "project_manager"))
    assert resp.status_code == 204
    assert key not in fake_s3.store
    detail = (await async_client.get(f"/kp-requests/{rid}", headers=_auth(kp_env["pm1"], "project_manager"))).json()
    assert [f["file_name"] for f in detail["files"]] == ["spec.pdf"]


@pytest.mark.asyncio
async def test_attachment_limit_counts_existing_files(async_client, kp_env, two_requests):
    rid = two_requests["material"]  # уже 1 файл
    files = [("files", (f"f{i}.pdf", b"%PDF", "application/pdf")) for i in range(10)]
    resp = await async_client.post(f"/kp-requests/{rid}/files",
                                   headers=_auth(kp_env["pm1"], "project_manager"), files=files)
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Окончательное удаление
# ---------------------------------------------------------------------------

async def _kp_counts(db):
    out = {}
    for model in (KpRequest, KpRequestItem, KpRequestFile, KpOffer, KpOfferPrice):
        out[model.__tablename__] = (await db.execute(select(func.count()).select_from(model))).scalar()
    return out


async def _add_offer_with_price(db, request_id):
    """Строки фаз 4+: КП и цена — чистка обязана убрать и их."""
    item = (await db.execute(
        select(KpRequestItem).where(KpRequestItem.request_id == request_id).limit(1)
    )).scalar_one()
    offer = KpOffer(request_id=request_id, supplier_name="ООО Поставщик", vat_mode="with_vat",
                    vat_rate=22, storage_key=f"kp/{request_id}/offers/x.pdf")
    db.add(offer)
    await db.flush()
    db.add(KpOfferPrice(offer_id=offer.id, item_id=item.id, price=100, source="manual", confirmed=True))
    await storage_service.put_object(offer.storage_key, b"offer", "application/pdf")
    await db.commit()


@pytest.mark.asyncio
async def test_permanent_card_delete_purges_requests_and_s3(async_client, db_session, kp_env, two_requests, fake_s3):
    from datetime import datetime, timezone
    await _add_offer_with_price(db_session, two_requests["material"])
    assert any(k.startswith("kp/") for k in fake_s3.store)

    await db_session.execute(
        WorkflowCard.__table__.update().where(WorkflowCard.id == kp_env["card_id"])
        .values(deleted_at=datetime.now(timezone.utc))
    )
    await db_session.commit()
    resp = await async_client.delete(f"/api/workflow-cards/{kp_env['card_id']}/permanent",
                                     headers=_auth(kp_env["pm1"], "project_manager"))
    assert resp.status_code == 204, resp.text
    db_session.expire_all()
    assert await _kp_counts(db_session) == {
        "kp_requests": 0, "kp_request_items": 0, "kp_request_files": 0,
        "kp_offers": 0, "kp_offer_prices": 0,
    }
    assert not any(k.startswith("kp/") for k in fake_s3.store)


@pytest.mark.asyncio
async def test_permanent_project_delete_purges_requests(async_client, db_session, kp_env, two_requests, fake_s3):
    resp = await async_client.delete(f"/projects/{kp_env['project_id']}/permanent",
                                     headers=_auth(kp_env["head"], "admin"))
    assert resp.status_code == 204, resp.text
    db_session.expire_all()
    assert (await _kp_counts(db_session))["kp_requests"] == 0
    assert (await _kp_counts(db_session))["kp_request_files"] == 0
    assert not any(k.startswith("kp/") for k in fake_s3.store)


@pytest.mark.asyncio
async def test_clear_project_trash_purges_requests(async_client, db_session, kp_env, two_requests, fake_s3):
    from datetime import datetime, timezone
    await db_session.execute(
        Project.__table__.update().where(Project.id == kp_env["project_id"])
        .values(deleted_at=datetime.now(timezone.utc))
    )
    await db_session.commit()
    resp = await async_client.delete("/projects/trash", headers=_auth(kp_env["head"], "admin"))
    assert resp.status_code == 204, resp.text
    db_session.expire_all()
    assert (await _kp_counts(db_session))["kp_request_items"] == 0
    assert not any(k.startswith("kp/") for k in fake_s3.store)


@pytest.mark.asyncio
async def test_purge_other_cards_untouched(db_session, kp_env, async_client, two_requests):
    removed = await kp.purge_for_cards(db_session, ["00000000-0000-0000-0000-000000000000"])
    await db_session.commit()
    assert removed == []
    assert (await _kp_counts(db_session))["kp_requests"] == 2


# ---------------------------------------------------------------------------
# Права (чистая логика)
# ---------------------------------------------------------------------------

def test_can_view_and_work_kp():
    req = KpRequest(target_role="supply_manager", author_id=5)
    sales = {"sub": "1", "role": "project_manager"}
    supply = {"sub": "2", "role": "supply_manager"}
    contractor = {"sub": "3", "role": "contractor_manager"}
    assert perm.can_view_kp(req, sales)
    assert perm.can_view_kp(req, supply)
    assert not perm.can_view_kp(req, contractor)
    assert perm.can_work_kp(req, supply)
    assert not perm.can_work_kp(req, contractor)
    assert not perm.can_work_kp(req, sales)
    assert perm.can_manage_kp(req, {"sub": "5", "role": "project_manager"})
    assert perm.can_manage_kp(req, {"sub": "9", "role": "head_of_sales"})
    assert perm.can_manage_kp(req, {"sub": "9", "role": "admin"})
    assert not perm.can_manage_kp(req, sales)
    assert not perm.can_manage_kp(req, {"sub": "5", "role": "supply_manager"})


@pytest.mark.asyncio
async def test_reopen_cancelled_untaken_request_returns_to_new(async_client, kp_env, two_requests):
    """Отменённый запрос, который никто не брал, возвращается новым — иначе он
    висел бы «в работе» без исполнителя."""
    rid = two_requests["material"]
    headers = _auth(kp_env["pm1"], "project_manager")
    assert (await async_client.post(f"/kp-requests/{rid}/cancel", headers=headers)).status_code == 200
    resp = await async_client.post(f"/kp-requests/{rid}/reopen", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "new"


@pytest.mark.asyncio
async def test_invalid_ids_are_404(async_client, kp_env):
    headers = _auth(kp_env["pm1"], "project_manager")
    assert (await async_client.get("/kp-requests/not-a-uuid", headers=headers)).status_code == 404
    assert (await async_client.get("/kp-request-files/1/download", headers=headers)).status_code == 404


# ---------------------------------------------------------------------------
# Чтение вложений: лимит до чтения, а не после
# ---------------------------------------------------------------------------

class _FakeUpload:
    """UploadFile, который помнит, сколько у него просили прочитать."""

    def __init__(self, name: str, size: int):
        self.filename = name
        self._data = b"x" * size
        self.reads: list = []

    async def read(self, size: int = -1) -> bytes:
        self.reads.append(size)
        return self._data if size is None or size < 0 else self._data[:size]


def test_kp_file_limit_is_own_50_mb():
    """Лимит КП — 50 МБ по спецификации, а не общий MAX_FILE_SIZE_MB задач."""
    from app.services import kp_offers

    assert kp.KP_MAX_FILE_MB == 50
    assert kp.MAX_FILE_BYTES == 50 * 1024 * 1024
    assert kp_offers.MAX_FILE_BYTES == 50 * 1024 * 1024


@pytest.mark.asyncio
async def test_read_uploads_checks_count_before_reading(monkeypatch):
    from fastapi import HTTPException

    from app.routers import kp_requests as router

    files = [_FakeUpload(f"f{i}.pdf", 5) for i in range(kp.MAX_FILES + 1)]
    with pytest.raises(HTTPException) as exc:
        await router._read_uploads(files)
    assert exc.value.status_code == 400
    assert all(f.reads == [] for f in files)


@pytest.mark.asyncio
async def test_read_uploads_stops_at_limit(monkeypatch):
    from fastapi import HTTPException

    from app.routers import kp_requests as router

    monkeypatch.setattr(kp, "MAX_FILE_BYTES", 10)
    ok = _FakeUpload("ok.pdf", 10)
    big = _FakeUpload("big.pdf", 1000)
    with pytest.raises(HTTPException) as exc:
        await router._read_uploads([ok, big])
    assert exc.value.status_code == 413
    assert "big.pdf" in exc.value.detail
    # Читается не больше лимита + 1 байт — файл целиком в память не попадает.
    assert ok.reads == [11] and big.reads == [11]
    assert await router._read_uploads([_FakeUpload("a.pdf", 10)]) == [("a.pdf", b"x" * 10)]


@pytest.mark.asyncio
async def test_read_offer_upload_stops_at_limit(monkeypatch):
    from fastapi import HTTPException

    from app.routers import kp_requests as router
    from app.services import kp_offers

    monkeypatch.setattr(kp_offers, "MAX_FILE_BYTES", 10)
    big = _FakeUpload("kp.pdf", 1000)
    with pytest.raises(HTTPException) as exc:
        await router._read_offer_upload(big)
    assert exc.value.status_code == 413
    assert big.reads == [11]
    assert await router._read_offer_upload(None) is None
