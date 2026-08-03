"""Перевод смет на единый источник правды — из админки.

План: `plans/2026-08-03-migraciya-smet-iz-adminki.md`.

Разовая операция, которая раньше запускалась только командой в консоли сервера.
Здесь проверяется то, что делает её безопасной для человека без консоли:

- отчёт не меняет ни одной записи;
- применение создаёт версии тем сметам, у которых их нет, и **не трогает** те,
  где два хранилища разошлись;
- смету можно исключить из операции (активный тендер);
- расхождение разбирается по одной смете, обе стороны уходят в историю;
- повторный запуск ничего не меняет;
- всё это доступно только администратору.
"""
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.estimate_version import EstimateVersion
from app.models.history import TaskHistory
from app.models.project import Project
from app.models.result import TaskResult
from app.models.task import Task
from app.models.user import User
# Импорт ради метаданных SQLAlchemy: на document_locks висит внешний ключ к
# workflow_cards, и при запуске одного этого файла таблица иначе не находится.
from app.models.workflow_card import WorkflowCard  # noqa: F401
from app.services import estimate_store
from app.utils.auth import create_access_token, hash_password


def _auth(user_id: int, role: str) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id, role)}"}


def _items(work_price: float = 1000.0, name: str = "Кладка стен") -> list:
    return [
        {"type": "Работа", "name": name, "unit": "м3", "quantity": 4,
         "work_price": work_price, "material_price": None},
        {"type": "Материал", "name": "Кирпич", "unit": "шт", "quantity": 400,
         "work_price": None, "material_price": 25.0},
    ]


@pytest_asyncio.fixture
async def mig_env(db_session, fake_s3):
    """Админ, менеджер и три сметы: без версии, совпадающая и расходящаяся."""
    for model in (EstimateVersion, TaskHistory, TaskResult, Task, Project, User):
        await db_session.execute(model.__table__.delete())
    await db_session.commit()

    admin = User(username="root", role="admin", full_name="Администратор",
                 password_hash=hash_password("p1"))
    manager = User(username="pm1", role="project_manager", full_name="Иванов Иван",
                   password_hash=hash_password("p2"))
    db_session.add_all([admin, manager])
    await db_session.flush()

    project = Project(name="Объект АР", owner_id=admin.id)
    db_session.add(project)
    await db_session.flush()

    def _task(name: str, items: list) -> Task:
        return Task(
            owner_id=admin.id, user_role="admin", task_type="ESTIMATE_FROM_LIST",
            status="completed", input_files=[], input_file_data=[], chat_history=[],
            project_id=str(project.id), name=name, progress_data={"items": items},
        )

    # 1. Версии нет — её и должна создать миграция.
    no_version = _task("Смета без версии", _items())
    # 2. Версия совпадает с позициями расчёта.
    in_sync = _task("Смета в порядке", _items())
    # 3. Версия и позиции разошлись — трогать нельзя без решения человека.
    conflict = _task("Смета с расхождением", _items(work_price=1000.0))
    db_session.add_all([no_version, in_sync, conflict])
    await db_session.flush()

    await estimate_store.ensure_working_version(
        db_session, in_sync, estimate_store.items_to_rows(_items()), commit=False,
    )
    await estimate_store.ensure_working_version(
        db_session, conflict,
        estimate_store.items_to_rows(_items(work_price=777.0)), commit=False,
    )
    await db_session.commit()

    yield {
        "admin": admin.id, "manager": manager.id,
        "no_version": str(no_version.id), "in_sync": str(in_sync.id),
        "conflict": str(conflict.id),
    }

    for model in (EstimateVersion, TaskHistory, TaskResult, Task, Project, User):
        await db_session.execute(model.__table__.delete())
    await db_session.commit()


async def _report(async_client, env, user="admin"):
    return await async_client.get(
        "/admin/estimates/migration",
        headers=_auth(env[user], "admin" if user == "admin" else "project_manager"),
    )


async def _apply(async_client, env, exclude=None):
    return await async_client.post(
        "/admin/estimates/migration/apply",
        json={"exclude": exclude or []},
        headers=_auth(env["admin"], "admin"),
    )


def _by_id(report: dict, task_id: str) -> dict:
    return next(e for e in report["entries"] if e["task_id"] == task_id)


# ---------------------------------------------------------------------------
# Отчёт
# ---------------------------------------------------------------------------

