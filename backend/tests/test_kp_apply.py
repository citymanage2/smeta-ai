"""Цены из КП в оптимизацию (план 2026-09-14-zapros-kp.md, фаза 8б; критерии 30–37).

* материал — `price_material`, работа — `price_work`; цена без коэффициента,
  без НДС, в единице строки; коэффициент версии сохраняется;
* сопоставление: `row_id` источника (запрос с этой оптимизации) → № исходной
  сметы + наименование → тип + наименование + единица (+ лист); все строки
  одного наименования получают цену, разные листы — «неоднозначно»;
* несколько запросов на строку — минимум;
* предпросмотр ничего не пишет; применение — новая версия «Цены из КП» одной
  транзакцией, исходная не меняется, устаревшая ревизия — 409 без версии;
* откат версии возвращает цены; сигналов журнала корректировок нет;
* «цена включает материалы» — цена материала строки не меняется.
"""
from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, update

from app.models.correction_signal import CorrectionSignal
from app.models.estimate_version import EstimateVersion
from app.models.history import TaskHistory
from app.models.kp_request import KpOffer, KpOfferPrice, KpRequest, KpRequestItem
from app.models.task import Task
from app.models.workflow_card import WorkflowCard
from tests.helpers.kp import add_offer, add_price, auth

COEF = {"work": 1.0, "material": 1.1, "scope": "all"}


def _row(rid, type_, name, unit, qty, pw=None, pm=None, *, sheet=None, source_no=None):
    return {"id": rid, "lineage_id": rid, "num": None, "type": type_, "name": name,
            "unit": unit, "qty": qty, "price_work": pw, "price_material": pm,
            "cost": None, "selected": False, "sheet": sheet, "source_no": source_no}


def _base_rows() -> list:
    return [
        _row("s1", "section", "Раздел 1", "", None),
        _row("m1", "material", "Арматура А500", "т", 2, pm=90000),
        _row("w1", "work", "Штукатурка стен", "м2", 100, pw=500, pm=300),
        _row("w2", "work", "Штукатурка стен", "м2", 50, pw=520),
    ]


@pytest_asyncio.fixture
async def env(db_session, make_kp_env):
    """Пользователи, проект и карточка оптимизации с исходной версией; запросы — в тестах."""
    env = await make_kp_env(stage="optimization", requests=False)
    task = Task(
        owner_id=env["pm1"], user_role="project_manager", task_type="ESTIMATE_OPTIMIZATION",
        status="completed", input_files=[], input_file_data=[], chat_history=[],
        project_id=env["project"],
    )
    db_session.add(task)
    await db_session.flush()
    card = await db_session.get(WorkflowCard, env["card"])
    card.optimization_task_id = str(task.id)
    version = EstimateVersion(
        task_id=str(task.id), version_number=0, version_label="original",
        version_display_name="Исходная", rows=_base_rows(), file_slot="result",
        task_type="ESTIMATE_OPTIMIZATION", coefficient=dict(COEF), rev=3,
    )
    db_session.add(version)
    await db_session.commit()
    env.update(task=str(task.id), version=str(version.id))
    return env


async def _request(db, env, category, items, *, source_kind="estimate", source_task_id=None,
                   status="done") -> tuple[str, list[str]]:
    role = "supply_manager" if category == "material" else "contractor_manager"
    request = KpRequest(
        project_id=env["project"], card_id=env["card"], source_kind=source_kind,
        source_task_id=source_task_id, category=category, target_role=role, status=status,
        author_id=env["pm1"], completed_at=datetime.now(timezone.utc),
    )
    db.add(request)
    await db.flush()
    ids = []
    for pos, spec in enumerate(items):
        item = KpRequestItem(request_id=request.id, position=pos, item_type=category,
                             name=spec["name"], unit=spec.get("unit"), qty=spec.get("qty"),
                             sheet=spec.get("sheet"), source_no=spec.get("source_no"),
                             source_row_ids=spec.get("row_ids", []))
        db.add(item)
        await db.flush()
        ids.append(str(item.id))
    await db.commit()
    return str(request.id), ids


async def _preview(client, env, version_id=None):
    return await client.post(
        "/kp-requests/apply/preview", headers=auth(env["pm1"], "project_manager"),
        json={"card_id": env["card"], "version_id": version_id or env["version"]},
    )


