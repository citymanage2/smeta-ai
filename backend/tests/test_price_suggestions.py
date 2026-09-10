"""Очередь предложений цены: система предлагает, решает человек.

План: plans/2026-09-10-sverka-i-obuchenie-na-pravkah.md, Фаза 6.

Главное, что здесь закреплено: без нажатия человека в прайс не уходит ничего
(правило 9 CLAUDE.md), предлагается медиана, а не последняя правка (одна
опечатка иначе стала бы ценой, перебивающей все прайсы подрядчиков), и
несводимая единица цену не пропускает (правило 8).
"""
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.correction_signal import CorrectionSignal
from app.models.price import PriceMaterial, PriceWork
from app.models.price_decision import PriceDecision
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.utils.auth import create_access_token, hash_password
from app.utils.price_min import ESTIMATE_CONTRACTOR

_MODELS = (CorrectionSignal, PriceDecision, PriceWork, PriceMaterial,
           Task, Project, User)


def _auth(user_id: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id, 'project_manager', 'pm1')}"}


@pytest_asyncio.fixture
async def env(db_session, fake_s3):
    for model in _MODELS:
        await db_session.execute(model.__table__.delete())
    await db_session.commit()

    pm1 = User(username="pm1", role="project_manager", full_name="Иванов Иван",
               password_hash=hash_password("p1"))
    db_session.add(pm1)
    await db_session.flush()

    project = Project(name="Объект АР", owner_id=pm1.id)
    db_session.add(project)
    await db_session.flush()

    tasks = []
    for _ in range(3):
        task = Task(
            owner_id=pm1.id, user_role="project_manager",
            task_type="ESTIMATE_FROM_LIST", status="completed",
            input_files=[], input_file_data=[], chat_history=[],
            project_id=str(project.id),
        )
        db_session.add(task)
        tasks.append(task)
    await db_session.commit()

    yield {"pm1": pm1.id, "tasks": [str(t.id) for t in tasks]}

    for model in _MODELS:
        await db_session.execute(model.__table__.delete())
    await db_session.commit()


def _signal(task_id: str, *, name="Кладка стен", unit="м3", field="price_work",
            previous=3000.0, new=2500.0, kind="estimate", first=True,
            row_key="e1") -> CorrectionSignal:
    return CorrectionSignal(
        task_id=task_id, document_kind=kind, row_key=row_key, row_name=name,
        row_type="work" if field == "price_work" else "material", unit=unit,
        field=field, previous_value=str(previous), new_value=str(new),
        previous_num=previous, new_num=new, is_first_touch=first,
        price_source="Прайс подрядчика №2", user_id=1, user_name="Иванов Иван",
    )


