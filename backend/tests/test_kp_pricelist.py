"""Цены из КП в прайс (план 2026-09-14-zapros-kp.md, фаза 7; критерии 23–28).

* материал — итоговая цена позиции (выбранное КП или минимум) перезаписывает
  цену материала;
* работа — каждая подтверждённая приведённая цена каждого КП пишется отдельным
  подрядчиком «КП: <поставщик>», прочие ключи целы;
* «цена включает материалы» и несводимая единица — не пишутся, причина в сводке;
* дата «Цена от» — по общему правилу (повтор той же цены дату не двигает);
* повторная запись после возврата в работу снимает свои прежние ключи, если
  их с тех пор никто не переписал;
* сбой записи не отменяет завершение: `pricelist_status = failed`, повтор кнопкой.
"""
from datetime import datetime, timezone
from typing import Optional

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, update

from app.models.kp_request import KpOffer, KpOfferPrice, KpRequest, KpRequestFile, KpRequestItem
from app.models.price import PriceMaterial, PriceWork
from app.models.project import Project
from app.models.user import User
from app.models.workflow_card import WorkflowCard
from app.services import kp_pricelist, price_bulk, price_service
from app.utils.auth import create_access_token, hash_password
from app.utils.price_min import ESTIMATE_CONTRACTOR

OLD = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
_PASSWORD_HASH = hash_password("x1234")
_MODELS = (KpOfferPrice, KpRequestItem, KpOffer, KpRequestFile, KpRequest,
           WorkflowCard, Project, User, PriceWork, PriceMaterial)


def _auth(user_id: int, role: str) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id, role, f'u{user_id}')}"}


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo else value


async def _wipe(db):
    for model in _MODELS:
        await db.execute(model.__table__.delete())
    await db.commit()


@pytest_asyncio.fixture
async def env(db_session, fake_s3, monkeypatch):
    async def _none(_name: str) -> Optional[list]:
        return None

    async def _noop_cache(db):
        return None

    monkeypatch.setattr(price_bulk, "_generate_embedding_safe", _none)
    monkeypatch.setattr(price_service, "load_cache", _noop_cache)
    await _wipe(db_session)

    def user(name, role):
        return User(username=name, role=role, full_name=name.upper(), is_active=True,
                    password_hash=_PASSWORD_HASH)

    users = {
        "pm1": user("pm1", "project_manager"),
        "pm2": user("pm2", "project_manager"),
        "supply1": user("supply1", "supply_manager"),
        "contractor1": user("contractor1", "contractor_manager"),
    }
    db_session.add_all(users.values())
    await db_session.flush()
    project = Project(name="Объект", owner_id=users["pm1"].id)
    db_session.add(project)
    await db_session.flush()
    card = WorkflowCard(project_id=str(project.id), name="КР", stage="estimate")
    db_session.add(card)
    await db_session.flush()

    def request(category, role, taker):
        return KpRequest(
            project_id=str(project.id), card_id=str(card.id), source_kind="estimate",
            category=category, target_role=role, status="in_progress",
            author_id=users["pm1"].id, taken_by_id=users[taker].id,
        )

    material = request("material", "supply_manager", "supply1")
    work = request("work", "contractor_manager", "contractor1")
    db_session.add_all([material, work])
    await db_session.flush()
    items = {
        "armature": KpRequestItem(request_id=material.id, position=0, item_type="material",
                                  name="Арматура А500", unit="кг", qty=2000, source_row_ids=["r1"]),
        "cement": KpRequestItem(request_id=material.id, position=1, item_type="material",
                                name="Цемент М500", unit="кг", qty=500, source_row_ids=["r2"]),
        "plaster": KpRequestItem(request_id=work.id, position=0, item_type="work",
                                 name="Штукатурка стен", unit="м2", qty=100, source_row_ids=["r3"]),
        "masonry": KpRequestItem(request_id=work.id, position=1, item_type="work",
                                 name="Кладка перегородок", unit="м2", qty=40, source_row_ids=["r4"]),
    }
    db_session.add_all(items.values())
    await db_session.commit()

    out = {name: u.id for name, u in users.items()}
    out.update(material=str(material.id), work=str(work.id),
               **{name: str(i.id) for name, i in items.items()})
    yield out
    await _wipe(db_session)


