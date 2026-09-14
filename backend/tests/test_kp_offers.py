"""КП к запросу: файлы, ручные цены, сравнение, завершение (план 2026-09-14-zapros-kp.md, фаза 4).

Критерии спецификации 14, 15, 18–22 в части сервера:
* загрузка КП в новый запрос берёт его в работу атомарно;
* КП — поставщик, дата, НДС и ставка, «включает материалы» (только работы),
  файл в S3 под `kp/{id}/offers/`, скачивание с проверкой роли, удаление до
  завершения;
* ручная цена сразу подтверждена, ИИ-черновик подтверждается отдельно;
* матрица в карточке запроса — приведённые цены, минимум, выбор, причины;
* «Завершить» — непустой отчёт и нет черновиков, иначе 422 с перечнем;
  атомарно; после завершения отдел производства ничего не правит (409).
"""
import json

import fitz
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
from app.services import kp_offers
from app.utils.auth import create_access_token, hash_password

_PASSWORD_HASH = hash_password("x1234")


def _auth(user_id: int, role: str) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id, role, f'u{user_id}')}"}


def _pdf(pages: int = 1) -> bytes:
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


_MODELS = (KpOfferPrice, KpRequestItem, KpOffer, KpRequestFile, KpRequest,
           EstimateVersion, WorkflowCard, Task, Project, User)


async def _wipe(db):
    for model in _MODELS:
        await db.execute(model.__table__.delete())
    await db.commit()


@pytest_asyncio.fixture
async def env(db_session, fake_s3):
    await _wipe(db_session)

    def user(name, role):
        return User(username=name, role=role, full_name=name.upper(), is_active=True,
                    password_hash=_PASSWORD_HASH)

    users = {
        "pm1": user("pm1", "project_manager"),
        "pm2": user("pm2", "project_manager"),
        "supply1": user("supply1", "supply_manager"),
        "supply2": user("supply2", "supply_manager"),
        "contractor1": user("contractor1", "contractor_manager"),
    }
    db_session.add_all(users.values())
    await db_session.flush()

    project = Project(name="Объект", owner_id=users["pm1"].id)
    db_session.add(project)
    await db_session.flush()
    card = WorkflowCard(project_id=str(project.id), name="КР", stage="list")
    db_session.add(card)
    await db_session.flush()

    def request(category, role):
        return KpRequest(
            project_id=str(project.id), card_id=str(card.id), source_kind="list",
            category=category, target_role=role, status="new", author_id=users["pm1"].id,
        )

    material = request("material", "supply_manager")
    work = request("work", "contractor_manager")
    db_session.add_all([material, work])
    await db_session.flush()
    items = {
        "armature": KpRequestItem(request_id=material.id, position=0, item_type="material",
                                  name="Арматура А500", unit="кг", qty=2000, source_row_ids=["r1"]),
        "cement": KpRequestItem(request_id=material.id, position=1, item_type="material",
                                name="Цемент М500", unit="кг", qty=500, source_row_ids=["r2"]),
        "plaster": KpRequestItem(request_id=work.id, position=0, item_type="work",
                                 name="Штукатурка стен", unit="м2", qty=100, source_row_ids=["r3"]),
    }
    db_session.add_all(items.values())
    await db_session.commit()

    out = {name: u.id for name, u in users.items()}
    out.update(material=str(material.id), work=str(work.id),
               **{name: str(i.id) for name, i in items.items()})
    yield out
    await _wipe(db_session)


SUPPLY = ("supply1", "supply_manager")
SUPPLY2 = ("supply2", "supply_manager")
CONTRACTOR = ("contractor1", "contractor_manager")
PM = ("pm1", "project_manager")


def _h(env, who):
    return _auth(env[who[0]], who[1])


async def _upload(client, env, request_key="material", who=SUPPLY, file=None, **fields):
    data = {"supplier_name": "ООО Металл", "vat_mode": "with_vat", "vat_rate": "22"}
    data.update({k: v for k, v in fields.items() if v is not None})
    files = [("file", file)] if file else []
    return await client.post(
        f"/kp-requests/{env[request_key]}/offers", headers=_h(env, who), data=data, files=files,
    )


