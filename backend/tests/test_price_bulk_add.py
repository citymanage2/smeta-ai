"""Работа с прайсом из редактора: «Добавить в прайс».

Фаза 10 плана `plans/2026-08-02-edinyy-redaktor-tablic.md`.

Главный риск фазы: прайс общий на всех и участвует в расчёте будущих смет.
Поэтому здесь проверяется не только сама запись, но и то, какую цену получит
расчёт после неё.

Решения пользователя (2026-08-03):
- у цены «Из смет» **приоритет**: если она есть — расчёт берёт её, а не минимум
  по подрядчикам; подрядчики работают, только когда цены из смет нет;
- повторное добавление той же работы **перезаписывает** цену «Из смет»
  (хранится последняя, а не история цен);
- материал с тем же названием **перезаписывается** ценой из сметы.
"""
from typing import Optional

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.document_lock import DocumentLock
from app.models.estimate_version import EstimateVersion
from app.models.history import TaskHistory
from app.models.price import PriceMaterial, PriceWork
from app.models.project import Project
from app.models.result import TaskResult
from app.models.task import Task
from app.models.user import User
from app.models.workflow_card import WorkflowCard
from app.utils.auth import create_access_token, hash_password
from app.utils.price_min import ESTIMATE_CONTRACTOR, compute_min_price
from app.utils.unit_normalizer import canonical_unit, unit_price_factor


def _auth(user_id: int, role: str) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id, role)}"}


def _items() -> list:
    return [
        {
            "type": "Работа", "name": "Кладка стен", "unit": "м3", "quantity": 4,
            "work_price": 1000.0, "material_price": None,
        },
        {
            "type": "Материал", "name": "Кирпич", "unit": "шт", "quantity": 400,
            "work_price": None, "material_price": 25.0,
        },
    ]


@pytest_asyncio.fixture
async def price_env(db_session, fake_s3, monkeypatch):
    """Проект → карточка → задача «Смета из перечня» + пустой прайс."""
    # Эмбеддинги в тестах не считаем: модель тяжёлая, а проверяем мы запись в
    # прайс, а не векторы. Позиция без вектора ищется точным совпадением имени.
    async def _no_embedding(_name: str) -> Optional[list]:
        return None

    monkeypatch.setattr(
        "app.services.price_bulk._generate_embedding_safe", _no_embedding, raising=False,
    )

    for model in (DocumentLock, EstimateVersion, TaskHistory, TaskResult,
                  WorkflowCard, Task, Project, User, PriceWork, PriceMaterial):
        await db_session.execute(model.__table__.delete())
    await db_session.commit()

    pm = User(username="pm1", role="project_manager", full_name="Иванов Иван",
              password_hash=hash_password("p1"))
    other = User(username="pm2", role="project_manager", full_name="Петров Пётр",
                 password_hash=hash_password("p2"))
    db_session.add_all([pm, other])
    await db_session.flush()

    project = Project(name="Объект АР", owner_id=pm.id)
    db_session.add(project)
    await db_session.flush()

    task = Task(
        owner_id=pm.id, user_role="project_manager", task_type="ESTIMATE_FROM_LIST",
        status="completed", input_files=[], input_file_data=[], chat_history=[],
        project_id=str(project.id), progress_data={"items": _items()},
    )
    db_session.add(task)
    await db_session.flush()

    card = WorkflowCard(project_id=str(project.id), name="АР", stage="estimate",
                        estimate_task_id=str(task.id))
    db_session.add(card)
    db_session.add(EstimateVersion(
        task_id=str(task.id), version_number=0, version_label="original",
        version_display_name="V0 — Оригинал", file_slot="estimate",
        task_type="ESTIMATE_FROM_LIST",
        rows=[{"id": "r1", "type": "work", "name": "Кладка стен", "unit": "м3",
               "qty": 4, "price_work": 1000, "price_material": None}],
    ))
    await db_session.commit()

    yield {
        "pm": pm.id, "other": other.id, "project_id": str(project.id),
        "card_id": str(card.id), "task_id": str(task.id),
    }

    for model in (DocumentLock, EstimateVersion, TaskHistory, TaskResult,
                  WorkflowCard, Task, Project, User, PriceWork, PriceMaterial):
        await db_session.execute(model.__table__.delete())
    await db_session.commit()