async def _add_offer(db, request_id, supplier, *, vat_mode="without_vat", vat_rate=None,
                     includes_materials=False) -> str:
    offer = KpOffer(request_id=request_id, supplier_name=supplier, vat_mode=vat_mode,
                    vat_rate=vat_rate, includes_materials=includes_materials)
    db.add(offer)
    await db.commit()
    return str(offer.id)


async def _add_price(db, offer_id, item_id, price, unit=None, *, confirmed=True,
                     includes_materials=None, source="manual"):
    db.add(KpOfferPrice(offer_id=offer_id, item_id=item_id, price=price, unit=unit,
                        confirmed=confirmed, includes_materials=includes_materials, source=source))
    await db.commit()


async def _set_status(db, request_id, value):
    await db.execute(update(KpRequest).where(KpRequest.id == request_id).values(status=value))
    await db.commit()
    db.expire_all()


async def _work_row(db, name) -> PriceWork:
    db.expire_all()
    return (await db.execute(select(PriceWork).where(PriceWork.name == name))).scalar_one()


async def _material_row(db, name) -> PriceMaterial:
    db.expire_all()
    return (await db.execute(select(PriceMaterial).where(PriceMaterial.name == name))).scalar_one()


async def _complete(client, env, request_key, who, role, report="Готово"):
    return await client.post(f"/kp-requests/{env[request_key]}/complete",
                             headers=_auth(env[who], role), json={"report": report})


# ---------------------------------------------------------------------------
# Материалы
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_material_overwritten_by_minimum_kp(async_client, db_session, env):
    db_session.add(PriceMaterial(name="Арматура А500", unit="кг", price=70.0, updated_at=OLD))
    await db_session.commit()
    a = await _add_offer(db_session, env["material"], "ООО Металл", vat_mode="with_vat", vat_rate=22)
    b = await _add_offer(db_session, env["material"], "ООО Сталь")
    # 54 900 ₽/т с НДС 22 % → 45,00 ₽/кг; 47 ₽/кг без НДС → 47,00.
    await _add_price(db_session, a, env["armature"], 54900, "т")
    await _add_price(db_session, b, env["armature"], 47, "кг")

    resp = await _complete(async_client, env, "material", "supply1", "supply_manager")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "done"
    assert body["pricelist_status"] == "done"
    assert body["pricelist_summary"]["updated"] == 1
    assert body["pricelist_summary"]["added"] == 0
    # Цемент без цены — пропуск с причиной.
    assert body["pricelist_summary"]["skipped"] == {kp_pricelist.SKIP_NO_PRICE: 1}
    assert body["pricelist_written_at"]

    row = await _material_row(db_session, "Арматура А500")
    assert row.price == 45.0
    assert _naive(row.updated_at) != _naive(OLD)


@pytest.mark.asyncio
async def test_material_selected_offer_beats_minimum_and_new_row_added(db_session, env):
    a = await _add_offer(db_session, env["material"], "А")
    b = await _add_offer(db_session, env["material"], "Б")
    await _add_price(db_session, a, env["cement"], 10, "кг")
    await _add_price(db_session, b, env["cement"], 12, "кг")
    await db_session.execute(update(KpRequestItem).where(KpRequestItem.id == env["cement"])
                             .values(selected_offer_id=b))
    await _set_status(db_session, env["material"], "done")

    request = await kp_pricelist.write(db_session, env["material"])
    assert request.pricelist_status == "done"
    assert request.pricelist_summary["added"] == 1
    row = await _material_row(db_session, "Цемент М500")
    assert row.price == 12.0
    assert row.unit == "кг"


@pytest.mark.asyncio
async def test_material_unit_not_compatible_with_price_list_skipped(db_session, env):
    db_session.add(PriceMaterial(name="Цемент М500", unit="мешок", price=450.0, updated_at=OLD))
    await db_session.commit()
    a = await _add_offer(db_session, env["material"], "А")
    await _add_price(db_session, a, env["cement"], 10, "кг")
    await _set_status(db_session, env["material"], "done")

    request = await kp_pricelist.write(db_session, env["material"])
    skipped = request.pricelist_summary["skipped"]
    assert skipped[price_bulk.SKIP_UNIT_MISMATCH] == 1
    row = await _material_row(db_session, "Цемент М500")
    assert row.price == 450.0