class TestReport:
    @pytest.mark.asyncio
    async def test_report_classifies_every_estimate(self, async_client, mig_env):
        r = await _report(async_client, mig_env)

        assert r.status_code == 200, r.text
        body = r.json()
        assert _by_id(body, mig_env["no_version"])["status"] == "needs_version"
        assert _by_id(body, mig_env["in_sync"])["status"] == "in_sync"
        assert _by_id(body, mig_env["conflict"])["status"] == "conflict"

    @pytest.mark.asyncio
    async def test_report_shows_both_totals_for_conflict(self, async_client, mig_env):
        """По этим двум числам человек и решает, чью сторону взять."""
        body = (await _report(async_client, mig_env)).json()

        entry = _by_id(body, mig_env["conflict"])
        assert entry["items_total"] > 0
        assert entry["version_total"] > 0
        assert entry["items_total"] != entry["version_total"]
        assert entry["diff_count"] >= 1

    @pytest.mark.asyncio
    async def test_report_changes_nothing(self, async_client, db_session, mig_env):
        before = len((await db_session.execute(select(EstimateVersion))).scalars().all())

        await _report(async_client, mig_env)

        after = len((await db_session.execute(select(EstimateVersion))).scalars().all())
        assert after == before

    @pytest.mark.asyncio
    async def test_summary_counts_present(self, async_client, mig_env):
        body = (await _report(async_client, mig_env)).json()

        assert body["counts"]["needs_version"] == 1
        assert body["counts"]["conflict"] == 1
        assert body["applied"] is False


# ---------------------------------------------------------------------------
# Создание недостающих версий
# ---------------------------------------------------------------------------

class TestApply:
    @pytest.mark.asyncio
    async def test_apply_creates_missing_version(
        self, async_client, db_session, mig_env
    ):
        r = await _apply(async_client, mig_env)

        assert r.status_code == 200, r.text
        version = await estimate_store.get_working_version(
            db_session, mig_env["no_version"])
        assert version is not None
        assert len(version.rows) == 2

    @pytest.mark.asyncio
    async def test_apply_does_not_touch_conflicts(
        self, async_client, db_session, mig_env
    ):
        """Смета с расхождением ждёт решения человека, а не догадки скрипта."""
        before = await estimate_store.get_working_version(
            db_session, mig_env["conflict"])
        rows_before = list(before.rows)

        await _apply(async_client, mig_env)

        await db_session.refresh(before)
        assert before.rows == rows_before

    @pytest.mark.asyncio
    async def test_excluded_estimate_is_skipped(
        self, async_client, db_session, mig_env
    ):
        """Активный тендер не трогаем — даже если версии у него нет."""
        r = await _apply(async_client, mig_env, exclude=[mig_env["no_version"]])

        assert _by_id(r.json(), mig_env["no_version"])["status"] == "excluded"
        assert await estimate_store.get_working_version(
            db_session, mig_env["no_version"]) is None

    @pytest.mark.asyncio
    async def test_apply_is_idempotent(self, async_client, db_session, mig_env):
        await _apply(async_client, mig_env)
        first = await estimate_store.get_working_version(
            db_session, mig_env["no_version"])
        first_rows = list(first.rows)

        second = await _apply(async_client, mig_env)

        assert _by_id(second.json(), mig_env["no_version"])["status"] == "in_sync"
        await db_session.refresh(first)
        assert first.rows == first_rows


# ---------------------------------------------------------------------------
# Разбор расхождения по одной смете
# ---------------------------------------------------------------------------

