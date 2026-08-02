"""Разовая миграция смет на единый источник правды.

Фаза 5 плана `plans/2026-08-02-edinyy-redaktor-tablic.md`.

Это единственное необратимое действие во всём плане, поэтому здесь проверяется
не столько «мигрирует», сколько «не портит»: режим отчёта ничего не меняет,
повторный запуск ничего не делает, а смета с расхождением между двумя
хранилищами не мигрируется молча — она попадает в отчёт и ждёт решения человека.
"""
import pytest
import pytest_asyncio

from app.models.estimate_version import EstimateVersion
from app.models.history import TaskHistory
from app.models.project import Project
from app.models.result import TaskResult
from app.models.task import Task
from app.models.user import User
from app.services import estimate_store
from app.utils.auth import hash_password
from app.utils.estimate_rows import items_to_rows, items_total
from scripts.migrate_estimate_items import migrate_estimates


def _items(work_price: float = 1000.0) -> list[dict]:
    return [
        {"type": "Работа", "name": "Кладка стен", "unit": "м3", "quantity": 4,
         "work_price": work_price, "material_price": None},
        {"type": "Материал", "name": "Кирпич", "unit": "шт", "quantity": 400,
         "work_price": None, "material_price": 25.0},
    ]


@pytest_asyncio.fixture
async def mig_env(db_session, fake_s3):
    for model in (EstimateVersion, TaskHistory, TaskResult, Task, Project, User):
        await db_session.execute(model.__table__.delete())
    await db_session.commit()

    pm = User(username="pm1", role="project_manager", password_hash=hash_password("p1"))
    db_session.add(pm)
    await db_session.flush()

    project = Project(name="Объект", owner_id=pm.id)
    db_session.add(project)
    await db_session.flush()

    async def make_task(items, name="Смета") -> Task:
        task = Task(
            owner_id=pm.id, user_role="project_manager",
            task_type="ESTIMATE_FROM_LIST", status="completed",
            input_files=[], input_file_data=[], chat_history=[],
            project_id=str(project.id), name=name,
            progress_data={"items": items},
        )
        db_session.add(task)
        await db_session.flush()
        return task

    yield {"db": db_session, "make_task": make_task}

    for model in (EstimateVersion, TaskHistory, TaskResult, Task, Project, User):
        await db_session.execute(model.__table__.delete())
    await db_session.commit()


async def _versions_count(db) -> int:
    from sqlalchemy import select
    res = await db.execute(select(EstimateVersion))
    return len(list(res.scalars().all()))


# ---------------------------------------------------------------------------
# Отчёт ничего не меняет
# ---------------------------------------------------------------------------

class TestDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_changes_nothing(self, mig_env):
        db = mig_env["db"]
        await mig_env["make_task"](_items())
        await db.commit()

        report = await migrate_estimates(db, apply=False)

        assert await _versions_count(db) == 0
        assert report.counts["needs_version"] == 1

    @pytest.mark.asyncio
    async def test_report_shows_money(self, mig_env):
        db = mig_env["db"]
        await mig_env["make_task"](_items())
        await db.commit()

        report = await migrate_estimates(db, apply=False)

        assert report.entries[0].items_total == items_total(_items())


# ---------------------------------------------------------------------------
# Создание недостающих версий
# ---------------------------------------------------------------------------

class TestCreateVersions:
    @pytest.mark.asyncio
    async def test_apply_creates_version_without_losing_numbers(self, mig_env):
        db = mig_env["db"]
        task = await mig_env["make_task"](_items())
        await db.commit()

        await migrate_estimates(db, apply=True)

        version = await estimate_store.get_working_version(db, str(task.id))
        assert version is not None
        assert [r["name"] for r in version.rows] == ["Кладка стен", "Кирпич"]
        assert version.rows[0]["price_work"] == 1000.0

    @pytest.mark.asyncio
    async def test_apply_is_idempotent(self, mig_env):
        db = mig_env["db"]
        await mig_env["make_task"](_items())
        await db.commit()

        await migrate_estimates(db, apply=True)
        second = await migrate_estimates(db, apply=True)

        assert await _versions_count(db) == 1
        assert second.counts.get("needs_version", 0) == 0
        assert second.counts["in_sync"] == 1

    @pytest.mark.asyncio
    async def test_task_without_items_is_skipped(self, mig_env):
        db = mig_env["db"]
        task = await mig_env["make_task"]([])
        task.progress_data = {}
        await db.commit()

        report = await migrate_estimates(db, apply=True)

        assert await _versions_count(db) == 0
        assert report.counts["empty"] == 1


