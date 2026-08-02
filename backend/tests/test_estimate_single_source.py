"""Смета хранится в одном месте.

Фаза 5 плана `plans/2026-08-02-edinyy-redaktor-tablic.md`.

До этой фазы смета жила в двух хранилищах: `task.progress_data['items']` и
`EstimateVersion.rows`. Правка на странице задачи и правка в редакторе писали в
разные места, и пользователь видел три разных числа для одной строки — на
странице задачи, в редакторе и в скачанном файле.

Здесь проверяется главный критерий приёмки: **правка любым путём меняет ровно
одно хранилище, а итог задачи, содержимое редактора и скачанный файл дают одно
и то же число.**
"""
import io

import openpyxl
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.document_lock import DocumentLock
from app.models.estimate_version import EstimateVersion
from app.models.history import TaskHistory
from app.models.project import Project
from app.models.result import TaskResult
from app.models.task import Task
from app.models.user import User
from app.models.workflow_card import WorkflowCard
from app.services import estimate_store, storage_service
from app.utils.auth import create_access_token, hash_password
from app.utils.estimate_rows import items_to_rows, items_signature, rows_to_items


def _auth(user_id: int, role: str) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id, role)}"}


def _items(work_price: float = 1000.0) -> list[dict]:
    return [
        {
            "type": "Работа", "name": "Кладка стен", "unit": "м3", "quantity": 4,
            "work_price": work_price, "material_price": None,
            "price_list_name": "Прайс", "sources": "прайс подрядчика",
            "notes": "по проекту",
        },
        {
            "type": "Материал", "name": "Кирпич", "unit": "шт", "quantity": 400,
            "work_price": None, "material_price": 25.0,
            "price_list_name": "Интернет", "sources": "сайт поставщика",
            "notes": "цена с НДС",
        },
    ]


def _grand_total_from_xlsx(data: bytes) -> float:
    """Итог из скачиваемого файла — строка «ИТОГО ПО СМЕТЕ:»."""
    ws = openpyxl.load_workbook(io.BytesIO(data), data_only=True).active
    for row in ws.iter_rows(values_only=True):
        for index, value in enumerate(row):
            if isinstance(value, str) and value.startswith("ИТОГО"):
                tail = [v for v in row[index + 1:] if isinstance(v, (int, float))]
                if tail:
                    return float(tail[-1])
    raise AssertionError("В файле нет строки «ИТОГО ПО СМЕТЕ:»")


@pytest_asyncio.fixture
async def est_env(db_session, fake_s3):
    """Проект → карточка → задача «Смета из перечня» с позициями от ИИ."""
    for model in (DocumentLock, EstimateVersion, TaskHistory, TaskResult,
                  WorkflowCard, Task, Project, User):
        await db_session.execute(model.__table__.delete())
    await db_session.commit()

    pm = User(username="pm1", role="project_manager", full_name="Иванов Иван",
              password_hash=hash_password("p1"))
    db_session.add(pm)
    await db_session.flush()

    project = Project(name="Объект АР", owner_id=pm.id)
    db_session.add(project)
    await db_session.flush()

    task = Task(
        owner_id=pm.id, user_role="project_manager", task_type="ESTIMATE_FROM_LIST",
        status="completed", input_files=[], input_file_data=[], chat_history=[],
        project_id=str(project.id),
        progress_data={"items": _items()},
    )
    db_session.add(task)
    await db_session.flush()

    card = WorkflowCard(project_id=str(project.id), name="АР", stage="estimate",
                        estimate_task_id=str(task.id))
    db_session.add(card)
    await db_session.commit()

    yield {
        "pm": pm.id, "project_id": str(project.id), "card_id": str(card.id),
        "task_id": str(task.id), "task": task,
    }

    for model in (DocumentLock, EstimateVersion, TaskHistory, TaskResult,
                  WorkflowCard, Task, Project, User):
        await db_session.execute(model.__table__.delete())
    await db_session.commit()


# ---------------------------------------------------------------------------
# Перевод между форматами
# ---------------------------------------------------------------------------

