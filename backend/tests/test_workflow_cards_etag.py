"""ETag на GET /api/projects/{id}/workflow-cards: 304 при неизменных данных."""
import uuid
import pytest

from app.models.project import Project
from app.models.workflow_card import WorkflowCard  # noqa: F401 — регистрирует таблицу в Base.metadata

pytestmark = pytest.mark.asyncio


async def test_workflow_cards_etag_304(async_client, db_session, admin_token):
    pid = str(uuid.uuid4())
    db_session.add(Project(id=pid, name="ETag Test"))
    await db_session.commit()

    url = f"/api/projects/{pid}/workflow-cards"
    r1 = await async_client.get(url, headers={"Authorization": admin_token})
    assert r1.status_code == 200
    etag = r1.headers.get("etag")
    assert etag, "ETag header must be set"
    assert r1.headers.get("cache-control") == "private, max-age=5"

    # Повторный запрос с тем же ETag — данные не менялись → 304 без тела.
    r2 = await async_client.get(
        url, headers={"Authorization": admin_token, "If-None-Match": etag}
    )
    assert r2.status_code == 304
    assert r2.headers.get("etag") == etag