async def _offer(client, env, **kw):
    resp = await _upload(client, env, file=("kp.pdf", _pdf(), "application/pdf"), **kw)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _put_price(client, env, offer_id, item_key, price, unit=None, who=SUPPLY, **extra):
    body = {"price": price, "unit": unit, **extra}
    return await client.put(
        f"/kp-offers/{offer_id}/prices/{env[item_key]}", headers=_h(env, who), json=body,
    )


async def _detail(client, env, request_key="material", who=SUPPLY):
    resp = await client.get(f"/kp-requests/{env[request_key]}", headers=_h(env, who))
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Загрузка КП
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_offer_takes_new_request_and_stores_file(async_client, db_session, env, fake_s3):
    resp = await _upload(async_client, env, file=("КП металл.pdf", _pdf(), "application/pdf"),
                         offer_date="2026-09-10")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["supplier_name"] == "ООО Металл"
    assert body["offer_date"] == "2026-09-10"
    assert body["vat_mode"] == "with_vat"
    assert body["vat_rate"] == 22
    assert body["includes_materials"] is False
    assert body["file_name"] == "КП металл.pdf"
    assert body["has_file"] is True
    assert body["created_by_name"] == "SUPPLY1"
    assert "storage_key" not in json.dumps(body)

    db_session.expire_all()
    request = await db_session.get(KpRequest, env["material"])
    assert request.status == "in_progress"
    assert request.taken_by_id == env["supply1"]
    assert request.taken_at is not None
    offer = await db_session.get(KpOffer, body["id"])
    assert offer.storage_key.startswith(f"kp/{env['material']}/offers/")
    assert offer.storage_key in fake_s3.store


@pytest.mark.asyncio
async def test_upload_to_request_in_progress_keeps_taker(async_client, db_session, env):
    await async_client.post(f"/kp-requests/{env['material']}/take", headers=_h(env, SUPPLY2))
    await _offer(async_client, env)
    db_session.expire_all()
    request = await db_session.get(KpRequest, env["material"])
    assert request.status == "in_progress"
    assert request.taken_by_id == env["supply2"]


@pytest.mark.asyncio
async def test_default_vat_rate_22_and_without_vat_has_no_rate(async_client, env):
    body = (await _upload(async_client, env, vat_rate="", file=("a.xlsx", b"PK", "application/octet-stream"))).json()
    assert body["vat_mode"] == "with_vat" and body["vat_rate"] == 22
    body = (await _upload(async_client, env, vat_mode="without_vat", vat_rate="20")).json()
    assert body["vat_mode"] == "without_vat" and body["vat_rate"] is None


@pytest.mark.asyncio
async def test_vat_mode_required_and_validated(async_client, env):
    resp = await async_client.post(
        f"/kp-requests/{env['material']}/offers", headers=_h(env, SUPPLY),
        data={"supplier_name": "Х"},
    )
    assert resp.status_code == 422
    assert (await _upload(async_client, env, vat_mode="maybe")).status_code == 422
    assert (await _upload(async_client, env, vat_rate="-1")).status_code == 422
    assert (await _upload(async_client, env, vat_rate="100")).status_code == 422
    assert (await _upload(async_client, env, vat_rate="abc")).status_code == 422
    assert (await _upload(async_client, env, offer_date="10.09.2026")).status_code == 422


@pytest.mark.asyncio
async def test_offer_needs_file_or_supplier(async_client, env):
    resp = await _upload(async_client, env, supplier_name="  ")
    assert resp.status_code == 422
    # Без файла, но с поставщиком — можно: цены вводятся руками.
    resp = await _upload(async_client, env)
    assert resp.status_code == 201
    assert resp.json()["has_file"] is False


@pytest.mark.asyncio
async def test_includes_materials_only_for_work(async_client, env):
    resp = await _upload(async_client, env, includes_materials="true")
    assert resp.status_code == 422
    resp = await _upload(async_client, env, request_key="work", who=CONTRACTOR,
                         includes_materials="true", supplier_name="Бригада")
    assert resp.status_code == 201, resp.text
    assert resp.json()["includes_materials"] is True