async def _list(async_client, env, **params) -> list:
    r = await async_client.get(
        "/price-suggestions", params=params, headers=_auth(env["pm1"])
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
async def test_single_edit_is_not_a_suggestion(async_client, db_session, env):
    """Одна правка — случай, а не закономерность."""
    db_session.add(_signal(env["tasks"][0]))
    await db_session.commit()

    assert await _list(async_client, env) == []


@pytest.mark.asyncio
async def test_two_edits_make_a_suggestion(async_client, db_session, env):
    """Две правки одной позиции — уже предложение, с числами и счётчиками."""
    db_session.add_all([
        _signal(env["tasks"][0]),
        _signal(env["tasks"][1]),
    ])
    await db_session.commit()

    items = await _list(async_client, env)
    assert len(items) == 1

    item = items[0]
    assert item["display_name"] == "Кладка стен"
    assert item["row_type"] == "work"
    assert item["unit"] == "м3"
    assert item["suggested_price"] == 2500.0
    assert item["system_price"] == 3000.0
    assert item["touches"] == 2
    assert item["tasks"] == 2
    assert item["sources"] == ["Прайс подрядчика №2"]


@pytest.mark.asyncio
async def test_median_is_offered_not_the_last_edit(async_client, db_session, env):
    """2500, 2800, 25000 → предлагается 2800, а не последняя опечатка."""
    db_session.add_all([
        _signal(env["tasks"][0], new=2500.0),
        _signal(env["tasks"][1], new=2800.0),
        _signal(env["tasks"][2], new=25000.0),
    ])
    await db_session.commit()

    item = (await _list(async_client, env))[0]
    assert item["suggested_price"] == 2800.0
    assert item["min_price"] == 2500.0
    assert item["max_price"] == 25000.0
    # Разброс в десять раз — система выбирать не вправе, человек предупреждён.
    assert item["prices_disagree"] is True


@pytest.mark.asyncio
async def test_list_and_completeness_signals_are_not_offered(
    async_client, db_session, env
):
    """Перечень и полнота в очередь не идут: там нет надёжных типа и единицы."""
    db_session.add_all([
        _signal(env["tasks"][0], kind="list", field="Цена работ", unit=""),
        _signal(env["tasks"][1], kind="list", field="Цена работ", unit=""),
    ])
    await db_session.commit()

    assert await _list(async_client, env) == []


@pytest.mark.asyncio
async def test_repeated_edits_of_same_cell_do_not_count(
    async_client, db_session, env
):
    """Правка правки — разговор человека с самим собой, не сигнал о цене."""
    db_session.add_all([
        _signal(env["tasks"][0]),
        _signal(env["tasks"][0], first=False, previous=2500.0, new=2400.0),
    ])
    await db_session.commit()

    assert await _list(async_client, env) == []


@pytest.mark.asyncio
async def test_different_units_are_different_suggestions(
    async_client, db_session, env
):
    """3000 за м2 и 3000 за м3 — разные цены, а не разброс одной."""
    db_session.add_all([
        _signal(env["tasks"][0], unit="м2"),
        _signal(env["tasks"][1], unit="м2"),
        _signal(env["tasks"][0], unit="м3", row_key="e2"),
        _signal(env["tasks"][1], unit="м3", row_key="e2"),
    ])
    await db_session.commit()

    items = await _list(async_client, env)
    assert sorted(i["unit"] for i in items) == ["м2", "м3"]


@pytest.mark.asyncio
async def test_nothing_is_written_without_a_press(async_client, db_session, env):
    """Просто посмотреть очередь — прайс не меняется. Правило 9."""
    db_session.add_all([_signal(env["tasks"][0]), _signal(env["tasks"][1])])
    await db_session.commit()

    await _list(async_client, env)

    db_session.expire_all()
    assert (await db_session.execute(select(PriceWork))).scalars().all() == []


@pytest.mark.asyncio
async def test_accept_writes_price_under_estimate_contractor(
    async_client, db_session, env
):
    """Подтверждение кладёт цену в прайс — тем же путём, что кнопка «в прайс»."""
    db_session.add_all([_signal(env["tasks"][0]), _signal(env["tasks"][1])])
    await db_session.commit()

    r = await async_client.post(
        "/price-suggestions/accept",
        json={"name": "Кладка стен", "row_type": "work", "unit": "м3",
              "price": 2500.0},
        headers=_auth(env["pm1"]),
    )
    assert r.status_code == 200, r.text

    db_session.expire_all()
    work = (await db_session.execute(select(PriceWork))).scalar_one()
    assert work.prices == {ESTIMATE_CONTRACTOR: 2500.0}
    assert work.min_price == 2500.0

    # Подтверждённое предложение больше не показывается.
    assert await _list(async_client, env) == []


@pytest.mark.asyncio
async def test_accept_with_incompatible_unit_is_refused_loudly(
    async_client, db_session, env
):
    """Цена за мешок в позицию с килограммами не уходит — и об этом говорят."""
    db_session.add(PriceWork(
        name="Смесь", unit="кг", prices={"Подрядчик А": 40}, min_price=40,
    ))
    db_session.add_all([
        _signal(env["tasks"][0], name="Смесь", unit="мешок", new=900.0),
        _signal(env["tasks"][1], name="Смесь", unit="мешок", new=900.0),
    ])
    await db_session.commit()

    r = await async_client.post(
        "/price-suggestions/accept",
        json={"name": "Смесь", "row_type": "work", "unit": "мешок", "price": 900.0},
        headers=_auth(env["pm1"]),
    )

    assert r.status_code == 409
    assert "единица" in r.json()["detail"].lower()

    db_session.expire_all()
    work = (await db_session.execute(select(PriceWork))).scalar_one()
    assert work.prices == {"Подрядчик А": 40}


@pytest.mark.asyncio
async def test_reject_hides_suggestion_and_writes_nothing(
    async_client, db_session, env
):
    """«Не запоминать» убирает предложение и не трогает прайс."""
    db_session.add_all([_signal(env["tasks"][0]), _signal(env["tasks"][1])])
    await db_session.commit()

    r = await async_client.post(
        "/price-suggestions/reject",
        json={"name": "Кладка стен", "row_type": "work", "unit": "м3",
              "price": 2500.0},
        headers=_auth(env["pm1"]),
    )
    assert r.status_code == 200

    assert await _list(async_client, env) == []
    db_session.expire_all()
    assert (await db_session.execute(select(PriceWork))).scalars().all() == []


@pytest.mark.asyncio
async def test_rejected_price_comes_back_when_person_starts_setting_another(
    async_client, db_session, env
):
    """Отклонили 2500 — 2500 не всплывает; 4000 это новое знание, спросим снова."""
    db_session.add_all([_signal(env["tasks"][0]), _signal(env["tasks"][1])])
    await db_session.commit()

    await async_client.post(
        "/price-suggestions/reject",
        json={"name": "Кладка стен", "row_type": "work", "unit": "м3",
              "price": 2500.0},
        headers=_auth(env["pm1"]),
    )
    assert await _list(async_client, env) == []

    # Человек дважды поставил заметно другую цену.
    db_session.add_all([
        _signal(env["tasks"][2], new=4000.0, row_key="e9"),
        _signal(env["tasks"][2], new=4000.0, row_key="e10"),
    ])
    await db_session.commit()

    items = await _list(async_client, env)
    assert len(items) == 1
    assert items[0]["suggested_price"] == 3250.0


@pytest.mark.asyncio
async def test_undo_returns_suggestion_to_the_queue(async_client, db_session, env):
    """Ошибочное «не запоминать» можно отменить: прайс общий, цена дорога."""
    db_session.add_all([_signal(env["tasks"][0]), _signal(env["tasks"][1])])
    await db_session.commit()

    payload = {"name": "Кладка стен", "row_type": "work", "unit": "м3",
               "price": 2500.0}
    await async_client.post("/price-suggestions/reject", json=payload,
                            headers=_auth(env["pm1"]))
    assert await _list(async_client, env) == []

    r = await async_client.post("/price-suggestions/undo", json=payload,
                                headers=_auth(env["pm1"]))
    assert r.json()["restored"] is True
    assert len(await _list(async_client, env)) == 1


@pytest.mark.asyncio
async def test_material_price_goes_to_materials(async_client, db_session, env):
    """Материал уходит в таблицу материалов, а не работ."""
    db_session.add_all([
        _signal(env["tasks"][0], name="Кирпич", unit="шт",
                field="price_material", previous=30.0, new=25.0),
        _signal(env["tasks"][1], name="Кирпич", unit="шт",
                field="price_material", previous=30.0, new=25.0),
    ])
    await db_session.commit()

    item = (await _list(async_client, env))[0]
    assert item["row_type"] == "material"

    r = await async_client.post(
        "/price-suggestions/accept",
        json={"name": "Кирпич", "row_type": "material", "unit": "шт",
              "price": 25.0},
        headers=_auth(env["pm1"]),
    )
    assert r.status_code == 200

    db_session.expire_all()
    material = (await db_session.execute(select(PriceMaterial))).scalar_one()
    assert material.price == 25.0
    assert (await db_session.execute(select(PriceWork))).scalars().all() == []


@pytest.mark.asyncio
async def test_person_can_correct_the_price_before_accepting(
    async_client, db_session, env
):
    """Человек — источник истины: он вправе записать своё число, а не наше."""
    db_session.add_all([_signal(env["tasks"][0]), _signal(env["tasks"][1])])
    await db_session.commit()

    await async_client.post(
        "/price-suggestions/accept",
        json={"name": "Кладка стен", "row_type": "work", "unit": "м3",
              "price": 2650.0},
        headers=_auth(env["pm1"]),
    )

    db_session.expire_all()
    work = (await db_session.execute(select(PriceWork))).scalar_one()
    assert work.prices == {ESTIMATE_CONTRACTOR: 2650.0}
