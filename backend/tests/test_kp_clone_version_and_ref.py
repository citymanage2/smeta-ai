"""Фундамент фазы 8 плана `plans/2026-09-14-zapros-kp.md` (подзадача 8а).

* `estimate_versions_service.clone_version` — клонирование версии без
  `commit`: применение цен из КП создаёт версию «Цены из КП» в той же
  транзакции, что и сверку ревизии, поэтому коммитить внутри нельзя.
  Ручная «Зафиксировать версию» идёт через него же, ответ роута прежний.
* `kp_ref` — ссылка строки на КП — едет полем строки (`PASSTHROUGH_FIELDS`),
  но в промпты не уходит (проблема 34).
"""
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.estimate_version import EstimateVersion
from app.models.history import TaskHistory
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.utils.auth import create_access_token, hash_password
from app.utils.estimate_rows import (
    PASSTHROUGH_FIELDS,
    item_to_row,
    row_to_item,
    without_prompt_fields,
)

_KP_REF = {
    "request_id": "req-1", "offer_id": "off-1", "supplier": "ООО Ромашка",
    "offer_date": "2026-09-10", "offers_count": 2, "includes_materials": False,
}


def _rows() -> list:
    return [
        {"id": "r1", "lineage_id": "r1", "num": 1, "type": "work", "name": "Кладка",
         "unit": "м2", "qty": 4, "price_work": 1000, "price_material": None,
         "cost": 4000, "selected": False, "source_no": "12", "kp_ref": dict(_KP_REF)},
        {"id": "r2", "lineage_id": "r2", "num": 2, "type": "material", "name": "Кирпич",
         "unit": "шт", "qty": 10, "price_work": None, "price_material": 500,
         "cost": 5000, "selected": False},
    ]


# ---------------------------------------------------------------------------
# kp_ref: едет полем строки, но не в промпт
# ---------------------------------------------------------------------------

def test_kp_ref_is_passthrough_field():
    assert "kp_ref" in PASSTHROUGH_FIELDS
    item = row_to_item(_rows()[0])
    assert item["kp_ref"] == _KP_REF
    assert item_to_row(item, num=1)["kp_ref"] == _KP_REF


def test_prompt_view_drops_kp_ref_and_source_no_without_touching_rows():
    rows = _rows()
    view = without_prompt_fields(rows)

    assert all("kp_ref" not in r and "source_no" not in r for r in view)
    assert view[0]["name"] == "Кладка" and view[0]["id"] == "r1"
    # Исходные строки не тронуты: вырезается копия
    assert rows[0]["kp_ref"] == _KP_REF and rows[0]["source_no"] == "12"


def test_task_processor_prompt_helper_drops_kp_ref():
    from app.services.task_processor import _without_source_no

    view = _without_source_no([row_to_item(_rows()[0])])
    assert "kp_ref" not in view[0] and "source_no" not in view[0]


# ---------------------------------------------------------------------------
# clone_version
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def clone_env(db_session):
    for model in (EstimateVersion, TaskHistory, Task, Project, User):
        await db_session.execute(model.__table__.delete())
    await db_session.commit()

    pm = User(username="pm_clone", role="project_manager", full_name="Иванов Иван",
              password_hash=hash_password("p1"))
    db_session.add(pm)
    await db_session.flush()
    project = Project(name="Объект", owner_id=pm.id)
    db_session.add(project)
    await db_session.flush()
    task = Task(
        owner_id=pm.id, user_role="project_manager", task_type="ESTIMATE_OPTIMIZATION",
        status="completed", input_files=[], input_file_data=[], chat_history=[],
        project_id=str(project.id),
    )
    db_session.add(task)
    await db_session.flush()
    source = EstimateVersion(
        task_id=str(task.id), version_number=3, version_label="technology",
        version_display_name="Технологии", rows=_rows(), file_slot="result",
        task_type="ESTIMATE_OPTIMIZATION", overhead_pct=7, transport_pct=2,
        contingency_pct=1, expenses_overridden=True,
        coefficient={"work": 1.05, "material": 1.0, "scope": "all"},
        draft_rows=[{"id": "draft"}], rev=5,
    )
    db_session.add(source)
    await db_session.commit()

    yield {"pm": pm.id, "task_id": str(task.id), "source_id": str(source.id)}

    for model in (EstimateVersion, TaskHistory, Task, Project, User):
        await db_session.execute(model.__table__.delete())
    await db_session.commit()