@pytest.mark.asyncio
async def test_kp_unit_not_compatible_with_item_skipped(db_session, env):
    a = await _add_offer(db_session, env["material"], "А")
    await _add_price(db_session, a, env["cement"], 400, "мешок")
    await _set_status(db_session, env["material"], "done")

    request = await kp_pricelist.write(db_session, env["material"])
    assert request.pricelist_summary["skipped"][kp_pricelist.SKIP_UNIT_INCOMPATIBLE] == 1
    db_session.expire_all()
    assert (await db_session.execute(select(PriceMaterial))).scalars().all() == []


# ---------------------------------------------------------------------------
# Работы
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_work_two_offers_two_keys_estimate_price_kept(async_client, db_session, env):
    db_session.add(PriceWork(name="Штукатурка стен", unit="м2",
                             prices={ESTIMATE_CONTRACTOR: 450.0, "Подрядчик": 400.0},
                             min_price=450.0, updated_at=OLD))
    await db_session.commit()
    a = await _add_offer(db_session, env["work"], "СтройА")
    b = await _add_offer(db_session, env["work"], "СтройБ", vat_mode="with_vat", vat_rate=22)
    await _add_price(db_session, a, env["plaster"], 500, "м2")
    await _add_price(db_session, b, env["plaster"], 732, "м2")  # 732 / 1,22 = 600

    resp = await _complete(async_client, env, "work", "contractor1", "contractor_manager")
    assert resp.status_code == 200, resp.text
    assert resp.json()["pricelist_status"] == "done"

    row = await _work_row(db_session, "Штукатурка стен")
    assert row.prices == {ESTIMATE_CONTRACTOR: 450.0, "Подрядчик": 400.0,
                          "КП: СтройА": 500.0, "КП: СтройБ": 600.0}
    assert row.min_price == 500.0


@pytest.mark.asyncio
async def test_work_includes_materials_not_written(db_session, env):
    a = await _add_offer(db_session, env["work"], "СтройА", includes_materials=True)
    b = await _add_offer(db_session, env["work"], "СтройБ")
    await _add_price(db_session, a, env["plaster"], 900, "м2")
    await _add_price(db_session, b, env["plaster"], 700, "м2", includes_materials=True)
    await _add_price(db_session, b, env["masonry"], 300, "м2")
    await _set_status(db_session, env["work"], "done")

    request = await kp_pricelist.write(db_session, env["work"])
    summary = request.pricelist_summary
    assert summary["skipped"] == {kp_pricelist.SKIP_INCLUDES_MATERIALS: 2}
    assert summary["added"] == 1
    db_session.expire_all()
    names = [w.name for w in (await db_session.execute(select(PriceWork))).scalars().all()]
    assert names == ["Кладка перегородок"]


@pytest.mark.asyncio
async def test_unconfirmed_price_not_written(db_session, env):
    a = await _add_offer(db_session, env["work"], "СтройА")
    await _add_price(db_session, a, env["plaster"], 500, "м2", confirmed=False, source="ai")
    await _set_status(db_session, env["work"], "done")
    request = await kp_pricelist.write(db_session, env["work"])
    assert request.pricelist_summary["added"] == 0
    assert request.pricelist_summary["skipped"] == {kp_pricelist.SKIP_NO_PRICE: 2}


@pytest.mark.asyncio
async def test_repeat_with_same_price_keeps_date(async_client, db_session, env):
    a = await _add_offer(db_session, env["work"], "СтройА")
    await _add_price(db_session, a, env["plaster"], 500, "м2")
    assert (await _complete(async_client, env, "work", "contractor1", "contractor_manager")).status_code == 200
    await db_session.execute(update(PriceWork).values(updated_at=OLD))
    await db_session.commit()

    assert (await async_client.post(f"/kp-requests/{env['work']}/reopen",
                                    headers=_auth(env["pm1"], "project_manager"))).status_code == 200
    resp = await _complete(async_client, env, "work", "contractor1", "contractor_manager", "Ещё раз")
    assert resp.status_code == 200, resp.text
    assert resp.json()["pricelist_status"] == "done"

    row = await _work_row(db_session, "Штукатурка стен")
    assert row.prices == {"КП: СтройА": 500.0}
    assert _naive(row.updated_at) == _naive(OLD)