async def _post(async_client, env, items, kind="estimate", user="pm"):
    return await async_client.post(
        f"/documents/{env['card_id']}/{kind}/price-list",
        json={"items": items},
        headers=_auth(env[user], "project_manager"),
    )


# ---------------------------------------------------------------------------
# Единицы измерения
# ---------------------------------------------------------------------------

class TestUnitCanonical:
    """«м2» и «м²» должны стать одной единицей, иначе одна и та же работа
    заводится в прайс дважды и цены расходятся."""

    @pytest.mark.parametrize("written", ["м2", "м²", "М2", "кв.м", "кв. м", "м.кв"])
    def test_square_meters_collapse_to_one_unit(self, written):
        assert canonical_unit(written) == "м2"

    @pytest.mark.parametrize("written", ["м3", "м³", "куб.м", "куб. м"])
    def test_cubic_meters_collapse_to_one_unit(self, written):
        assert canonical_unit(written) == "м3"

    @pytest.mark.parametrize("written", ["шт", "шт.", "ШТ", " шт "])
    def test_pieces_collapse_to_one_unit(self, written):
        assert canonical_unit(written) == "шт"

    @pytest.mark.parametrize("written", ["пог.м", "п.м", "п/м", "пм", "м.п."])
    def test_linear_meters_collapse_to_one_unit(self, written):
        assert canonical_unit(written) == "пог.м"

    def test_unknown_unit_kept_as_is(self):
        """Незнакомую единицу не выдумываем — оставляем как написал человек."""
        assert canonical_unit("бухта") == "бухта"

    def test_empty_unit_survives(self):
        assert canonical_unit(None) == ""
        assert canonical_unit("") == ""

    def test_prefixed_unit_scales_price(self):
        """«100 м2» по 5000 ₽ — это 50 ₽ за м2, иначе прайс завысит цену в сто раз."""
        unit, factor = unit_price_factor("100 м2")

        assert unit == "м2"
        assert factor == 100

    def test_plain_unit_has_factor_one(self):
        unit, factor = unit_price_factor("м2")

        assert unit == "м2"
        assert factor == 1


# ---------------------------------------------------------------------------
# Правило минимальной цены
# ---------------------------------------------------------------------------

class TestMinPriceRule:
    """Приоритет у цены из смет — решение пользователя 2026-08-03."""

    def test_contractors_only_gives_minimum(self):
        assert compute_min_price({"Подрядчик А": 1500, "Подрядчик Б": 1200}) == 1200

    def test_estimate_price_wins_even_if_higher(self):
        prices = {"Подрядчик А": 1200, ESTIMATE_CONTRACTOR: 2000}

        assert compute_min_price(prices) == 2000

    def test_estimate_price_wins_when_lower(self):
        prices = {"Подрядчик А": 1200, ESTIMATE_CONTRACTOR: 500}

        assert compute_min_price(prices) == 500

    def test_non_positive_estimate_price_ignored(self):
        prices = {"Подрядчик А": 1200, ESTIMATE_CONTRACTOR: 0}

        assert compute_min_price(prices) == 1200

    def test_empty_prices_give_none(self):
        assert compute_min_price({}) is None
        assert compute_min_price(None) is None

    def test_garbage_values_do_not_break(self):
        assert compute_min_price({"Подрядчик": "нет цены"}) is None


# ---------------------------------------------------------------------------
# Пакетная запись в прайс
# ---------------------------------------------------------------------------

