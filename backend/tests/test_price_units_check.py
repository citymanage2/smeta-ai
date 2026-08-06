"""Кнопка «Проверить цены» для смет, посчитанных до сверки единиц.

Подбор цены теперь единицу сверяет, но сметы, посчитанные раньше, уже стоят с
ценой за тонну в строке с килограммами. Пересчитывать их за человека нельзя —
цену могли поправить руками, — поэтому проверка только помечает подозрительные
строки, а решает человек.

Спека: specs/2026-08-06-edinica-izmereniya-v-podbore-ceny.md
"""
import pytest
import pytest_asyncio

from app.models.document_lock import DocumentLock
from app.models.estimate_version import EstimateVersion
from app.models.history import TaskHistory
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.models.workflow_card import WorkflowCard
from app.utils.auth import create_access_token, hash_password
from app.utils.unit_compat import PRICE_UNIT_MISMATCH_PREFIX


def _auth(user_id: int, role: str) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id, role, 'pm1')}"}


def _row(row_id: str, kind: str, name: str, unit: str, qty: float,
         price: float) -> dict:
    field = "price_work" if kind == "work" else "price_material"
    row = {"id": row_id, "lineage_id": row_id, "type": kind, "name": name,
           "unit": unit, "qty": qty, "price_work": None, "price_material": None}
    row[field] = price
    return row


@pytest_asyncio.fixture
async def estimate_env(db_session, fake_s3):
    for model in (DocumentLock, EstimateVersion, TaskHistory, WorkflowCard,
                  Task, Project, User):
        await db_session.execute(model.__table__.delete())
    await db_session.commit()

    pm1 = User(username="pm1", role="project_manager", full_name="Иванов Иван",
               password_hash=hash_password("p1"))
    db_session.add(pm1)
    await db_session.flush()

    project = Project(name="Объект АР", owner_id=pm1.id)
    db_session.add(project)
    await db_session.flush()

    task = Task(
        owner_id=pm1.id, user_role="project_manager", task_type="ESTIMATE_FROM_LIST",
        status="completed", input_files=[], input_file_data=[], chat_history=[],
        project_id=str(project.id),
    )
    db_session.add(task)
    await db_session.flush()

    card = WorkflowCard(project_id=str(project.id), name="АР", stage="estimate",
                        estimate_task_id=str(task.id))
    db_session.add(card)

    rows = [
        # Цена за тонну стоит в строке с килограммами — та самая ошибка.
        _row("r1", "material", "Смеси сухие", "кг", 30, 73770.0),
        # Цена уже пересчитана к единице позиции — тревожить незачем.
        _row("r2", "material", "Затирка", "кг", 10, 73.77),
        # Единицы совпадают — обычная строка.
        _row("r3", "work", "Окраска", "м2", 100, 180.0),
    ]
    version = EstimateVersion(
        task_id=str(task.id), version_number=0, version_label="original",
        version_display_name="Смета", rows=rows, file_slot="estimate",
        task_type="ESTIMATE_FROM_LIST",
    )
    db_session.add(version)
    await db_session.commit()

    yield {"pm1": pm1.id, "card_id": str(card.id), "task_id": str(task.id),
           "version_id": str(version.id)}

    for model in (DocumentLock, EstimateVersion, TaskHistory, WorkflowCard,
                  Task, Project, User):
        await db_session.execute(model.__table__.delete())
    await db_session.commit()


class _FakePrices:
    """Прайс: затирка стоит 73 770 ₽ за тонну, окраска — 180 ₽ за м2."""

    @staticmethod
    def _exact_match_work(name):
        if name == "Окраска":
            return {"name": name, "min_price": 180.0, "unit": "м2"}
        return None

    @staticmethod
    def _exact_match_material_row(name):
        if name in ("Смеси сухие", "Затирка"):
            return {"name": name, "price": 73770.0, "unit": "т"}
        return None

    @staticmethod
    def _exact_match_cache_work(name):
        return None

    @staticmethod
    def _exact_match_cache_material(name):
        return None

    @staticmethod
    async def batch_embedding_match_works(names):
        return [None] * len(names)

    @staticmethod
    async def batch_embedding_match_material_rows(names):
        return [None] * len(names)


@pytest.fixture
def fake_prices(monkeypatch):
    import app.services.price_service as real

    for attribute in (
        "_exact_match_work", "_exact_match_material_row",
        "_exact_match_cache_work", "_exact_match_cache_material",
        "batch_embedding_match_works", "batch_embedding_match_material_rows",
    ):
        monkeypatch.setattr(real, attribute, getattr(_FakePrices, attribute))


@pytest.mark.asyncio
async def test_stroka_s_chuzhoy_edinicey_pomechaetsya(
    async_client, db_session, estimate_env, fake_prices
):
    r = await async_client.post(
        f"/documents/{estimate_env['card_id']}/estimate/price-units-check",
        json={"rev": 0},
        headers=_auth(estimate_env["pm1"], "project_manager"),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["checked"] == 3
    assert data["flagged"] == 1

    version = await db_session.get(EstimateVersion, estimate_env["version_id"])
    await db_session.refresh(version)
    rows = {row["id"]: row for row in version.rows}

    assert PRICE_UNIT_MISMATCH_PREFIX in rows["r1"]["notes"]
    assert "73,77" in rows["r1"]["notes"], "человеку показывают ожидаемую цену"
    # Цена не тронута: решает человек.
    assert rows["r1"]["price_material"] == 73770.0

    assert not (rows["r2"].get("notes") or ""), "пересчитанную цену не трогаем"
    assert not (rows["r3"].get("notes") or ""), "совпавшую единицу не трогаем"


@pytest.mark.asyncio
async def test_povtornaya_proverka_ne_dvoit_pometku(
    async_client, db_session, estimate_env, fake_prices
):
    headers = _auth(estimate_env["pm1"], "project_manager")
    url = f"/documents/{estimate_env['card_id']}/estimate/price-units-check"

    first = await async_client.post(url, json={"rev": 0}, headers=headers)
    assert first.json()["flagged"] == 1
    rev = first.json()["rev"]

    second = await async_client.post(url, json={"rev": rev}, headers=headers)
    assert second.status_code == 200, second.text
    assert second.json()["flagged"] == 0, "второй проход помечать нечего"
    assert second.json()["rev"] == rev, "без изменений rev не растёт"


@pytest.mark.asyncio
async def test_perechen_proveryat_nechem(
    async_client, db_session, estimate_env, fake_prices
):
    """У плоского перечня нет ни цен, ни типов строк — отказ понятный."""
    task = Task(
        owner_id=estimate_env["pm1"], user_role="project_manager",
        task_type="LIST_FROM_GRAND", status="completed",
        input_files=[], input_file_data=[], chat_history=[],
    )
    db_session.add(task)
    await db_session.flush()
    card = await db_session.get(WorkflowCard, estimate_env["card_id"])
    card.list_task_id = str(task.id)
    db_session.add(EstimateVersion(
        task_id=str(task.id), version_number=0, version_label="original",
        version_display_name="V0", rows=[], file_slot="result",
        task_type="LIST_FROM_GRAND",
    ))
    await db_session.commit()

    r = await async_client.post(
        f"/documents/{estimate_env['card_id']}/list/price-units-check",
        json={"rev": 0},
        headers=_auth(estimate_env["pm1"], "project_manager"),
    )
    assert r.status_code == 409