@pytest.mark.asyncio
async def test_renamed_supplier_removes_old_key_unless_overwritten(db_session, env):
    a = await _add_offer(db_session, env["work"], "СтройА")
    await _add_price(db_session, a, env["plaster"], 500, "м2")
    await _add_price(db_session, a, env["masonry"], 300, "м2")
    await _set_status(db_session, env["work"], "done")
    await kp_pricelist.write(db_session, env["work"])

    # Другой запрос тем временем переписал ключ у кладки.
    masonry = await _work_row(db_session, "Кладка перегородок")
    await db_session.execute(update(PriceWork).where(PriceWork.id == masonry.id)
                             .values(prices={"КП: СтройА": 280.0}, min_price=280.0))
    await db_session.execute(update(KpOffer).where(KpOffer.id == a).values(supplier_name="СтройА-Групп"))
    await db_session.commit()

    request = await kp_pricelist.write(db_session, env["work"])
    assert request.pricelist_status == "done"
    summary = request.pricelist_summary
    assert summary["retired"] == 1
    written = {(w["name_key"], w["contractor"]) for w in summary["written"]}
    assert ("кладка перегородок", "КП: СтройА-Групп") in written

    plaster = await _work_row(db_session, "Штукатурка стен")
    assert plaster.prices == {"КП: СтройА-Групп": 500.0}
    assert plaster.min_price == 500.0
    masonry = await _work_row(db_session, "Кладка перегородок")
    assert masonry.prices == {"КП: СтройА": 280.0, "КП: СтройА-Групп": 300.0}
    assert masonry.min_price == 280.0