async def _apply(client, env, preview: dict, choices=None, client_rev=None, who=None):
    user_id, role = who or (env["pm1"], "project_manager")
    return await client.post(
        "/kp-requests/apply", headers=auth(user_id, role),
        json={"card_id": env["card"], "version_id": preview["version_id"],
              "client_rev": preview["rev"] if client_rev is None else client_rev,
              "preview_hash": preview["preview_hash"], "choices": choices or {}},
    )


async def _versions(db, env) -> list[EstimateVersion]:
    db.expire_all()
    return list((await db.execute(
        select(EstimateVersion).where(EstimateVersion.task_id == env["task"])
        .order_by(EstimateVersion.version_number)
    )).scalars().all())


def _by_id(rows) -> dict:
    return {r.get("id") or r["row_id"]: r for r in rows}


# ---------------------------------------------------------------------------
# Поле цены по типу строки, коэффициент, новая версия
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_material_and_work_prices_go_to_new_version(async_client, db_session, env):
    mat_req, (armature,) = await _request(
        db_session, env, "material", [{"name": "Арматура А500", "unit": "т", "qty": 2}])
    work_req, (plaster,) = await _request(
        db_session, env, "work", [{"name": "Штукатурка стен", "unit": "м2", "qty": 150}])
    steel = await add_offer(db_session, mat_req, "ООО Сталь", offer_date=date(2026, 9, 10))
    # 102 000 с НДС 20 % → 85 000 без НДС
    await add_price(db_session, steel, armature, 102000, "т")
    await db_session.execute(update(KpOffer).where(KpOffer.id == steel)
                             .values(vat_mode="with_vat", vat_rate=20))
    await db_session.commit()
    brigade = await add_offer(db_session, work_req, "Бригада", offer_date=date(2026, 9, 11))
    await add_price(db_session, brigade, plaster, 450, "м2")

    resp = await _preview(async_client, env)
    assert resp.status_code == 200, resp.text
    preview = resp.json()
    assert preview["rev"] == 3
    rows = _by_id(preview["rows"])
    assert rows["m1"]["field"] == "price_material" and rows["m1"]["new_price"] == 85000
    assert rows["m1"]["old_price"] == 90000
    assert {rows["w1"]["field"], rows["w2"]["field"]} == {"price_work"}
    assert rows["w1"]["new_price"] == 450 and rows["w2"]["new_price"] == 450
    assert preview["not_found"] == [] and preview["ambiguous"] == []

    resp = await _apply(async_client, env, preview)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["applied_rows"] == 3

    source, clone = await _versions(db_session, env)
    assert body["version_id"] == str(clone.id)
    # Новая версия — отдельной вкладкой: у неё своё имя, не как у исходной.
    assert clone.version_display_name and clone.version_display_name != source.version_display_name
    assert source.rows == _base_rows()  # исходная не изменена
    assert clone.coefficient == COEF
    new = _by_id(clone.rows)
    # Коэффициент материалов 1.1 к цене не применён: в документ — исходная цена
    assert new["m1"]["price_material"] == 85000 and new["m1"]["price_work"] is None
    assert new["m1"]["cost"] == 170000
    assert new["w1"]["price_work"] == 450 and new["w1"]["price_material"] == 300
    assert new["w2"]["price_work"] == 450
    assert new["s1"] == _base_rows()[0]
    assert new["m1"]["kp_ref"] == {
        "request_id": mat_req, "offer_id": steel, "supplier": "ООО Сталь",
        "offer_date": "2026-09-10", "offers_count": 1, "includes_materials": False,
        # Какая цена и какой записана — без коэффициента: пометка действует, пока она та же.
        "field": "price_material", "price": 85000,
    }
    assert new["w1"]["kp_ref"]["field"] == "price_work" and new["w1"]["kp_ref"]["price"] == 450
    assert new["m1"]["optimization_note"] == "Из КП: ООО Сталь от 10.09.2026"

    clone_id = str(clone.id)
    db_session.expire_all()
    for rid in (mat_req, work_req):
        request = await db_session.get(KpRequest, rid)
        assert request.applied_at is not None
        assert request.applied_version_id == clone_id