class TestResolve:
    async def _resolve(self, async_client, env, task_id, prefer):
        return await async_client.post(
            "/admin/estimates/migration/resolve",
            json={"task_id": task_id, "prefer": prefer},
            headers=_auth(env["admin"], "admin"),
        )

    @pytest.mark.asyncio
    async def test_prefer_items_overwrites_version(
        self, async_client, db_session, mig_env
    ):
        r = await self._resolve(async_client, mig_env, mig_env["conflict"], "items")

        assert r.status_code == 200, r.text
        version = await estimate_store.get_working_version(
            db_session, mig_env["conflict"])
        items = estimate_store.rows_to_items(version.rows)
        assert items[0]["work_price"] == 1000.0

    @pytest.mark.asyncio
    async def test_prefer_version_keeps_editor_rows(
        self, async_client, db_session, mig_env
    ):
        r = await self._resolve(async_client, mig_env, mig_env["conflict"], "version")

        assert r.status_code == 200
        version = await estimate_store.get_working_version(
            db_session, mig_env["conflict"])
        items = estimate_store.rows_to_items(version.rows)
        assert items[0]["work_price"] == 777.0

    @pytest.mark.asyncio
    async def test_both_sides_saved_to_history(
        self, async_client, db_session, mig_env
    ):
        """Единственный способ вернуться назад — снимок обеих сторон."""
        await self._resolve(async_client, mig_env, mig_env["conflict"], "items")

        entries = (await db_session.execute(
            select(TaskHistory).where(
                TaskHistory.task_id == mig_env["conflict"],
                TaskHistory.operation_type == "estimate_migration",
            )
        )).scalars().all()
        assert len(entries) == 1
        saved = entries[0].previous_value
        assert saved["rows"] and saved["items"]

    @pytest.mark.asyncio
    async def test_resolve_touches_only_named_estimate(
        self, async_client, db_session, mig_env
    ):
        await self._resolve(async_client, mig_env, mig_env["conflict"], "items")

        # Соседняя смета без версии осталась без версии: её не задели.
        assert await estimate_store.get_working_version(
            db_session, mig_env["no_version"]) is None

    @pytest.mark.asyncio
    async def test_unknown_estimate_gives_404(self, async_client, mig_env):
        r = await self._resolve(
            async_client, mig_env, "11111111-1111-1111-1111-111111111111", "items")

        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Права
# ---------------------------------------------------------------------------

class TestPermissions:
    @pytest.mark.asyncio
    async def test_manager_cannot_read_report(self, async_client, mig_env):
        r = await _report(async_client, mig_env, user="manager")

        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_manager_cannot_apply(self, async_client, mig_env):
        r = await async_client.post(
            "/admin/estimates/migration/apply",
            json={"exclude": []},
            headers=_auth(mig_env["manager"], "project_manager"),
        )

        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Расхождение объяснено словами (Фаза 3)
# ---------------------------------------------------------------------------
#
# На боевых данных нашлось девять расхождений, и у шести итоги совпали до рубля,
# а «расходится позиций» показывало сотни. По такому отчёту решение принять
# нельзя: непонятно, изменились цифры или строки просто переставлены. Цена
# ошибки — стёртые правки человека.


def _analyze(items, version_items):
    from app.services.estimate_migration import describe_diff
    return describe_diff(items, version_items)


class TestDiffExplained:
    def test_reordered_rows_are_order_only(self):
        """Строки переставлены местами: состав тот же, деньги те же."""
        a = _items()
        b = list(reversed(_items()))

        d = _analyze(a, b)

        assert d["only_order"] is True
        assert d["same_totals"] is True

    def test_changed_price_is_not_order_only(self):
        a = _items(work_price=1000.0)
        b = _items(work_price=777.0)

        d = _analyze(a, b)

        assert d["only_order"] is False
        assert d["same_totals"] is False

    def test_sample_shows_both_values(self):
        """Человеку нужно увидеть, что именно разошлось."""
        a = _items(work_price=1000.0)
        b = _items(work_price=777.0)

        d = _analyze(a, b)

        assert d["samples"], "пример различия обязателен"
        first = d["samples"][0]
        assert "Кладка стен" in first["name"]
        assert "1000" in first["items"] or "1 000" in first["items"]
        assert "777" in first["version"]

    def test_row_counts_are_reported(self):
        a = _items() + [{"type": "Работа", "name": "Штукатурка", "unit": "м2",
                         "quantity": 10, "work_price": 500.0, "material_price": None}]
        b = _items()

        d = _analyze(a, b)

        assert d["items_rows"] == 3
        assert d["version_rows"] == 2
        assert d["only_order"] is False

    def test_samples_are_capped(self):
        """Список примеров не должен превращаться в простыню."""
        a = [{"type": "Работа", "name": f"Работа {i}", "unit": "м2",
              "quantity": 1, "work_price": 100.0, "material_price": None}
             for i in range(20)]
        b = [{**row, "work_price": 200.0} for row in a]

        d = _analyze(a, b)

        assert len(d["samples"]) <= 3

    def test_equal_estimates_have_no_diff(self):
        d = _analyze(_items(), _items())

        assert d["only_order"] is True
        assert d["samples"] == []

    @pytest.mark.asyncio
    async def test_report_explains_conflict(self, async_client, mig_env):
        """Отчёт по API отдаёт разбор, а не только число расхождений."""
        body = (await _report(async_client, mig_env)).json()

        entry = _by_id(body, mig_env["conflict"])
        assert entry["only_order"] is False
        assert entry["same_totals"] is False
        assert entry["items_rows"] == 2
        assert entry["version_rows"] == 2
        assert entry["samples"]
