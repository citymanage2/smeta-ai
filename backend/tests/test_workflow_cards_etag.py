"""ETag на GET /api/projects/{id}/workflow-cards: 304, пока данные не менялись.

Список карточек поллится каждые 5 секунд. Неизменный список отдаётся пустым 304,
но любая правка карточки обязана дойти до экрана: тот же ETag после правки —
и доска показывала бы устаревшее, пока человек не обновит страницу.
"""
import uuid
import pytest

from app.models.project import Project
from app.models.workflow_card import WorkflowCard  # noqa: F401 — регистрирует таблицу в Base.metadata

pytestmark = pytest.mark.asyncio


async def test_workflow_cards_etag_304(async_client, db_session, admin_token):
    pid = str(uuid.uuid4())
    db_session.add(Project(id=pid, name="ETag Test"))
    await db_session.commit()
    auth = {"Authorization": admin_token}
    created = await async_client.post(
        f"/api/projects/{pid}/workflow-cards", json={"name": "АР"}, headers=auth
    )
    assert created.status_code == 201
    card_id = created.json()["id"]

    url = f"/api/projects/{pid}/workflow-cards"
    r1 = await async_client.get(url, headers=auth)
    assert r1.status_code == 200
    etag = r1.headers.get("etag")
    assert etag, "ETag header must be set"

    # Повторный запрос с тем же ETag — данные не менялись → 304 без тела.
    r2 = await async_client.get(url, headers={**auth, "If-None-Match": etag})
    assert r2.status_code == 304
    assert r2.headers.get("etag") == etag

    # Карточку переименовали — старый ETag больше не совпадает: новый список.
    renamed = await async_client.patch(
        f"/api/workflow-cards/{card_id}", json={"name": "АР, ред. 2"}, headers=auth
    )
    assert renamed.status_code == 200
    r3 = await async_client.get(url, headers={**auth, "If-None-Match": etag})
    assert r3.status_code == 200
    assert r3.headers.get("etag") not in (None, etag)
    assert [c["name"] for c in r3.json()] == ["АР, ред. 2"]