@pytest.mark.asyncio
async def test_offer_file_types_and_limits(async_client, env, monkeypatch):
    resp = await _upload(async_client, env, file=("kp.docx", b"PK", "application/octet-stream"))
    assert resp.status_code == 415
    for name in ("kp.xls", "kp.jpg", "kp.jpeg", "kp.png"):
        assert (await _upload(async_client, env, file=(name, b"x", "application/octet-stream"))).status_code == 201, name
    monkeypatch.setattr(kp_offers, "MAX_FILE_BYTES", 10)
    resp = await _upload(async_client, env, file=("big.xlsx", b"x" * 11, "application/octet-stream"))
    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_pdf_page_limit_and_broken_pdf(async_client, env, monkeypatch):
    monkeypatch.setattr(kp_offers, "MAX_PDF_PAGES", 2)
    resp = await _upload(async_client, env, file=("kp.pdf", _pdf(3), "application/pdf"))
    assert resp.status_code == 422
    assert "3" in resp.json()["detail"]
    resp = await _upload(async_client, env, file=("kp.pdf", b"not a pdf", "application/pdf"))
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_upload_forbidden_for_sales_and_foreign_role(async_client, db_session, env):
    assert (await _upload(async_client, env, who=PM)).status_code == 403
    assert (await _upload(async_client, env, who=CONTRACTOR)).status_code == 404
    count = (await db_session.execute(select(func.count()).select_from(KpOffer))).scalar()
    assert count == 0


@pytest.mark.asyncio
async def test_upload_to_done_or_cancelled_is_409(async_client, db_session, env):
    for st in ("done", "cancelled"):
        await db_session.execute(
            KpRequest.__table__.update().where(KpRequest.id == env["material"]).values(status=st)
        )
        await db_session.commit()
        assert (await _upload(async_client, env)).status_code == 409, st


@pytest.mark.asyncio
async def test_download_offer_by_role(async_client, env):
    offer = await _offer(async_client, env)
    url = f"/kp-offers/{offer['id']}/download"
    for who in (SUPPLY2, PM):
        resp = await async_client.get(url, headers=_h(env, who))
        assert resp.status_code == 200, who
        assert resp.content.startswith(b"%PDF")
    resp = await async_client.get(url, headers=_h(env, CONTRACTOR))
    assert resp.status_code == 404
    token = create_access_token(env["supply2"], "supply_manager", "u")
    assert (await async_client.get(f"{url}?token={token}")).status_code == 200
    assert (await async_client.get(url)).status_code == 401


@pytest.mark.asyncio
async def test_download_offer_without_file_404(async_client, env):
    offer = (await _upload(async_client, env)).json()
    resp = await async_client.get(f"/kp-offers/{offer['id']}/download", headers=_h(env, SUPPLY))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Правка и удаление КП
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_patch_offer(async_client, env):
    offer = await _offer(async_client, env)
    url = f"/kp-offers/{offer['id']}"
    resp = await async_client.patch(url, headers=_h(env, SUPPLY2),
                                    json={"supplier_name": "ООО Сталь", "vat_rate": 20})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["supplier_name"] == "ООО Сталь"
    assert body["vat_rate"] == 20
    assert body["offer_date"] is None

    body = (await async_client.patch(url, headers=_h(env, SUPPLY), json={"vat_mode": "without_vat"})).json()
    assert body["vat_mode"] == "without_vat" and body["vat_rate"] is None
    body = (await async_client.patch(url, headers=_h(env, SUPPLY), json={"vat_mode": "with_vat"})).json()
    assert body["vat_rate"] == 22
    body = (await async_client.patch(url, headers=_h(env, SUPPLY), json={"offer_date": "2026-09-01"})).json()
    assert body["offer_date"] == "2026-09-01" and body["supplier_name"] == "ООО Сталь"

    assert (await async_client.patch(url, headers=_h(env, SUPPLY), json={"vat_rate": 150})).status_code == 422
    # КП с файлом может остаться без поставщика (его подскажет разбор), без файла — нет.
    assert (await async_client.patch(url, headers=_h(env, SUPPLY), json={"supplier_name": ""})).status_code == 200
    manual = (await _upload(async_client, env, supplier_name="Звонок")).json()
    resp = await async_client.patch(f"/kp-offers/{manual['id']}", headers=_h(env, SUPPLY), json={"supplier_name": " "})
    assert resp.status_code == 422
    assert (await async_client.patch(url, headers=_h(env, SUPPLY), json={"includes_materials": True})).status_code == 422
    assert (await async_client.patch(url, headers=_h(env, PM), json={"supplier_name": "Х"})).status_code == 403
    assert (await async_client.patch(url, headers=_h(env, CONTRACTOR), json={"supplier_name": "Х"})).status_code == 404