class TestBulkAdd:
    @pytest.mark.asyncio
    async def test_new_work_lands_in_estimate_contractor(
        self, async_client, db_session, price_env
    ):
        r = await _post(async_client, price_env, [
            {"kind": "work", "name": "Кладка стен", "unit": "м3", "price": 1000},
        ])

        assert r.status_code == 200, r.text
        assert r.json()["added"] == 1

        work = (await db_session.execute(select(PriceWork))).scalar_one()
        assert work.name == "Кладка стен"
        assert work.prices == {ESTIMATE_CONTRACTOR: 1000}
        assert work.min_price == 1000

    @pytest.mark.asyncio
    async def test_repeated_work_keeps_only_last_price(
        self, async_client, db_session, price_env
    ):
        """Решение пользователя: хранится последняя цена, а не история цен."""
        await _post(async_client, price_env, [
            {"kind": "work", "name": "Кладка стен", "unit": "м3", "price": 1000},
        ])
        r = await _post(async_client, price_env, [
            {"kind": "work", "name": "Кладка стен", "unit": "м3", "price": 1400},
        ])

        assert r.json()["updated"] == 1
        assert r.json()["added"] == 0

        works = (await db_session.execute(select(PriceWork))).scalars().all()
        assert len(works) == 1
        assert works[0].prices == {ESTIMATE_CONTRACTOR: 1400}
        assert works[0].min_price == 1400

    @pytest.mark.asyncio
    async def test_estimate_price_beats_contractor_in_calculation(
        self, async_client, db_session, price_env
    ):
        """Главная проверка риска: какую цену получит расчёт следующей сметы."""
        db_session.add(PriceWork(
            name="Кладка стен", unit="м3",
            prices={"Подрядчик А": 800}, min_price=800,
        ))
        await db_session.commit()

        await _post(async_client, price_env, [
            {"kind": "work", "name": "Кладка стен", "unit": "м3", "price": 2000},
        ])

        work = (await db_session.execute(select(PriceWork))).scalar_one()
        assert work.prices == {"Подрядчик А": 800, ESTIMATE_CONTRACTOR: 2000}
        # Расчёт сметы читает min_price — и обязан взять цену из сметы.
        assert work.min_price == 2000

    @pytest.mark.asyncio
    async def test_existing_unit_not_overwritten(
        self, async_client, db_session, price_env
    ):
        """Единица существующей позиции задаёт, за что цена подрядчика.

        Если её переписать единицей из чужой сметы, цена подрядчика за «м2»
        молча станет ценой за «м3» — и все расчёты по ней поедут.
        """
        db_session.add(PriceWork(
            name="Штукатурка", unit="м2", prices={"Подрядчик А": 800}, min_price=800,
        ))
        await db_session.commit()

        await _post(async_client, price_env, [
            {"kind": "work", "name": "Штукатурка", "unit": "м3", "price": 900},
        ])

        work = (await db_session.execute(select(PriceWork))).scalar_one()
        assert work.unit == "м2"
        assert work.prices["Подрядчик А"] == 800

    @pytest.mark.asyncio
    async def test_new_material_lands_with_price(
        self, async_client, db_session, price_env
    ):
        r = await _post(async_client, price_env, [
            {"kind": "material", "name": "Кирпич", "unit": "шт", "price": 25},
        ])

        assert r.json()["added"] == 1
        material = (await db_session.execute(select(PriceMaterial))).scalar_one()
        assert material.price == 25
        assert material.unit == "шт"

    @pytest.mark.asyncio
    async def test_existing_material_is_overwritten_without_duplicate(
        self, async_client, db_session, price_env
    ):
        db_session.add(PriceMaterial(name="Кирпич", unit="шт", price=18.0))
        await db_session.commit()

        r = await _post(async_client, price_env, [
            {"kind": "material", "name": "кирпич", "unit": "шт", "price": 25},
        ])

        assert r.json()["updated"] == 1
        materials = (await db_session.execute(select(PriceMaterial))).scalars().all()
        assert len(materials) == 1
        assert materials[0].price == 25

    @pytest.mark.asyncio
    async def test_units_normalized_on_write(
        self, async_client, db_session, price_env
    ):
        await _post(async_client, price_env, [
            {"kind": "work", "name": "Штукатурка", "unit": "м²", "price": 500},
            {"kind": "work", "name": "Штукатурка", "unit": "кв.м", "price": 600},
        ])

        works = (await db_session.execute(select(PriceWork))).scalars().all()
        assert len(works) == 1, "«м²» и «кв.м» — одна и та же единица"
        assert works[0].unit == "м2"
        assert works[0].prices == {ESTIMATE_CONTRACTOR: 600}

    @pytest.mark.asyncio
    async def test_prefixed_unit_price_recalculated(
        self, async_client, db_session, price_env
    ):
        """Цена за «100 м2» приводится к цене за «м2»."""
        await _post(async_client, price_env, [
            {"kind": "work", "name": "Окраска", "unit": "100 м2", "price": 5000},
        ])

        work = (await db_session.execute(select(PriceWork))).scalar_one()
        assert work.unit == "м2"
        assert work.prices == {ESTIMATE_CONTRACTOR: 50}

    @pytest.mark.asyncio
    async def test_summary_counts_skipped_positions(self, async_client, price_env):
        r = await _post(async_client, price_env, [
            {"kind": "work", "name": "Кладка", "unit": "м3", "price": 1000},
            {"kind": "work", "name": "  ", "unit": "м3", "price": 900},
            {"kind": "work", "name": "Без цены", "unit": "м3", "price": None},
            {"kind": "material", "name": "Отрицательная цена", "unit": "шт", "price": -5},
            {"kind": "section", "name": "Раздел 1", "unit": None, "price": None},
        ])

        body = r.json()
        assert body["added"] == 1
        assert body["updated"] == 0
        assert body["skipped"] == 4

    @pytest.mark.asyncio
    async def test_duplicate_names_inside_one_batch_collapse(
        self, async_client, db_session, price_env
    ):
        """Одна работа встречается в смете дважды — в прайсе должна быть одна."""
        r = await _post(async_client, price_env, [
            {"kind": "work", "name": "Кладка стен", "unit": "м3", "price": 1000},
            {"kind": "work", "name": "Кладка стен", "unit": "м3", "price": 1200},
        ])

        assert r.status_code == 200
        works = (await db_session.execute(select(PriceWork))).scalars().all()
        assert len(works) == 1
        assert works[0].prices == {ESTIMATE_CONTRACTOR: 1200}

    @pytest.mark.asyncio
    async def test_batch_of_fifty_goes_in_one_request(
        self, async_client, db_session, price_env
    ):
        items = [
            {"kind": "work", "name": f"Работа {i}", "unit": "м2", "price": 100 + i}
            for i in range(50)
        ]

        r = await _post(async_client, price_env, items)

        assert r.status_code == 200
        assert r.json()["added"] == 50
        works = (await db_session.execute(select(PriceWork))).scalars().all()
        assert len(works) == 50

    @pytest.mark.asyncio
    async def test_empty_batch_rejected(self, async_client, price_env):
        r = await _post(async_client, price_env, [])

        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_action_written_to_document_history(
        self, async_client, db_session, price_env
    ):
        await _post(async_client, price_env, [
            {"kind": "work", "name": "Кладка стен", "unit": "м3", "price": 1000},
        ])

        entries = (await db_session.execute(
            select(TaskHistory).where(TaskHistory.document_kind == "estimate")
        )).scalars().all()
        assert len(entries) == 1
        assert entries[0].operation_type == "document_price_list"
        assert "Иванов Иван" in entries[0].description
        assert "прайс" in entries[0].description.lower()

    @pytest.mark.asyncio
    async def test_history_entry_cannot_be_reverted(
        self, async_client, db_session, price_env
    ):
        """Запись в прайс строк документа не меняет — откатывать нечего."""
        await _post(async_client, price_env, [
            {"kind": "work", "name": "Кладка стен", "unit": "м3", "price": 1000},
        ])
        entry = (await db_session.execute(select(TaskHistory))).scalars().first()

        r = await async_client.post(
            f"/documents/{price_env['card_id']}/estimate/history/{entry.id}/revert",
            headers=_auth(price_env["pm"], "project_manager"),
        )

        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_document_rev_untouched(self, async_client, db_session, price_env):
        """Запись в прайс не двигает rev: у соседа «Применить» не должно ломаться."""
        await async_client.get(
            f"/documents/{price_env['card_id']}/estimate",
            headers=_auth(price_env["pm"], "project_manager"),
        )
        version = (await db_session.execute(select(EstimateVersion))).scalars().first()
        rev_before = version.rev

        await _post(async_client, price_env, [
            {"kind": "work", "name": "Кладка стен", "unit": "м3", "price": 1000},
        ])
        await db_session.refresh(version)

        assert version.rev == rev_before

    @pytest.mark.asyncio
    async def test_foreign_document_forbidden(self, async_client, price_env):
        """Менеджер не работает с чужой сметой — в том числе через прайс."""
        r = await _post(async_client, price_env, [
            {"kind": "work", "name": "Кладка", "unit": "м3", "price": 1000},
        ], user="other")

        assert r.status_code in (403, 404)

    @pytest.mark.asyncio
    async def test_flat_document_rejected(self, async_client, db_session, price_env):
        """У перечня нет цен и типов строк — добавлять в прайс нечего."""
        task = Task(
            owner_id=price_env["pm"], user_role="project_manager",
            task_type="LIST_FROM_GRAND", status="completed",
            input_files=[], input_file_data=[], chat_history=[],
            project_id=price_env["project_id"],
        )
        db_session.add(task)
        await db_session.flush()
        card = await db_session.get(WorkflowCard, price_env["card_id"])
        card.list_task_id = str(task.id)
        db_session.add(EstimateVersion(
            task_id=str(task.id), version_number=0, version_label="original",
            version_display_name="V0", rows=[], file_slot="result",
            task_type="LIST_FROM_GRAND",
        ))
        await db_session.commit()

        r = await _post(async_client, price_env, [
            {"kind": "work", "name": "Кладка", "unit": "м3", "price": 1000},
        ], kind="list")

        assert r.status_code == 409

    @pytest.mark.asyncio
    async def test_price_cache_reloaded_after_write(
        self, async_client, price_env
    ):
        """Без перезагрузки кэша добавленная позиция не участвовала бы в расчёте
        до следующего перезапуска сервера."""
        from app.services import price_service

        await _post(async_client, price_env, [
            {"kind": "work", "name": "Кладка стен", "unit": "м3", "price": 1000},
        ])

        matched = price_service._exact_match_work("Кладка стен")
        assert matched is not None
        assert matched["min_price"] == 1000