@pytest.mark.asyncio
async def test_clone_version_copies_content_and_does_not_commit(db_session, clone_env):
    from app.services.estimate_versions_service import clone_version

    source = await db_session.get(EstimateVersion, clone_env["source_id"])
    clone = await clone_version(db_session, source, "Цены из КП")

    assert clone.id != source.id
    assert clone.task_id == source.task_id
    assert clone.version_number == 4
    assert clone.version_label == "custom"
    assert clone.version_display_name == "Цены из КП"
    assert clone.rows == _rows()
    assert clone.rows is not source.rows
    assert clone.overhead_pct == 7 and clone.transport_pct == 2
    assert clone.contingency_pct == 1 and clone.expenses_overridden is True
    assert clone.coefficient == {"work": 1.05, "material": 1.0, "scope": "all"}
    assert clone.task_type == "ESTIMATE_OPTIMIZATION"
    assert clone.file_slot == "result"
    # Черновик, ревизия и откат — состояние исходной версии, а не содержимое
    assert clone.draft_rows is None
    assert not clone.rev
    assert not clone.is_rolled_back

    # Правка строк клона не меняет исходную версию
    clone.rows[0]["price_work"] = 1
    assert source.rows[0]["price_work"] == 1000

    # Коммита внутри нет: откат транзакции убирает клон
    await db_session.rollback()
    db_session.expire_all()
    left = (await db_session.execute(
        select(EstimateVersion).where(EstimateVersion.task_id == clone_env["task_id"])
    )).scalars().all()
    assert [v.version_number for v in left] == [3]


@pytest.mark.asyncio
async def test_create_manual_version_route_response_unchanged(
    async_client, db_session, clone_env,
):
    headers = {"Authorization": f"Bearer {create_access_token(clone_env['pm'], 'project_manager', 'pm_clone')}"}
    resp = await async_client.post(
        f"/tasks/{clone_env['task_id']}/estimate/versions",
        json={"source_version_id": clone_env["source_id"], "version_display_name": "Снимок"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {
        "id", "task_id", "version_number", "version_label", "version_display_name",
        "rows", "overhead_pct", "transport_pct", "contingency_pct",
        "expenses_overridden", "optimization_proposals", "is_rolled_back", "created_at",
    }
    assert body["version_number"] == 4
    assert body["version_label"] == "custom"
    assert body["version_display_name"] == "Снимок"
    assert [r["id"] for r in body["rows"]] == ["r1", "r2"]
    assert float(body["overhead_pct"]) == 7 and body["expenses_overridden"] is True
    assert body["is_rolled_back"] is False

    db_session.expire_all()
    saved = await db_session.get(EstimateVersion, body["id"])
    assert saved is not None
    assert saved.file_slot == "result"
    assert saved.task_type == "ESTIMATE_OPTIMIZATION"
    assert saved.coefficient == {"work": 1.05, "material": 1.0, "scope": "all"}


@pytest.mark.asyncio
async def test_optimize_custom_prompt_has_no_kp_ref(
    async_client, db_session, clone_env, monkeypatch,
):
    """Строки версии оптимизации уходят в промпт «Предложения» без kp_ref и source_no."""
    import app.services.claude_service as claude_service

    captured: list = []

    async def fake_call_claude(*, messages, **kwargs):
        captured.append(messages[0]["content"])
        return '{"proposals": []}'

    monkeypatch.setattr(claude_service, "call_claude", fake_call_claude)
    headers = {"Authorization": f"Bearer {create_access_token(clone_env['pm'], 'project_manager', 'pm_clone')}"}
    resp = await async_client.post(
        f"/tasks/{clone_env['task_id']}/estimate/optimize/custom",
        json={"version_id": clone_env["source_id"], "row_ids": ["r1"]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert len(captured) == 1
    prompt = captured[0]
    assert "Кладка" in prompt
    assert "kp_ref" not in prompt and "ООО Ромашка" not in prompt
    assert "source_no" not in prompt