@pytest.mark.asyncio
async def test_delete_offer_removes_prices_selection_and_file(async_client, db_session, env, fake_s3):
    offer = await _offer(async_client, env)
    await _put_price(async_client, env, offer["id"], "armature", 50000, "т")
    resp = await async_client.put(f"/kp-request-items/{env['armature']}/selected-offer",
                                  headers=_h(env, SUPPLY), json={"offer_id": offer["id"]})
    assert resp.status_code == 200, resp.text
    key = (await db_session.get(KpOffer, offer["id"])).storage_key

    resp = await async_client.delete(f"/kp-offers/{offer['id']}", headers=_h(env, SUPPLY2))
    assert resp.status_code == 204
    db_session.expire_all()
    assert await db_session.get(KpOffer, offer["id"]) is None
    assert (await db_session.execute(select(func.count()).select_from(KpOfferPrice))).scalar() == 0
    assert (await db_session.get(KpRequestItem, env["armature"])).selected_offer_id is None
    assert key not in fake_s3.store


# ---------------------------------------------------------------------------
# Цены
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_manual_price_confirmed_and_matrix(async_client, env):
    offer = await _offer(async_client, env)  # с НДС 22 %
    resp = await _put_price(async_client, env, offer["id"], "armature", 54900, "т")
    assert resp.status_code == 200, resp.text
    cell = resp.json()
    assert cell["source"] == "manual" and cell["confirmed"] is True
    assert cell["normalized_price"] == 45.00

    body = await _detail(async_client, env)
    assert [o["id"] for o in body["offers"]] == [offer["id"]]
    armature = next(i for i in body["items"] if i["id"] == env["armature"])
    assert armature["cells"][0]["normalized_price"] == 45.00
    assert armature["cells"][0]["unit_status"] == "converted"
    assert armature["min_offer_id"] == offer["id"]
    assert armature["best"]["price"] == 45.00
    assert armature["best"]["supplier_name"] == "ООО Металл"
    cement = next(i for i in body["items"] if i["id"] == env["cement"])
    assert cement["cells"][0]["price"] is None
    assert cement["best"] is None


@pytest.mark.asyncio
async def test_price_edit_replaces_ai_draft(async_client, db_session, env):
    offer = await _offer(async_client, env)
    db_session.add(KpOfferPrice(offer_id=offer["id"], item_id=env["cement"], price=9.5, unit="кг",
                                name_in_offer="ЦЕМ I 42,5", source="ai", confidence="low", confirmed=False))
    await db_session.commit()
    resp = await _put_price(async_client, env, offer["id"], "cement", 10, "кг")
    body = resp.json()
    assert body["source"] == "manual" and body["confirmed"] is True and body["confidence"] is None
    assert body["name_in_offer"] == "ЦЕМ I 42,5"
    rows = (await db_session.execute(select(func.count()).select_from(KpOfferPrice))).scalar()
    assert rows == 1


@pytest.mark.asyncio
async def test_confirm_and_delete_price(async_client, db_session, env):
    offer = await _offer(async_client, env)
    db_session.add(KpOfferPrice(offer_id=offer["id"], item_id=env["cement"], price=9.5, unit="кг",
                                source="ai", confidence="high", confirmed=False))
    await db_session.commit()
    url = f"/kp-offers/{offer['id']}/prices/{env['cement']}"
    resp = await async_client.post(f"{url}/confirm", headers=_h(env, SUPPLY2))
    assert resp.status_code == 200, resp.text
    assert resp.json()["confirmed"] is True and resp.json()["source"] == "ai"

    assert (await async_client.delete(url, headers=_h(env, SUPPLY))).status_code == 204
    assert (await async_client.delete(url, headers=_h(env, SUPPLY))).status_code == 404
    assert (await async_client.post(f"{url}/confirm", headers=_h(env, SUPPLY))).status_code == 404