class TestRowItemConversion:
    def test_round_trip_keeps_numbers(self):
        items = _items()
        back = rows_to_items(items_to_rows(items))

        assert items_signature(back) == items_signature(items)

    def test_round_trip_keeps_price_source_and_notes(self):
        back = rows_to_items(items_to_rows(_items()))

        assert back[0]["price_list_name"] == "Прайс"
        assert back[0]["sources"] == "прайс подрядчика"
        assert back[1]["notes"] == "цена с НДС"

    def test_round_trip_keeps_row_identity(self):
        rows = items_to_rows(_items())
        again = items_to_rows(rows_to_items(rows))

        assert [r["id"] for r in again] == [r["id"] for r in rows]

    def test_negative_quantity_has_no_cost_but_keeps_sign(self):
        rows = items_to_rows([{
            "type": "Работа", "name": "Вычет", "unit": "м", "quantity": -0.61,
            "work_price": 100.0, "material_price": None,
        }])

        assert rows[0]["qty"] == -0.61
        assert rows[0]["cost"] is None

    def test_type_inferred_when_missing(self):
        rows = items_to_rows([
            {"name": "Материал без типа", "quantity": 1, "material_price": 10.0},
            {"name": "Работа без типа", "quantity": 1, "work_price": 10.0},
        ])

        assert rows[0]["type"] == "material"
        assert rows[1]["type"] == "work"


# ---------------------------------------------------------------------------
# Одно хранилище
# ---------------------------------------------------------------------------

class TestSingleStorage:
    @pytest.mark.asyncio
    async def test_read_items_prefers_version_over_progress_data(self, db_session, est_env):
        task = await db_session.get(Task, est_env["task_id"])
        await estimate_store.write_items(db_session, task, _items(work_price=7777.0))

        items = await estimate_store.read_items(db_session, task)

        assert items[0]["work_price"] == 7777.0
        # progress_data остаётся записью «что выдал ИИ» и не переписывается
        assert task.progress_data["items"][0]["work_price"] == 1000.0

    @pytest.mark.asyncio
    async def test_read_items_falls_back_to_progress_data(self, db_session, est_env):
        """Сметы, посчитанные до перехода, версии ещё не имеют."""
        task = await db_session.get(Task, est_env["task_id"])

        items = await estimate_store.read_items(db_session, task)

        assert [i["name"] for i in items] == ["Кладка стен", "Кирпич"]

    @pytest.mark.asyncio
    async def test_write_creates_single_working_version(self, db_session, est_env):
        task = await db_session.get(Task, est_env["task_id"])
        await estimate_store.write_items(db_session, task, _items())
        await estimate_store.write_items(db_session, task, _items(work_price=2000.0))

        res = await db_session.execute(
            select(EstimateVersion).where(EstimateVersion.task_id == est_env["task_id"])
        )
        versions = list(res.scalars().all())

        assert len(versions) == 1
        assert versions[0].rows[0]["price_work"] == 2000.0

    @pytest.mark.asyncio
    async def test_write_bumps_rev(self, db_session, est_env):
        task = await db_session.get(Task, est_env["task_id"])
        version, _ = await estimate_store.write_items(db_session, task, _items())
        assert version.rev == 0

        version, _ = await estimate_store.write_items(db_session, task, _items(work_price=2.0))
        assert version.rev == 1

    @pytest.mark.asyncio
    async def test_write_drops_stale_draft(self, db_session, est_env):
        task = await db_session.get(Task, est_env["task_id"])
        version, _ = await estimate_store.write_items(db_session, task, _items())
        version.draft_rows = [{"id": "x"}]
        await db_session.commit()

        await estimate_store.write_items(db_session, task, _items(work_price=3.0))

        assert version.draft_rows is None


# ---------------------------------------------------------------------------
# Три числа сходятся
# ---------------------------------------------------------------------------

