"""Эталонный прайс: два шага HTTP — посмотреть и применить.

Фаза 3 плана `plans/2026-09-02-etalonnyy-prays-iz-smety.md`.

Разделение на шаги — не удобство интерфейса, а требование безопасности: прайс
общий, стёртая цена подрядчика не возвращается. Поэтому предпросмотр обязан
быть чтением, а применение — делать ровно то, что человек увидел и отметил.

Проверяется здесь и то, чего в ответе быть **не должно**: удаление позиции, в
которую только что записана эталонная цена, и запись позиции с несводимой
единицей.
"""
import io
from datetime import datetime, timedelta, timezone

import openpyxl
import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.models.price import PriceMaterial, PriceWork
from app.models.price_cache import PriceCacheWork
from app.services import price_service, reference_price
from app.utils.price_min import ESTIMATE_CONTRACTOR

pytestmark = pytest.mark.asyncio

_HEADERS = [
    "№", "Тип", "Наименование", "Ед. изм.", "Кол-во",
    "Цена работы (за ед.)", "Цена материала (за ед.)",
]


def _smeta_bytes(rows: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(_HEADERS)
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _upload(rows: list[list]) -> dict:
    return {"file": ("смета.xlsx", _smeta_bytes(rows),
                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}


@pytest_asyncio.fixture(autouse=True)
async def clean_price(db_session, monkeypatch):
    """Пустой прайс и никакого векторного поиска, если тест не попросил иного."""
    async def _wipe():
        await db_session.execute(delete(PriceWork))
        await db_session.execute(delete(PriceMaterial))
        await db_session.execute(delete(PriceCacheWork))
        await db_session.commit()

    async def _noop_cache(db):
        return None

    monkeypatch.setattr(price_service, "load_cache", _noop_cache)
    monkeypatch.setattr(price_service, "duplicate_vectors_ready", lambda kind: False)

    await _wipe()
    yield
    await _wipe()


# ---------------------------------------------------------------------------
# Права и предпросмотр
# ---------------------------------------------------------------------------

async def test_preview_requires_manager(async_client, user_token):
    """Прайс — управляющее действие: менеджер проектов сюда не ходит."""
    r = await async_client.post(
        "/prices/reference/preview",
        files=_upload([[1, "Работа", "Кладка стен", "м3", 1, 1000, None]]),
        headers={"Authorization": user_token},
    )
    assert r.status_code == 403


async def test_apply_requires_manager(async_client, user_token):
    r = await async_client.post(
        "/prices/reference/apply",
        json={"items": [], "remove": []},
        headers={"Authorization": user_token},
    )
    assert r.status_code == 403


async def test_preview_shows_what_will_be_erased(async_client, admin_token, db_session):
    """Человек видит цену подрядчика, которая исчезнет, и чья она."""
    db_session.add(PriceWork(
        name="Кладка стен", unit="м3",
        prices={"ООО Рога": 1200.0}, min_price=1200.0,
    ))
    await db_session.commit()

    r = await async_client.post(
        "/prices/reference/preview",
        files=_upload([[1, "Работа", "Кладка стен", "м3", 1, 1000, None]]),
        headers={"Authorization": admin_token},
    )

    assert r.status_code == 200
    data = r.json()
    entry = data["plan"][0]
    assert entry["action"] == "reprice"
    assert entry["removed"] == [{"contractor": "ООО Рога", "price": 1200.0}]
    assert data["summary"]["reprice"] == 1
    assert data["items"][0]["price"] == 1000.0


async def test_preview_changes_nothing(async_client, admin_token, db_session):
    """Предпросмотр — чтение. Дважды подряд даёт то же самое."""
    db_session.add(PriceWork(
        name="Кладка стен", unit="м3", prices={"ООО Рога": 1200.0}, min_price=1200.0,
    ))
    await db_session.commit()

    for _ in range(2):
        r = await async_client.post(
            "/prices/reference/preview",
            files=_upload([[1, "Работа", "Кладка стен", "м3", 1, 1000, None]]),
            headers={"Authorization": admin_token},
        )
        assert r.json()["plan"][0]["removed"] == [{"contractor": "ООО Рога", "price": 1200.0}]

    db_session.expire_all()
    work = (await db_session.execute(select(PriceWork))).scalar_one()
    assert work.prices == {"ООО Рога": 1200.0}
    assert work.min_price == 1200.0


async def test_preview_says_when_vector_search_is_off(async_client, admin_token):
    """Пустой список дублей без векторов — это «поиск отключён», а не «дублей нет»."""
    r = await async_client.post(
        "/prices/reference/preview",
        files=_upload([[1, "Работа", "Кладка стен", "м3", 1, 1000, None]]),
        headers={"Authorization": admin_token},
    )
    assert r.json()["duplicates"]["vectors_ready"] is False


async def test_unreadable_file_is_refused(async_client, admin_token):
    r = await async_client.post(
        "/prices/reference/preview",
        files={"file": ("прайс.xlsx", b"not a workbook", "application/octet-stream")},
        headers={"Authorization": admin_token},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Применение
# ---------------------------------------------------------------------------

async def test_apply_leaves_single_price_for_work(async_client, admin_token, db_session):
    """Главное обещание функции: у работы остаётся одна цена — из файла."""
    db_session.add(PriceWork(
        name="Кладка стен", unit="м3",
        prices={"ООО Рога": 1200.0, "ИП Копыта": 1100.0}, min_price=1100.0,
    ))
    await db_session.commit()

    r = await async_client.post(
        "/prices/reference/apply",
        json={
            "items": [{"kind": "work", "name": "Кладка стен", "unit": "м3", "price": 1000.0}],
            "remove": [],
        },
        headers={"Authorization": admin_token},
    )

    assert r.status_code == 200
    db_session.expire_all()
    work = (await db_session.execute(select(PriceWork))).scalar_one()
    assert work.prices == {ESTIMATE_CONTRACTOR: 1000.0}
    assert work.min_price == 1000.0


async def test_apply_overwrites_material_price(async_client, admin_token, db_session):
    db_session.add(PriceMaterial(name="Кирпич", unit="шт", price=30.0))
    await db_session.commit()

    await async_client.post(
        "/prices/reference/apply",
        json={
            "items": [{"kind": "material", "name": "Кирпич", "unit": "шт", "price": 25.0}],
            "remove": [],
        },
        headers={"Authorization": admin_token},
    )

    db_session.expire_all()
    material = (await db_session.execute(select(PriceMaterial))).scalar_one()
    assert material.price == 25.0


async def test_apply_adds_new_position(async_client, admin_token, db_session):
    r = await async_client.post(
        "/prices/reference/apply",
        json={
            "items": [{"kind": "work", "name": "Новая работа", "unit": "м2", "price": 500.0}],
            "remove": [],
        },
        headers={"Authorization": admin_token},
    )

    assert r.json()["added"] == 1
    db_session.expire_all()
    work = (await db_session.execute(select(PriceWork))).scalar_one()
    assert work.prices == {ESTIMATE_CONTRACTOR: 500.0}


async def test_apply_refuses_incompatible_unit(async_client, admin_token, db_session):
    """Цена за мешок не заменяется ценой за кг — даже если фронт прислал позицию."""
    db_session.add(PriceMaterial(name="Смесь сухая", unit="мешок", price=300.0))
    await db_session.commit()

    r = await async_client.post(
        "/prices/reference/apply",
        json={
            "items": [{"kind": "material", "name": "Смесь сухая", "unit": "кг", "price": 12.0}],
            "remove": [],
        },
        headers={"Authorization": admin_token},
    )

    assert r.json()["blocked"] == 1
    db_session.expire_all()
    material = (await db_session.execute(select(PriceMaterial))).scalar_one()
    assert material.price == 300.0
    assert material.unit == "мешок"


async def test_price_date_moves_only_on_reprice(async_client, admin_token, db_session):
    """Дата «Цена от» — дата цены. Та же цена её не двигает (правило №15)."""
    old = datetime.now(timezone.utc) - timedelta(days=40)
    db_session.add(PriceMaterial(name="Кирпич", unit="шт", price=25.0, updated_at=old))
    db_session.add(PriceMaterial(name="Песок", unit="м3", price=900.0, updated_at=old))
    await db_session.commit()

    await async_client.post(
        "/prices/reference/apply",
        json={
            "items": [
                {"kind": "material", "name": "Кирпич", "unit": "шт", "price": 25.0},
                {"kind": "material", "name": "Песок", "unit": "м3", "price": 1000.0},
            ],
            "remove": [],
        },
        headers={"Authorization": admin_token},
    )

    db_session.expire_all()
    rows = {m.name: m for m in (await db_session.execute(select(PriceMaterial))).scalars()}
    assert rows["Кирпич"].updated_at.date() == old.date()
    assert rows["Песок"].updated_at.date() == datetime.now(timezone.utc).date()


async def test_work_date_moves_when_contractor_prices_erased(async_client, admin_token, db_session):
    """Стирание чужих цен — переоценка: расчёт после него берёт другое число."""
    old = datetime.now(timezone.utc) - timedelta(days=40)
    db_session.add(PriceWork(
        name="Кладка стен", unit="м3",
        prices={"ООО Рога": 1000.0, ESTIMATE_CONTRACTOR: 1000.0},
        min_price=1000.0, updated_at=old,
    ))
    await db_session.commit()

    await async_client.post(
        "/prices/reference/apply",
        json={
            "items": [{"kind": "work", "name": "Кладка стен", "unit": "м3", "price": 1000.0}],
            "remove": [],
        },
        headers={"Authorization": admin_token},
    )

    db_session.expire_all()
    work = (await db_session.execute(select(PriceWork))).scalar_one()
    assert work.updated_at.date() == datetime.now(timezone.utc).date()


# ---------------------------------------------------------------------------
# Удаление дублей
# ---------------------------------------------------------------------------

async def test_only_checked_duplicates_are_deleted(async_client, admin_token, db_session):
    """Неотмеченное остаётся. Это и есть весь смысл подтверждения."""
    db_session.add(PriceWork(name="Кладка стен кирпичных", unit="м3",
                             prices={"ООО Рога": 1300.0}, min_price=1300.0))
    db_session.add(PriceWork(name="Кладка перегородок", unit="м3",
                             prices={"ООО Рога": 900.0}, min_price=900.0))
    await db_session.commit()
    rows = {w.name: w.id for w in (await db_session.execute(select(PriceWork))).scalars()}

    r = await async_client.post(
        "/prices/reference/apply",
        json={
            "items": [{"kind": "work", "name": "Кладка стен", "unit": "м3", "price": 1000.0}],
            "remove": [{"source": "price", "kind": "work", "id": rows["Кладка стен кирпичных"]}],
        },
        headers={"Authorization": admin_token},
    )

    assert r.json()["removed"] == 1
    db_session.expire_all()
    left = {w.name for w in (await db_session.execute(select(PriceWork))).scalars()}
    assert left == {"Кладка перегородок", "Кладка стен"}


async def test_cache_record_can_be_deleted(async_client, admin_token, db_session):
    """Кеш веб-поиска — такой же источник цены, как прайс, и чистится так же."""
    db_session.add(PriceCacheWork(name="Кладка стен кирпичных", unit="м3", price=1500.0))
    await db_session.commit()
    cache_id = (await db_session.execute(select(PriceCacheWork))).scalar_one().id

    r = await async_client.post(
        "/prices/reference/apply",
        json={
            "items": [{"kind": "work", "name": "Кладка стен", "unit": "м3", "price": 1000.0}],
            "remove": [{"source": "cache", "kind": "work", "id": str(cache_id)}],
        },
        headers={"Authorization": admin_token},
    )

    assert r.json()["removed"] == 1
    db_session.expire_all()
    assert (await db_session.execute(select(PriceCacheWork))).scalars().all() == []


async def test_position_just_written_is_never_deleted(async_client, admin_token, db_session):
    """Отметить к удалению строку, куда мы только что записали эталон, нельзя:
    иначе операция стёрла бы собственный результат."""
    db_session.add(PriceWork(name="Кладка стен", unit="м3",
                             prices={"ООО Рога": 1200.0}, min_price=1200.0))
    await db_session.commit()
    work_id = (await db_session.execute(select(PriceWork))).scalar_one().id

    r = await async_client.post(
        "/prices/reference/apply",
        json={
            "items": [{"kind": "work", "name": "Кладка стен", "unit": "м3", "price": 1000.0}],
            "remove": [{"source": "price", "kind": "work", "id": work_id}],
        },
        headers={"Authorization": admin_token},
    )

    assert r.json()["removed"] == 0
    db_session.expire_all()
    work = (await db_session.execute(select(PriceWork))).scalar_one()
    assert work.prices == {ESTIMATE_CONTRACTOR: 1000.0}


async def test_apply_reloads_price_cache(async_client, admin_token, monkeypatch):
    """Без перезагрузки кэша расчёт увидел бы новую цену только после рестарта."""
    called = {"n": 0}

    async def _spy(db):
        called["n"] += 1

    monkeypatch.setattr(price_service, "load_cache", _spy)

    await async_client.post(
        "/prices/reference/apply",
        json={
            "items": [{"kind": "work", "name": "Новая работа", "unit": "м2", "price": 500.0}],
            "remove": [],
        },
        headers={"Authorization": admin_token},
    )

    assert called["n"] == 1


# ---------------------------------------------------------------------------
# Обычная загрузка прайса не меняется
# ---------------------------------------------------------------------------

async def test_plain_import_still_merges_contractor_prices(async_client, admin_token, db_session):
    """Эталон — отдельный путь. Обычная загрузка обязана остаться слиянием.

    Иначе однажды кто-то зальёт прайс подрядчика привычной кнопкой и не
    досчитается всех остальных цен.
    """
    db_session.add(PriceWork(name="Кладка стен", unit="м3",
                             prices={"ООО Рога": 1200.0}, min_price=1200.0))
    await db_session.commit()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Наименование", "Ед. изм.", "ИП Копыта"])
    ws.append(["Кладка стен", "м3", 1100])
    buffer = io.BytesIO()
    wb.save(buffer)

    r = await async_client.post(
        "/admin/price-lists/works",
        files={"file": ("price.xlsx", buffer.getvalue(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers={"Authorization": admin_token},
    )

    assert r.status_code == 200
    db_session.expire_all()
    work = (await db_session.execute(select(PriceWork))).scalar_one()
    assert work.prices == {"ООО Рога": 1200.0, "ИП Копыта": 1100.0}


async def test_apply_asks_the_model_once_for_new_positions(
    async_client, admin_token, monkeypatch,
):
    """Эталон из сметы — это сотни новых позиций сразу.

    По вектору за позицию запись превращалась бы в минуты ожидания, поэтому
    модель спрашивается один раз на весь файл.
    """
    calls = {"n": 0}

    def fake_batch(texts, input_type="search_document"):
        calls["n"] += 1
        return [[0.1, 0.2] for _ in texts]

    from app.services import reference_price as service

    monkeypatch.setattr(service, "generate_embeddings_batch", fake_batch)

    r = await async_client.post(
        "/prices/reference/apply",
        json={
            "items": [
                {"kind": "work", "name": "Работа один", "unit": "м2", "price": 100.0},
                {"kind": "work", "name": "Работа два", "unit": "м2", "price": 200.0},
                {"kind": "material", "name": "Материал", "unit": "шт", "price": 30.0},
            ],
            "remove": [],
        },
        headers={"Authorization": admin_token},
    )

    assert r.json()["added"] == 3
    assert calls["n"] == 1