@pytest.mark.asyncio
async def test_price_validation(async_client, env):
    offer = await _offer(async_client, env)
    for price in (0, -5, "abc", None):
        resp = await _put_price(async_client, env, offer["id"], "cement", price)
        assert resp.status_code == 422, price
    # Позиция чужого запроса — нет такой позиции в этом КП.
    resp = await _put_price(async_client, env, offer["id"], "plaster", 100)
    assert resp.status_code == 404
    # «Включает материалы» у цены материала — нельзя.
    resp = await _put_price(async_client, env, offer["id"], "cement", 10, includes_materials=True)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_work_price_includes_materials_overrides_offer(async_client, env):
    offer = (await _upload(async_client, env, request_key="work", who=CONTRACTOR,
                           supplier_name="Бригада", vat_mode="without_vat",
                           includes_materials="true")).json()
    resp = await _put_price(async_client, env, offer["id"], "plaster", 700, "м2", who=CONTRACTOR,
                            includes_materials=False)
    assert resp.status_code == 200, resp.text
    body = await _detail(async_client, env, "work", CONTRACTOR)
    cell = body["items"][0]["cells"][0]
    assert cell["includes_materials"] is False
    assert body["items"][0]["best"]["includes_materials"] is False


@pytest.mark.asyncio
async def test_incompatible_unit_reason_in_matrix(async_client, env):
    offer = await _offer(async_client, env)
    await _put_price(async_client, env, offer["id"], "cement", 350, "мешок")
    body = await _detail(async_client, env)
    cement = next(i for i in body["items"] if i["id"] == env["cement"])
    assert cement["cells"][0]["normalized_price"] is None
    assert "мешок" in cement["cells"][0]["reason"]
    assert cement["best"] is None


@pytest.mark.asyncio
async def test_sales_cannot_edit_prices(async_client, env):
    offer = await _offer(async_client, env)
    assert (await _put_price(async_client, env, offer["id"], "cement", 10, who=PM)).status_code == 403
    assert (await _put_price(async_client, env, offer["id"], "cement", 10, who=CONTRACTOR)).status_code == 404


# ---------------------------------------------------------------------------
# Выбор КП
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_selected_offer_overrides_minimum(async_client, env):
    a = await _offer(async_client, env, supplier_name="А", vat_mode="without_vat")
    b = await _offer(async_client, env, supplier_name="Б", vat_mode="without_vat")
    await _put_price(async_client, env, a["id"], "cement", 9, "кг")
    await _put_price(async_client, env, b["id"], "cement", 10, "кг")
    url = f"/kp-request-items/{env['cement']}/selected-offer"

    body = await _detail(async_client, env)
    cement = next(i for i in body["items"] if i["id"] == env["cement"])
    assert cement["best"]["offer_id"] == a["id"] and cement["min_offer_id"] == a["id"]

    resp = await async_client.put(url, headers=_h(env, PM), json={"offer_id": b["id"]})
    assert resp.status_code == 200, resp.text
    cement = next(i for i in resp.json()["items"] if i["id"] == env["cement"])
    assert cement["selected_offer_id"] == b["id"]
    assert cement["best"]["offer_id"] == b["id"] and cement["best"]["selected"] is True
    assert cement["min_offer_id"] == a["id"]

    resp = await async_client.put(url, headers=_h(env, SUPPLY), json={"offer_id": None})
    cement = next(i for i in resp.json()["items"] if i["id"] == env["cement"])
    assert cement["selected_offer_id"] is None and cement["best"]["offer_id"] == a["id"]