# ---------------------------------------------------------------------------
# Сбой, повтор и права
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_write_failure_keeps_request_done_and_retry_writes(async_client, db_session, env, monkeypatch):
    a = await _add_offer(db_session, env["work"], "СтройА")
    await _add_price(db_session, a, env["plaster"], 500, "м2")
    real_add = price_bulk.add_items

    async def _boom(*args, **kwargs):
        raise RuntimeError("Нет связи с базой прайса")

    monkeypatch.setattr(price_bulk, "add_items", _boom)
    resp = await _complete(async_client, env, "work", "contractor1", "contractor_manager")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "done"
    assert body["pricelist_status"] == "failed"
    assert "Нет связи" in body["pricelist_error"]
    db_session.expire_all()
    assert (await db_session.execute(select(PriceWork))).scalars().all() == []

    monkeypatch.setattr(price_bulk, "add_items", real_add)
    resp = await async_client.post(f"/kp-requests/{env['work']}/pricelist/retry",
                                   headers=_auth(env["contractor1"], "contractor_manager"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pricelist_status"] == "done"
    assert body["pricelist_error"] is None
    row = await _work_row(db_session, "Штукатурка стен")
    assert row.prices == {"КП: СтройА": 500.0}


@pytest.mark.asyncio
async def test_retry_access_and_status(async_client, db_session, env):
    url = f"/kp-requests/{env['work']}/pricelist/retry"
    # Не завершён — записывать нечего.
    resp = await async_client.post(url, headers=_auth(env["contractor1"], "contractor_manager"))
    assert resp.status_code == 409
    await _set_status(db_session, env["work"], "done")
    # Чужая роль запроса не видит.
    resp = await async_client.post(url, headers=_auth(env["supply1"], "supply_manager"))
    assert resp.status_code == 404
    # Продажи, но не автор и не руководитель.
    resp = await async_client.post(url, headers=_auth(env["pm2"], "project_manager"))
    assert resp.status_code == 403
    # Автор запроса может.
    resp = await async_client.post(url, headers=_auth(env["pm1"], "project_manager"))
    assert resp.status_code == 200, resp.text
    assert resp.json()["pricelist_status"] == "done"


# ---------------------------------------------------------------------------
# Гонка записи: чужой ключ, записанный между чтением и записью
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_items_merges_key_into_fresh_prices(db_session, env, monkeypatch):
    """Два завершения пишут одну работу: ключ «КП: …» соседа не стирается.

    Между чтением прайса и записью идёт медленный расчёт векторов новых позиций;
    сосед успевает записать свой ключ. Слияние обязано идти в свежий словарь.
    """
    db_session.add(PriceWork(name="Штукатурка стен", unit="м2",
                             prices={"КП: СтройА": 500.0}, min_price=500.0, updated_at=OLD))
    await db_session.commit()

    async def _slow_embedding(_name):
        # Пока «считается вектор», другое завершение записало свой ключ.
        await db_session.execute(
            update(PriceWork).where(PriceWork.name == "Штукатурка стен")
            .values(prices={"КП: СтройА": 500.0, "КП: СтройВ": 450.0}, min_price=450.0)
        )
        return None

    monkeypatch.setattr(price_bulk, "_generate_embedding_safe", _slow_embedding)
    result = await price_bulk.add_items(db_session, [
        {"kind": "work", "name": "Кладка перегородок", "unit": "м2", "price": 300,
         "contractor": "КП: СтройБ"},
        {"kind": "work", "name": "Штукатурка стен", "unit": "м2", "price": 600,
         "contractor": "КП: СтройБ"},
    ], commit=False, with_written=True)
    await db_session.commit()

    assert result["added"] == 1 and result["updated"] == 1
    row = await _work_row(db_session, "Штукатурка стен")
    assert row.prices == {"КП: СтройА": 500.0, "КП: СтройВ": 450.0, "КП: СтройБ": 600.0}
    assert row.min_price == 450.0


async def _other_done_request(db, env, written, *, deleted=False, status="done") -> str:
    source = await db.get(KpRequest, env["work"])
    other = KpRequest(
        project_id=source.project_id, card_id=source.card_id, source_kind="estimate",
        category="work", target_role="contractor_manager", status=status,
        author_id=env["pm1"], pricelist_status="done",
        pricelist_summary={"added": 0, "updated": 0, "skipped": {}, "retired": 0, "written": written},
        deleted_at=datetime.now(timezone.utc) if deleted else None,
    )
    db.add(other)
    await db.commit()
    return str(other.id)


@pytest.mark.asyncio
async def test_stale_key_kept_when_other_done_request_wrote_same(db_session, env):
    """Тот же ключ с тем же значением записал другой завершённый запрос — не снимаем."""
    a = await _add_offer(db_session, env["work"], "СтройА")
    await _add_price(db_session, a, env["plaster"], 500, "м2")
    await _add_price(db_session, a, env["masonry"], 300, "м2")
    await _set_status(db_session, env["work"], "done")
    await kp_pricelist.write(db_session, env["work"])

    same = [{"kind": "work", "name_key": "штукатурка стен", "contractor": "КП: СтройА", "value": 500.0}]
    await _other_done_request(db_session, env, same)
    # Удалённый и не завершённый запросы не в счёт: кладку снимаем.
    masonry = [{"kind": "work", "name_key": "кладка перегородок", "contractor": "КП: СтройА",
                "value": 300.0}]
    await _other_done_request(db_session, env, masonry, deleted=True)
    await _other_done_request(db_session, env, masonry, status="in_progress")

    await db_session.execute(update(KpOffer).where(KpOffer.id == a).values(supplier_name="СтройА-Групп"))
    await db_session.commit()
    request = await kp_pricelist.write(db_session, env["work"])
    assert request.pricelist_summary["retired"] == 1

    plaster = await _work_row(db_session, "Штукатурка стен")
    assert plaster.prices == {"КП: СтройА": 500.0, "КП: СтройА-Групп": 500.0}
    masonry_row = await _work_row(db_session, "Кладка перегородок")
    assert masonry_row.prices == {"КП: СтройА-Групп": 300.0}


@pytest.mark.asyncio
async def test_same_name_positions_in_request_not_written(db_session, env):
    """Две позиции запроса с одним ключом прайса — какая цена верна, система не выбирает."""
    db_session.add(KpRequestItem(request_id=env["material"], position=2, item_type="material",
                                 name="арматура  А500", unit="кг", qty=10, source_row_ids=["r9"]))
    work_twin = KpRequestItem(request_id=env["work"], position=2, item_type="work",
                              name="ШТУКАТУРКА стен", unit="м2", qty=5, source_row_ids=["r8"])
    db_session.add(work_twin)
    await db_session.commit()
    twin = (await db_session.execute(
        select(KpRequestItem).where(KpRequestItem.name == "арматура  А500"))).scalar_one()
    twin_id, work_twin_id = str(twin.id), str(work_twin.id)

    m = await _add_offer(db_session, env["material"], "ООО Сталь")
    await _add_price(db_session, m, env["armature"], 85, "кг")
    await _add_price(db_session, m, twin_id, 90, "кг")
    await _add_price(db_session, m, env["cement"], 10, "кг")
    await _set_status(db_session, env["material"], "done")
    request = await kp_pricelist.write(db_session, env["material"])
    summary = request.pricelist_summary
    assert summary["skipped"] == {kp_pricelist.SKIP_DUPLICATE_NAME: 2}
    assert summary["added"] == 1
    db_session.expire_all()
    names = [r.name for r in (await db_session.execute(select(PriceMaterial))).scalars().all()]
    assert names == ["Цемент М500"]

    # Работа: коллизия — по имени и подрядчику; у другого подрядчика её нет.
    a = await _add_offer(db_session, env["work"], "СтройА")
    b = await _add_offer(db_session, env["work"], "СтройБ")
    await _add_price(db_session, a, env["plaster"], 500, "м2")
    await _add_price(db_session, a, work_twin_id, 550, "м2")
    await _add_price(db_session, b, env["plaster"], 480, "м2")
    await _set_status(db_session, env["work"], "done")
    request = await kp_pricelist.write(db_session, env["work"])
    assert request.pricelist_summary["skipped"] == {
        kp_pricelist.SKIP_DUPLICATE_NAME: 2, kp_pricelist.SKIP_NO_PRICE: 1,
    }
    row = await _work_row(db_session, "Штукатурка стен")
    assert row.prices == {"КП: СтройБ": 480.0}


@pytest.mark.asyncio
async def test_select_offer_after_done_rewrites_pricelist(async_client, db_session, env):
    """Продажи сменили выбранное КП в завершённом запросе — прайс получает цену выбора."""
    a = await _add_offer(db_session, env["material"], "А")
    b = await _add_offer(db_session, env["material"], "Б")
    await _add_price(db_session, a, env["cement"], 10, "кг")
    await _add_price(db_session, b, env["cement"], 12, "кг")
    resp = await _complete(async_client, env, "material", "supply1", "supply_manager")
    assert resp.status_code == 200, resp.text
    assert (await _material_row(db_session, "Цемент М500")).price == 10.0

    url = f"/kp-request-items/{env['cement']}/selected-offer"
    resp = await async_client.put(url, headers=_auth(env["pm1"], "project_manager"), json={"offer_id": b})
    assert resp.status_code == 200, resp.text
    assert resp.json()["pricelist_status"] == "done"
    assert (await _material_row(db_session, "Цемент М500")).price == 12.0

    # Снять выбор — снова минимум.
    resp = await async_client.put(url, headers=_auth(env["pm1"], "project_manager"), json={"offer_id": None})
    assert resp.status_code == 200, resp.text
    assert (await _material_row(db_session, "Цемент М500")).price == 10.0


@pytest.mark.asyncio
async def test_select_offer_in_progress_does_not_write_pricelist(async_client, db_session, env):
    a = await _add_offer(db_session, env["material"], "А")
    await _add_price(db_session, a, env["cement"], 10, "кг")
    url = f"/kp-request-items/{env['cement']}/selected-offer"
    resp = await async_client.put(url, headers=_auth(env["supply1"], "supply_manager"), json={"offer_id": a})
    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    assert (await db_session.execute(select(PriceMaterial))).scalars().all() == []