# ---------------------------------------------------------------------------
# Расхождения
# ---------------------------------------------------------------------------

class TestConflicts:
    @pytest.mark.asyncio
    async def test_matching_estimate_is_in_sync(self, mig_env):
        db = mig_env["db"]
        task = await mig_env["make_task"](_items())
        await db.commit()
        await estimate_store.write_items(db, task, _items())

        report = await migrate_estimates(db, apply=True)

        assert report.counts["in_sync"] == 1

    @pytest.mark.asyncio
    async def test_conflict_is_reported_and_not_migrated(self, mig_env):
        db = mig_env["db"]
        task = await mig_env["make_task"](_items())
        await db.commit()
        await estimate_store.write_items(db, task, _items(work_price=9999.0))

        report = await migrate_estimates(db, apply=True)
        version = await estimate_store.get_working_version(db, str(task.id))

        assert report.counts["conflict"] == 1
        assert report.entries[0].diff_count == 1
        # Версию не тронули — решение за человеком
        assert version.rows[0]["price_work"] == 9999.0

    @pytest.mark.asyncio
    async def test_prefer_items_resolves_conflict_and_backs_up(self, mig_env):
        db = mig_env["db"]
        task = await mig_env["make_task"](_items())
        await db.commit()
        await estimate_store.write_items(db, task, _items(work_price=9999.0))

        report = await migrate_estimates(db, apply=True, prefer="items")
        version = await estimate_store.get_working_version(db, str(task.id))

        from sqlalchemy import select
        res = await db.execute(
            select(TaskHistory).where(TaskHistory.task_id == str(task.id))
        )
        backups = [e for e in res.scalars().all() if e.operation_type == "estimate_migration"]

        assert report.counts["resolved"] == 1
        assert version.rows[0]["price_work"] == 1000.0
        assert len(backups) == 1
        assert backups[0].previous_value["rows"][0]["price_work"] == 9999.0
        assert backups[0].previous_value["items"][0]["work_price"] == 1000.0

    @pytest.mark.asyncio
    async def test_excluded_task_is_never_touched(self, mig_env):
        db = mig_env["db"]
        task = await mig_env["make_task"](_items())
        await db.commit()

        report = await migrate_estimates(db, apply=True, exclude={str(task.id)})

        assert await _versions_count(db) == 0
        assert report.counts["excluded"] == 1


# ---------------------------------------------------------------------------
# Итог отчёта совпадает с итогом файла
# ---------------------------------------------------------------------------

class TestTotalsMatchFile:
    def test_items_total_matches_generator(self):
        from app.utils.xlsx_exporter import generate_estimate_xlsx

        _, grand_total = generate_estimate_xlsx(_items())

        assert items_total(_items()) == grand_total

    def test_items_total_ignores_negative_quantity(self):
        from app.utils.xlsx_exporter import generate_estimate_xlsx

        items = _items() + [{
            "type": "Работа", "name": "Вычет", "unit": "м", "quantity": -5,
            "work_price": 100.0, "material_price": None,
        }]
        _, grand_total = generate_estimate_xlsx(items)

        assert items_total(items) == grand_total

    def test_rows_and_items_give_same_total(self):
        rows = items_to_rows(_items())
        from app.utils.estimate_rows import rows_to_items

        assert items_total(rows_to_items(rows)) == items_total(_items())