@pytest.mark.asyncio
async def test_selected_offer_validation_and_access(async_client, env):
    a = await _offer(async_client, env)
    work_offer = (await _upload(async_client, env, request_key="work", who=CONTRACTOR,
                                supplier_name="Бригада")).json()
    url = f"/kp-request-items/{env['cement']}/selected-offer"
    resp = await async_client.put(url, headers=_h(env, SUPPLY), json={"offer_id": work_offer["id"]})
    assert resp.status_code == 422
    resp = await async_client.put(url, headers=_h(env, SUPPLY), json={"offer_id": "не-uuid"})
    assert resp.status_code == 422
    resp = await async_client.put(url, headers=_h(env, CONTRACTOR), json={"offer_id": a["id"]})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_sales_can_select_after_done_production_cannot(async_client, db_session, env):
    a = await _offer(async_client, env)
    await _put_price(async_client, env, a["id"], "cement", 10, "кг")
    resp = await async_client.post(f"/kp-requests/{env['material']}/complete",
                                   headers=_h(env, SUPPLY), json={"report": "Ответил один"})
    assert resp.status_code == 200, resp.text
    url = f"/kp-request-items/{env['cement']}/selected-offer"
    assert (await async_client.put(url, headers=_h(env, SUPPLY), json={"offer_id": a["id"]})).status_code == 409
    assert (await async_client.put(url, headers=_h(env, PM), json={"offer_id": a["id"]})).status_code == 200


# ---------------------------------------------------------------------------
# Завершение
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_complete_requires_report(async_client, env):
    await _offer(async_client, env)
    for report in (None, "", "   "):
        resp = await async_client.post(f"/kp-requests/{env['material']}/complete",
                                       headers=_h(env, SUPPLY), json={"report": report})
        assert resp.status_code == 422, report
        assert "отчёт" in json.dumps(resp.json(), ensure_ascii=False).lower()


@pytest.mark.asyncio
async def test_complete_with_draft_price_is_422_with_list(async_client, db_session, env):
    offer = await _offer(async_client, env)
    db_session.add(KpOfferPrice(offer_id=offer["id"], item_id=env["cement"], price=9.5, unit="кг",
                                source="ai", confirmed=False))
    await db_session.commit()
    resp = await async_client.post(f"/kp-requests/{env['material']}/complete",
                                   headers=_h(env, SUPPLY), json={"report": "Готово"})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "Цемент М500" in detail and "ООО Металл" in detail
    db_session.expire_all()
    assert (await db_session.get(KpRequest, env["material"])).status == "in_progress"