@pytest.mark.asyncio
async def test_history_entry_and_no_correction_signals(async_client, db_session, env):
    work_req, (plaster,) = await _request(
        db_session, env, "work", [{"name": "Штукатурка стен", "unit": "м2"}])
    offer = await add_offer(db_session, work_req, "Бригада")
    await add_price(db_session, offer, plaster, 450)

    preview = (await _preview(async_client, env)).json()
    assert (await _apply(async_client, env, preview)).status_code == 200

    db_session.expire_all()
    entries = (await db_session.execute(
        select(TaskHistory).where(TaskHistory.task_id == env["task"]))).scalars().all()
    assert len(entries) == 1
    assert entries[0].operation_type == "kp_prices"
    assert entries[0].document_kind == "optimization"
    signals = (await db_session.execute(select(CorrectionSignal))).scalars().all()
    assert signals == []


@pytest.mark.asyncio
async def test_preview_writes_nothing(async_client, db_session, env):
    work_req, (plaster,) = await _request(
        db_session, env, "work", [{"name": "Штукатурка стен", "unit": "м2"}])
    offer = await add_offer(db_session, work_req, "Бригада")
    await add_price(db_session, offer, plaster, 450)

    assert (await _preview(async_client, env)).status_code == 200
    (source,) = await _versions(db_session, env)
    assert source.rev == 3 and source.rows == _base_rows()
    request = await db_session.get(KpRequest, work_req)
    assert request.applied_at is None


# ---------------------------------------------------------------------------
# Сопоставление
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_different_sheets_ambiguous_until_chosen(async_client, db_session, env):
    rows = _base_rows()
    rows[2]["sheet"], rows[3]["sheet"] = "ОПС", "СОТ"
    await db_session.execute(update(EstimateVersion).where(EstimateVersion.id == env["version"])
                             .values(rows=rows))
    await db_session.commit()
    work_req, (plaster,) = await _request(
        db_session, env, "work", [{"name": "Штукатурка стен", "unit": "м2"}])
    offer = await add_offer(db_session, work_req, "Бригада")
    await add_price(db_session, offer, plaster, 450)

    preview = (await _preview(async_client, env)).json()
    assert preview["rows"] == []
    (amb,) = preview["ambiguous"]
    assert amb["item_id"] == plaster
    assert {c["row_id"] for c in amb["candidates"]} == {"w1", "w2"}

    # Без выбора — применять нечего, версии нет
    resp = await _apply(async_client, env, preview)
    assert resp.status_code == 422
    assert len(await _versions(db_session, env)) == 1

    # Чужая строка в выборе — 422
    resp = await _apply(async_client, env, preview, choices={plaster: ["m1"]})
    assert resp.status_code == 422

    resp = await _apply(async_client, env, preview, choices={plaster: ["w2"]})
    assert resp.status_code == 200, resp.text
    _, clone = await _versions(db_session, env)
    new = _by_id(clone.rows)
    assert new["w2"]["price_work"] == 450 and new["w1"]["price_work"] == 500


@pytest.mark.asyncio
async def test_sheet_of_item_narrows_match(async_client, db_session, env):
    rows = _base_rows()
    rows[2]["sheet"], rows[3]["sheet"] = "ОПС", "СОТ"
    await db_session.execute(update(EstimateVersion).where(EstimateVersion.id == env["version"])
                             .values(rows=rows))
    await db_session.commit()
    work_req, (plaster,) = await _request(
        db_session, env, "work", [{"name": "штукатурка  стен", "unit": "м2", "sheet": "СОТ"}])
    offer = await add_offer(db_session, work_req, "Бригада")
    await add_price(db_session, offer, plaster, 450)

    preview = (await _preview(async_client, env)).json()
    assert [r["row_id"] for r in preview["rows"]] == ["w2"]
    assert preview["ambiguous"] == []


@pytest.mark.asyncio
async def test_not_found_and_unit_mismatch(async_client, db_session, env):
    work_req, (ghost, plaster_m3) = await _request(db_session, env, "work", [
        {"name": "Покраска потолка", "unit": "м2"},
        {"name": "Штукатурка стен", "unit": "м3"},
    ])
    offer = await add_offer(db_session, work_req, "Бригада")
    await add_price(db_session, offer, ghost, 200)
    await add_price(db_session, offer, plaster_m3, 900)

    preview = (await _preview(async_client, env)).json()
    assert preview["rows"] == []
    assert {n["item_id"] for n in preview["not_found"]} == {ghost, plaster_m3}
    resp = await _apply(async_client, env, preview)
    assert resp.status_code == 422
    assert len(await _versions(db_session, env)) == 1