class TestNumbersAgree:
    @pytest.mark.asyncio
    async def test_cost_editor_and_file_agree_after_write(self, db_session, est_env):
        task = await db_session.get(Task, est_env["task_id"])
        version, grand_total = await estimate_store.write_items(db_session, task, _items())

        res = await db_session.execute(
            select(TaskResult).where(
                TaskResult.task_id == est_env["task_id"], TaskResult.slot == "estimate",
            )
        )
        stored = res.scalar_one()
        file_total = _grand_total_from_xlsx(await storage_service.load_bytes(stored.storage_key))

        # 4 × 1000 = 4000 работ, 400 × 25 = 10000 материалов, по 3% сверху
        expected = round(4000 + 120 + 10000 + 300, 2)
        assert grand_total == expected
        assert float(task.cost) == expected
        assert file_total == expected
        assert sum(r["cost"] or 0 for r in version.rows) == 14000

    @pytest.mark.asyncio
    async def test_apply_through_document_api_updates_cost_and_file(
        self, db_session, est_env, async_client
    ):
        task = await db_session.get(Task, est_env["task_id"])
        version, _ = await estimate_store.write_items(db_session, task, _items())

        rows = [dict(r) for r in version.rows]
        rows[0]["price_work"] = 2000.0

        response = await async_client.post(
            f"/documents/{est_env['card_id']}/estimate/apply",
            json={"rows": rows, "rev": version.rev},
            headers=_auth(est_env["pm"], "project_manager"),
        )
        assert response.status_code == 200, response.text

        await db_session.refresh(task)
        res = await db_session.execute(
            select(TaskResult).where(
                TaskResult.task_id == est_env["task_id"], TaskResult.slot == "estimate",
            )
        )
        stored = res.scalar_one()
        file_total = _grand_total_from_xlsx(await storage_service.load_bytes(stored.storage_key))

        expected = round(8000 + 240 + 10000 + 300, 2)
        assert float(task.cost) == expected
        assert file_total == expected

    @pytest.mark.asyncio
    async def test_user_edit_does_not_touch_ai_record(
        self, db_session, est_env, async_client
    ):
        task = await db_session.get(Task, est_env["task_id"])
        version, _ = await estimate_store.write_items(db_session, task, _items())

        rows = [dict(r) for r in version.rows]
        rows[0]["price_work"] = 2000.0
        await async_client.post(
            f"/documents/{est_env['card_id']}/estimate/apply",
            json={"rows": rows, "rev": version.rev},
            headers=_auth(est_env["pm"], "project_manager"),
        )

        await db_session.refresh(task)
        assert task.progress_data["items"][0]["work_price"] == 1000.0


# ---------------------------------------------------------------------------
# Старый эндпоинт остаётся рабочим и пишет туда же
# ---------------------------------------------------------------------------

class TestLegacyEndpoint:
    @pytest.mark.asyncio
    async def test_old_editor_save_rows_updates_cost_and_file(
        self, db_session, est_env, async_client
    ):
        """Старый редактор сметы пишет туда же и тоже пересобирает файл и итог.

        Иначе он остался бы щелью, через которую смета снова расходится:
        строки версии новые, а `task.cost` и скачиваемый файл — старые.
        """
        task = await db_session.get(Task, est_env["task_id"])
        version, _ = await estimate_store.write_items(db_session, task, _items())

        rows = [dict(r) for r in version.rows]
        rows[0]["price_work"] = 3000.0

        response = await async_client.put(
            f"/tasks/{est_env['task_id']}/estimate/versions/{version.id}/rows",
            json={"rows": rows},
            headers=_auth(est_env["pm"], "project_manager"),
        )
        assert response.status_code == 200, response.text

        await db_session.refresh(task)
        res = await db_session.execute(
            select(TaskResult).where(
                TaskResult.task_id == est_env["task_id"], TaskResult.slot == "estimate",
            )
        )
        stored = res.scalar_one()
        file_total = _grand_total_from_xlsx(await storage_service.load_bytes(stored.storage_key))

        expected = round(12000 + 360 + 10000 + 300, 2)
        assert float(task.cost) == expected
        assert file_total == expected


    @pytest.mark.asyncio
    async def test_patch_estimate_items_writes_into_version(
        self, db_session, est_env, async_client
    ):
        task = await db_session.get(Task, est_env["task_id"])
        await estimate_store.write_items(db_session, task, _items())

        response = await async_client.patch(
            f"/tasks/{est_env['task_id']}/estimate-items",
            json={"items": _items(work_price=5000.0)},
            headers=_auth(est_env["pm"], "project_manager"),
        )
        assert response.status_code == 200, response.text

        version = await estimate_store.get_working_version(db_session, est_env["task_id"])
        await db_session.refresh(version)
        await db_session.refresh(task)

        expected = round(20000 + 600 + 10000 + 300, 2)
        assert version.rows[0]["price_work"] == 5000.0
        assert float(task.cost) == expected
        assert response.json()["grand_total"] == expected