@pytest.mark.asyncio
async def test_complete_without_offers_with_report(async_client, db_session, env):
    resp = await async_client.post(f"/kp-requests/{env['material']}/complete",
                                   headers=_h(env, SUPPLY), json={"report": "Никто не ответил"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "done"
    assert body["report"] == "Никто не ответил"
    assert body["completed_by_name"] == "SUPPLY1"
    # Новый запрос завершён без «взять в работу» — завершивший подписан и взявшим.
    assert body["taken_by_name"] == "SUPPLY1"


@pytest.mark.asyncio
async def test_after_done_production_edits_409(async_client, db_session, env):
    offer = await _offer(async_client, env)
    await _put_price(async_client, env, offer["id"], "cement", 10, "кг")
    resp = await async_client.post(f"/kp-requests/{env['material']}/complete",
                                   headers=_h(env, SUPPLY), json={"report": "Готово"})
    assert resp.status_code == 200
    price_url = f"/kp-offers/{offer['id']}/prices/{env['cement']}"
    assert (await _put_price(async_client, env, offer["id"], "cement", 11, "кг")).status_code == 409
    assert (await async_client.post(f"{price_url}/confirm", headers=_h(env, SUPPLY))).status_code == 409
    assert (await async_client.delete(price_url, headers=_h(env, SUPPLY))).status_code == 409
    assert (await async_client.patch(f"/kp-offers/{offer['id']}", headers=_h(env, SUPPLY),
                                     json={"supplier_name": "Х"})).status_code == 409
    assert (await async_client.delete(f"/kp-offers/{offer['id']}", headers=_h(env, SUPPLY))).status_code == 409
    assert (await _upload(async_client, env)).status_code == 409
    second = await async_client.post(f"/kp-requests/{env['material']}/complete",
                                     headers=_h(env, SUPPLY2), json={"report": "Ещё раз"})
    assert second.status_code == 409
    db_session.expire_all()
    assert (await db_session.get(KpRequest, env["material"])).report == "Готово"
    # Файл завершённого КП по-прежнему скачивается.
    assert (await async_client.get(f"/kp-offers/{offer['id']}/download", headers=_h(env, PM))).status_code == 200


@pytest.mark.asyncio
async def test_complete_is_atomic_against_stale_state(db_session, env):
    """Двое нажали «Завершить» одновременно: оба прочли `in_progress`."""
    rid = env["material"]
    await db_session.execute(
        KpRequest.__table__.update().where(KpRequest.id == rid).values(status="in_progress")
    )
    await db_session.commit()
    db_session.expire_all()
    stale = await db_session.get(KpRequest, rid)
    assert stale.status == "in_progress"
    await db_session.execute(
        KpRequest.__table__.update().where(KpRequest.id == rid)
        .values(status="done", completed_by_id=env["supply2"], report="Первый")
    )
    await db_session.commit()
    assert stale.status == "in_progress"  # объект сессии устарел (expire_on_commit=False)
    user = {"sub": str(env["supply1"]), "role": "supply_manager"}
    with pytest.raises(Exception) as exc:
        await kp_offers.complete(db_session, rid, "Второй", user)
    assert getattr(exc.value, "status_code", None) == 409
    db_session.expire_all()
    request = await db_session.get(KpRequest, rid)
    assert request.report == "Первый"


@pytest.mark.asyncio
async def test_complete_forbidden_for_sales_and_foreign_role(async_client, env):
    url = f"/kp-requests/{env['material']}/complete"
    assert (await async_client.post(url, headers=_h(env, PM), json={"report": "x"})).status_code == 403
    assert (await async_client.post(url, headers=_h(env, CONTRACTOR), json={"report": "x"})).status_code == 404


@pytest.mark.asyncio
async def test_reopen_after_complete_allows_edits_again(async_client, env):
    offer = await _offer(async_client, env)
    await async_client.post(f"/kp-requests/{env['material']}/complete",
                            headers=_h(env, SUPPLY), json={"report": "Готово"})
    resp = await async_client.post(f"/kp-requests/{env['material']}/reopen", headers=_h(env, PM))
    assert resp.status_code == 200
    assert (await _put_price(async_client, env, offer["id"], "cement", 11, "кг")).status_code == 200


@pytest.mark.asyncio
async def test_detail_permissions_for_editing(async_client, db_session, env):
    body = await _detail(async_client, env, who=SUPPLY)
    # Новый: загрузить КП и завершить можно, выбирать ещё нечего.
    assert body["permissions"]["can_edit_offers"] is True
    assert body["permissions"]["can_complete"] is True
    assert body["permissions"]["can_select_offer"] is False
    await _offer(async_client, env)
    body = await _detail(async_client, env, who=SUPPLY)
    assert body["permissions"]["can_select_offer"] is True
    body = await _detail(async_client, env, who=PM)
    assert body["permissions"]["can_edit_offers"] is False
    assert body["permissions"]["can_complete"] is False
    assert body["permissions"]["can_select_offer"] is True
    await db_session.execute(
        KpRequest.__table__.update().where(KpRequest.id == env["material"]).values(status="done")
    )
    await db_session.commit()
    db_session.expire_all()
    body = await _detail(async_client, env, who=SUPPLY)
    assert body["permissions"]["can_edit_offers"] is False
    assert body["permissions"]["can_complete"] is False
    assert body["permissions"]["can_select_offer"] is False
    body = await _detail(async_client, env, who=PM)
    assert body["permissions"]["can_select_offer"] is True


@pytest.mark.asyncio
async def test_price_on_offer_deleted_meanwhile_is_404(async_client, db_session, env):
    """Коллега удалил КП, пока цена ждала строку запроса: 404, а не цена без КП."""
    offer = await _offer(async_client, env)
    stale = await db_session.get(KpOffer, offer["id"])
    assert stale is not None
    real_get = kp_offers.get_offer

    async def get_then_delete(db, offer_id, user):
        found = await real_get(db, offer_id, user)
        await db.execute(KpOffer.__table__.delete().where(KpOffer.id == offer_id))
        return found

    import unittest.mock as mock
    with mock.patch.object(kp_offers, "get_offer", get_then_delete):
        resp = await _put_price(async_client, env, offer["id"], "cement", 10, "кг")
    assert resp.status_code == 404
    db_session.expire_all()
    assert (await db_session.execute(select(func.count()).select_from(KpOfferPrice))).scalar() == 0