@pytest.mark.asyncio
async def test_row_id_match_only_for_same_optimization_and_price_in_row_unit(
    async_client, db_session, env,
):
    own, (own_item,) = await _request(
        db_session, env, "material", [{"name": "Арматура А500", "unit": "кг", "row_ids": ["m1"]}],
        source_kind="optimization", source_task_id=env["task"])
    offer = await add_offer(db_session, own, "ООО Сталь")
    await add_price(db_session, offer, own_item, 85, "кг")

    preview = (await _preview(async_client, env)).json()
    (row,) = preview["rows"]
    # Позиция в кг, строка в т: цена — в единице строки
    assert row["row_id"] == "m1" and row["new_price"] == 85000 and row["match"] == "row_id"

    # Тот же запрос, но поставленный с другой задачи: row_id не доверяем
    await db_session.execute(update(KpRequest).where(KpRequest.id == own)
                             .values(source_task_id="7c1e2b1a-3f4d-4e5a-9b6c-1d2e3f4a5b6c"))
    await db_session.commit()
    preview = (await _preview(async_client, env)).json()
    assert preview["rows"] == [] and len(preview["not_found"]) == 1


@pytest.mark.asyncio
async def test_source_no_and_name_match_ignores_unit(async_client, db_session, env):
    rows = _base_rows()
    rows[2]["source_no"] = "12"
    rows[3]["source_no"] = "13"
    rows[3]["unit"] = "100 м2"
    await db_session.execute(update(EstimateVersion).where(EstimateVersion.id == env["version"])
                             .values(rows=rows))
    await db_session.commit()
    work_req, (plaster,) = await _request(
        db_session, env, "work", [{"name": "Штукатурка стен", "unit": "м2", "source_no": "13"}])
    offer = await add_offer(db_session, work_req, "Бригада")
    await add_price(db_session, offer, plaster, 4.5, "м2")

    preview = (await _preview(async_client, env)).json()
    (row,) = preview["rows"]
    assert row["row_id"] == "w2" and row["match"] == "source_no"
    assert row["new_price"] == 450  # за 100 м2


@pytest.mark.asyncio
async def test_several_requests_on_row_take_minimum(async_client, db_session, env):
    first, (a,) = await _request(db_session, env, "work", [{"name": "Штукатурка стен", "unit": "м2"}])
    second, (b,) = await _request(db_session, env, "work", [{"name": "Штукатурка стен", "unit": "м2"}])
    o1 = await add_offer(db_session, first, "Бригада 1")
    o1b = await add_offer(db_session, first, "Бригада 1б")
    o2 = await add_offer(db_session, second, "Бригада 2")
    await add_price(db_session, o1, a, 480)
    await add_price(db_session, o1b, a, 470)
    await add_price(db_session, o2, b, 460)
    # Выбор человека в первом запросе перекрывает его минимум
    await db_session.execute(update(KpRequestItem).where(KpRequestItem.id == a)
                             .values(selected_offer_id=o1))
    # Черновик дешевле всех — не участвует
    o3 = await add_offer(db_session, second, "Черновик")
    await add_price(db_session, o3, b, 100, confirmed=False)

    preview = (await _preview(async_client, env)).json()
    rows = _by_id(preview["rows"])
    assert rows["w1"]["new_price"] == 460 and rows["w1"]["offer_id"] == o2
    resp = await _apply(async_client, env, preview)
    assert resp.status_code == 200, resp.text
    _, clone = await _versions(db_session, env)
    assert _by_id(clone.rows)["w1"]["kp_ref"]["request_id"] == second
    db_session.expire_all()
    # Проигравший запрос ничего не дал строкам — применённым не считается
    assert (await db_session.get(KpRequest, first)).applied_at is None
    assert (await db_session.get(KpRequest, second)).applied_at is not None


@pytest.mark.asyncio
async def test_includes_materials_keeps_material_price(async_client, db_session, env):
    work_req, (plaster,) = await _request(
        db_session, env, "work", [{"name": "Штукатурка стен", "unit": "м2"}])
    offer = await add_offer(db_session, work_req, "Бригада", includes_materials=True,
                         offer_date=date(2026, 9, 1))
    await add_price(db_session, offer, plaster, 800)

    preview = (await _preview(async_client, env)).json()
    assert preview["includes_materials_count"] == 2
    assert (await _apply(async_client, env, preview)).status_code == 200
    _, clone = await _versions(db_session, env)
    w1 = _by_id(clone.rows)["w1"]
    assert w1["price_work"] == 800 and w1["price_material"] == 300
    assert w1["kp_ref"]["includes_materials"] is True
    assert w1["optimization_note"] == "Из КП: Бригада от 01.09.2026, цена включает материалы"