# ---------------------------------------------------------------------------
# Правило минимальной цены на обычных путях каталога
# ---------------------------------------------------------------------------

class TestCatalogPathsFollowSameRule:
    """Правило одно на весь прайс: иначе ручная правка каталога вернула бы
    старое поведение и расчёт снова взял бы цену подрядчика.

    Каталог правит руководитель (`get_manager_user` — admin | head_of_sales), а
    добавлять позиции из сметы может любой сотрудник: это разные права.
    """

    @pytest.mark.asyncio
    async def test_create_work_via_catalog(self, async_client, db_session, price_env):
        r = await async_client.post(
            "/prices/catalog/works",
            json={"name": "Кладка", "unit": "м3",
                  "prices": {"Подрядчик А": 1200, ESTIMATE_CONTRACTOR: 2000}},
            headers=_auth(price_env["pm"], "head_of_sales"),
        )

        assert r.status_code == 201, r.text
        assert r.json()["price"] == 2000

    @pytest.mark.asyncio
    async def test_update_work_via_catalog(self, async_client, db_session, price_env):
        work = PriceWork(name="Кладка", unit="м3",
                         prices={"Подрядчик А": 1200}, min_price=1200)
        db_session.add(work)
        await db_session.commit()

        r = await async_client.put(
            f"/prices/catalog/works/{work.id}",
            json={"prices": {"Подрядчик А": 1200, ESTIMATE_CONTRACTOR: 2000}},
            headers=_auth(price_env["pm"], "head_of_sales"),
        )

        assert r.status_code == 200, r.text
        assert r.json()["price"] == 2000