@pytest.mark.asyncio
async def test_unrelated_requests_ignored(async_client, db_session, env):
    for status in ("in_progress", "cancelled"):
        req, (item,) = await _request(db_session, env, "work",
                                      [{"name": "Штукатурка стен", "unit": "м2"}], status=status)
        offer = await add_offer(db_session, req, "Бригада")
        await add_price(db_session, offer, item, 100)
    preview = (await _preview(async_client, env)).json()
    assert preview["rows"] == [] and preview["not_found"] == []


# ---------------------------------------------------------------------------
# Конфликты и откат
# ---------------------------------------------------------------------------

async def _simple_work(db_session, env, price=450):
    work_req, (plaster,) = await _request(
        db_session, env, "work", [{"name": "Штукатурка стен", "unit": "м2"}])
    offer = await add_offer(db_session, work_req, "Бригада")
    await add_price(db_session, offer, plaster, price)
    return work_req, plaster, offer


@pytest.mark.asyncio
async def test_stale_client_rev_conflict_creates_nothing(async_client, db_session, env):
    work_req, _, _ = await _simple_work(db_session, env)
    preview = (await _preview(async_client, env)).json()
    # Коллега применил правку: rev ушёл вперёд
    await db_session.execute(update(EstimateVersion).where(EstimateVersion.id == env["version"])
                             .values(rev=4))
    await db_session.commit()

    resp = await _apply(async_client, env, preview)
    assert resp.status_code == 409
    versions = await _versions(db_session, env)
    assert len(versions) == 1 and versions[0].rev == 4
    assert (await db_session.get(KpRequest, work_req)).applied_at is None


@pytest.mark.asyncio
async def test_changed_prices_after_preview_conflict(async_client, db_session, env):
    _, plaster, offer = await _simple_work(db_session, env)
    preview = (await _preview(async_client, env)).json()
    await db_session.execute(update(KpOfferPrice).where(KpOfferPrice.item_id == plaster)
                             .values(price=400))
    await db_session.commit()

    resp = await _apply(async_client, env, preview)
    assert resp.status_code == 409
    versions = await _versions(db_session, env)
    assert len(versions) == 1
    assert versions[0].rev == 3  # заявка на ревизию откатилась вместе со всем


@pytest.mark.asyncio
async def test_not_latest_version_conflict(async_client, db_session, env):
    await _simple_work(db_session, env)
    newer = EstimateVersion(task_id=env["task"], version_number=1, version_label="custom",
                            version_display_name="Моя", rows=_base_rows(), file_slot="result", rev=0)
    db_session.add(newer)
    await db_session.commit()

    resp = await _preview(async_client, env)
    assert resp.status_code == 409
    # Откатили новую — исходная снова последняя
    await db_session.execute(update(EstimateVersion).where(EstimateVersion.id == newer.id)
                             .values(is_rolled_back=True))
    await db_session.commit()
    assert (await _preview(async_client, env)).status_code == 200


@pytest.mark.asyncio
async def test_rollback_returns_prices(async_client, db_session, env):
    await _simple_work(db_session, env)
    preview = (await _preview(async_client, env)).json()
    assert (await _apply(async_client, env, preview)).status_code == 200
    _, clone = await _versions(db_session, env)
    assert _by_id(clone.rows)["w1"]["price_work"] == 450

    resp = await async_client.post(
        f"/tasks/{env['task']}/estimate/versions/{env['version']}/rollback",
        headers=auth(env["pm1"], "project_manager"))
    assert resp.status_code == 200, resp.text
    source, clone = await _versions(db_session, env)
    assert clone.is_rolled_back is True
    assert _by_id(source.rows)["w1"]["price_work"] == 500
    # После отката снова можно применять к исходной
    assert (await _preview(async_client, env)).status_code == 200


@pytest.mark.asyncio
async def test_production_role_forbidden(async_client, db_session, env):
    await _simple_work(db_session, env)
    preview = (await _preview(async_client, env)).json()
    resp = await async_client.post(
        "/kp-requests/apply/preview", headers=auth(env["contractor1"], "contractor_manager"),
        json={"card_id": env["card"], "version_id": env["version"]})
    assert resp.status_code == 403
    resp = await _apply(async_client, env, preview, who=(env["contractor1"], "contractor_manager"))
    assert resp.status_code == 403
    assert len(await _versions(db_session, env)) == 1


@pytest.mark.asyncio
async def test_newer_version_after_preview_conflict(async_client, db_session, env):
    work_req, _, _ = await _simple_work(db_session, env)
    preview = (await _preview(async_client, env)).json()
    db_session.add(EstimateVersion(task_id=env["task"], version_number=1, version_label="custom",
                                   version_display_name="Моя", rows=_base_rows(),
                                   file_slot="result", rev=0))
    await db_session.commit()

    resp = await _apply(async_client, env, preview)
    assert resp.status_code == 409
    versions = await _versions(db_session, env)
    assert [v.version_number for v in versions] == [0, 1]
    assert versions[0].rev == 3
    assert (await db_session.get(KpRequest, work_req)).applied_at is None


@pytest.mark.asyncio
async def test_row_id_match_requires_same_name_analog_not_priced(async_client, db_session, env):
    """Оптимизация заменила позицию аналогом в той же строке: id прежний, имя другое.

    Цена из КП назначена за позицию запроса — на аналог она не ложится.
    """
    rows = _base_rows()
    rows[1]["name"] = "Арматура А400 (аналог)"
    await db_session.execute(update(EstimateVersion).where(EstimateVersion.id == env["version"])
                             .values(rows=rows))
    await db_session.commit()
    own, (own_item,) = await _request(
        db_session, env, "material", [{"name": "Арматура А500", "unit": "т", "row_ids": ["m1"]}],
        source_kind="optimization", source_task_id=env["task"])
    offer = await add_offer(db_session, own, "ООО Сталь")
    await add_price(db_session, offer, own_item, 85000, "т")

    preview = (await _preview(async_client, env)).json()
    assert preview["rows"] == []
    assert [n["item_id"] for n in preview["not_found"]] == [own_item]

    # Регистр и пробелы наименования — не повод отказать (та же нормализация).
    rows[1]["name"] = "  арматура  а500 "
    await db_session.execute(update(EstimateVersion).where(EstimateVersion.id == env["version"])
                             .values(rows=rows))
    await db_session.commit()
    preview = (await _preview(async_client, env)).json()
    (row,) = preview["rows"]
    assert row["row_id"] == "m1" and row["match"] == "row_id" and row["new_price"] == 85000


@pytest.mark.asyncio
async def test_kp_note_appended_to_optimization_note_and_replaced_on_repeat(
    async_client, db_session, env,
):
    rows = _base_rows()
    rows[2]["optimization_note"] = "Заменено аналогом"
    await db_session.execute(update(EstimateVersion).where(EstimateVersion.id == env["version"])
                             .values(rows=rows))
    await db_session.commit()
    work_req, (plaster,) = await _request(
        db_session, env, "work", [{"name": "Штукатурка стен", "unit": "м2"}])
    offer = await add_offer(db_session, work_req, "Бригада")
    await add_price(db_session, offer, plaster, 450)

    preview = (await _preview(async_client, env)).json()
    assert (await _apply(async_client, env, preview)).status_code == 200
    _, clone = await _versions(db_session, env)
    new = _by_id(clone.rows)
    assert new["w1"]["optimization_note"] == "Заменено аналогом; Из КП: Бригада"
    assert new["w2"]["optimization_note"] == "Из КП: Бригада"

    # Повтор поверх новой версии: пометка КП заменяется, а не копится.
    await db_session.execute(update(KpOffer).where(KpOffer.id == offer)
                             .values(supplier_name="Бригада-2"))
    await db_session.commit()
    preview = (await _preview(async_client, env, version_id=str(clone.id))).json()
    assert (await _apply(async_client, env, preview)).status_code == 200, preview
    *_, again = await _versions(db_session, env)
    new = _by_id(again.rows)
    assert new["w1"]["optimization_note"] == "Заменено аналогом; Из КП: Бригада-2"
    assert new["w2"]["optimization_note"] == "Из КП: Бригада-2"
