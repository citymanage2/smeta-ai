"""Разделы сводной как документ единого редактора (kind `summary-section`).

Фаза 7 плана `plans/2026-08-02-edinyy-redaktor-tablic.md`.

Раздел сводной — это снимок строк сметы карточки внутри `summary_estimates`.
Он не версия и не задача: у него нет вкладок версий, он не зависит от того, идёт
ли сейчас расчёт сметы, и правится он независимо от исходной сметы.

Проверяем ровно это:
  * раздел открывается тем же API, что перечень, смета и оптимизация;
  * строки берутся и пишутся в `summary_estimates.sections` — второго хранилища
    нет (правило Фазы 5);
  * правка раздела не трогает исходную версию сметы;
  * черновик, `rev`, история и откат работают так же, как у остальных типов;
  * право на правку определяется проектом (сводная — артефакт проекта);
  * старый `PUT /projects/{id}/summary` больше не может затереть строки разделов.
"""
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.document_lock import DocumentLock
from app.models.estimate_version import EstimateVersion
from app.models.history import TaskHistory
from app.models.project import Project
from app.models.summary_estimate import SummaryEstimate
from app.models.summary_section_doc import SummarySectionDoc
from app.models.task import Task
from app.models.user import User
from app.models.workflow_card import WorkflowCard
from app.utils.auth import create_access_token, hash_password


def _auth(user_id: int, role: str, username: str = None) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id, role, username)}"}


def _estimate_rows(price_work: int = 1000) -> list:
    return [
        {
            "id": "row-1", "lineage_id": "row-1", "num": 1, "type": "work",
            "name": "Демонтаж перегородок", "unit": "м2", "qty": 10,
            "price_work": price_work, "price_material": None, "cost": price_work * 10,
            "selected": False,
        },
        {
            "id": "row-2", "lineage_id": "row-2", "num": 2, "type": "material",
            "name": "Гипсокартон", "unit": "лист", "qty": 20,
            "price_work": None, "price_material": 500, "cost": 10000,
            "selected": False,
        },
    ]


@pytest_asyncio.fixture
async def summary_env(db_session, fake_s3):
    """Проект pm1 → карточка со сметой → сводная с одним разделом.

    Строки раздела намеренно отличаются от строк исходной версии сметы: раздел —
    снимок, и тесты должны видеть, из какого именно хранилища пришли строки.
    """
    for model in (DocumentLock, SummarySectionDoc, SummaryEstimate, EstimateVersion,
                  TaskHistory, WorkflowCard, Task, Project, User):
        await db_session.execute(model.__table__.delete())
    await db_session.commit()

    pm1 = User(username="pm1", role="project_manager", full_name="Иванов Иван",
               password_hash=hash_password("p1"))
    pm2 = User(username="pm2", role="project_manager", full_name="Петров Пётр",
               password_hash=hash_password("p2"))
    head = User(username="head", role="head_of_sales", full_name="Руководитель",
                password_hash=hash_password("p3"))
    db_session.add_all([pm1, pm2, head])
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

    version = EstimateVersion(
        task_id=str(task.id), version_number=0, version_label="original",
        version_display_name="Исходная смета", rows=_estimate_rows(1000),
        file_slot="estimate", task_type="ESTIMATE_FROM_LIST",
    )
    db_session.add(version)
    await db_session.flush()

    card = WorkflowCard(project_id=str(project.id), name="АР", stage="estimate",
                        estimate_task_id=str(task.id))
    db_session.add(card)
    await db_session.flush()

    summary = SummaryEstimate(
        project_id=str(project.id),
        sections=[{
            "card_id": str(card.id),
            "card_name": "АР",
            "version_id": str(version.id),
            "version_display_name": "Исходная смета",
            # Снимок: цена работ уже правилась в сводной и отличается от версии.
            "rows": _estimate_rows(1500),
        }],
        overrides={},
    )
    db_session.add(summary)
    await db_session.commit()

    env = {
        "pm1": pm1.id, "pm2": pm2.id, "head": head.id,
        "project_id": str(project.id), "card_id": str(card.id),
        "task_id": str(task.id), "version_id": str(version.id),
        "summary_id": str(summary.id),
    }
    yield env

    for model in (DocumentLock, SummarySectionDoc, SummaryEstimate, EstimateVersion,
                  TaskHistory, WorkflowCard, Task, Project, User):
        await db_session.execute(model.__table__.delete())
    await db_session.commit()


def _url(env: dict, suffix: str = "") -> str:
    return f"/documents/{env['card_id']}/summary-section{suffix}"


async def _reload_summary(db_session, env: dict) -> SummaryEstimate:
    """Перечитать сводную из БД, минуя кэш сессии."""
    db_session.expire_all()
    res = await db_session.execute(
        select(SummaryEstimate).where(SummaryEstimate.project_id == env["project_id"])
    )
    return res.scalar_one()


# ---------------------------------------------------------------------------
# Открытие
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_section_opens_as_document(async_client, summary_env):
    """Раздел сводной — такой же документ, как смета: тот же адрес, тот же контракт."""
    resp = await async_client.get(
        _url(summary_env), headers=_auth(summary_env["pm1"], "project_manager"))

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["kind"] == "summary-section"
    # Строки раздела — типизированные строки сметы, значит адаптер тот же.
    assert data["row_format"] == "estimate"
    assert data["can_write"] is True
    assert data["readonly_reason"] is None
    # Вкладок версий у раздела нет: снимок один.
    assert data["versions"] == []


@pytest.mark.asyncio
async def test_section_rows_come_from_summary_snapshot(async_client, summary_env):
    """Строки берутся из сводной, а не из исходной версии сметы."""
    resp = await async_client.get(
        _url(summary_env, "/rows"), headers=_auth(summary_env["pm1"], "project_manager"))

    assert resp.status_code == 200, resp.text
    rows = resp.json()["rows"]
    assert len(rows) == 2
    assert rows[0]["price_work"] == 1500  # снимок сводной, а не 1000 из версии


@pytest.mark.asyncio
async def test_card_without_section_is_not_found(async_client, db_session, summary_env):
    """Карточка, которой нет среди разделов сводной, документом не открывается."""
    other = WorkflowCard(project_id=summary_env["project_id"], name="ОВ", stage="estimate",
                         estimate_task_id=summary_env["task_id"])
    db_session.add(other)
    await db_session.commit()

    resp = await async_client.get(
        f"/documents/{other.id}/summary-section",
        headers=_auth(summary_env["pm1"], "project_manager"))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Черновик и применение
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_draft_does_not_touch_summary(async_client, db_session, summary_env):
    """Черновик живёт отдельно: сводная до «Применить» не меняется."""
    edited = _estimate_rows(1500)
    edited[0]["price_work"] = 9999

    resp = await async_client.put(
        _url(summary_env, "/draft"), json={"rows": edited},
        headers=_auth(summary_env["pm1"], "project_manager"))
    assert resp.status_code == 200, resp.text

    summary = await _reload_summary(db_session, summary_env)
    assert summary.sections[0]["rows"][0]["price_work"] == 1500

    rows_resp = await async_client.get(
        _url(summary_env, "/rows"), headers=_auth(summary_env["pm1"], "project_manager"))
    assert rows_resp.json()["draft_rows"][0]["price_work"] == 9999


@pytest.mark.asyncio
async def test_apply_writes_rows_into_summary(async_client, db_session, summary_env):
    """«Применить» пишет строки в сводную, двигает rev и оставляет запись в истории."""
    edited = _estimate_rows(1500)
    edited[0]["price_work"] = 2500

    resp = await async_client.post(
        _url(summary_env, "/apply"), json={"rev": 0, "rows": edited},
        headers=_auth(summary_env["pm1"], "project_manager", "pm1"))
    assert resp.status_code == 200, resp.text
    assert resp.json()["rev"] == 1

    summary = await _reload_summary(db_session, summary_env)
    assert summary.sections[0]["rows"][0]["price_work"] == 2500
    # Имя раздела и ссылка на версию не теряются при записи строк.
    assert summary.sections[0]["card_name"] == "АР"
    assert summary.sections[0]["version_id"] == summary_env["version_id"]

    res = await db_session.execute(
        select(TaskHistory).where(TaskHistory.document_kind == "summary-section"))
    entries = list(res.scalars().all())
    assert len(entries) == 1
    assert entries[0].user_name == "Иванов Иван"


@pytest.mark.asyncio
async def test_apply_does_not_touch_source_estimate(async_client, db_session, summary_env):
    """Правка раздела не меняет исходную смету — снимок на то и снимок."""
    edited = _estimate_rows(1500)
    edited[0]["price_work"] = 2500

    await async_client.post(
        _url(summary_env, "/apply"), json={"rev": 0, "rows": edited},
        headers=_auth(summary_env["pm1"], "project_manager"))

    db_session.expire_all()
    version = await db_session.get(EstimateVersion, summary_env["version_id"])
    assert version.rows[0]["price_work"] == 1000


@pytest.mark.asyncio
async def test_apply_with_stale_rev_returns_409(async_client, summary_env):
    """Второе «Применить» со старым rev отклоняется, а не затирает чужие правки."""
    edited = _estimate_rows(1500)
    edited[0]["price_work"] = 2500
    first = await async_client.post(
        _url(summary_env, "/apply"), json={"rev": 0, "rows": edited},
        headers=_auth(summary_env["pm1"], "project_manager"))
    assert first.status_code == 200

    edited[0]["price_work"] = 3300
    second = await async_client.post(
        _url(summary_env, "/apply"), json={"rev": 0, "rows": edited},
        headers=_auth(summary_env["head"], "head_of_sales"))
    assert second.status_code == 409
    assert "Иванов Иван" in second.json()["detail"]


@pytest.mark.asyncio
async def test_revert_restores_previous_section_rows(async_client, db_session, summary_env):
    """Откат возвращает раздел к состоянию до правки."""
    edited = _estimate_rows(1500)
    edited[0]["price_work"] = 2500
    await async_client.post(
        _url(summary_env, "/apply"), json={"rev": 0, "rows": edited},
        headers=_auth(summary_env["pm1"], "project_manager"))

    history = await async_client.get(
        _url(summary_env, "/history"), headers=_auth(summary_env["pm1"], "project_manager"))
    entry_id = history.json()[0]["id"]

    resp = await async_client.post(
        _url(summary_env, f"/history/{entry_id}/revert"),
        headers=_auth(summary_env["pm1"], "project_manager"))
    assert resp.status_code == 200, resp.text

    summary = await _reload_summary(db_session, summary_env)
    assert summary.sections[0]["rows"][0]["price_work"] == 1500


@pytest.mark.asyncio
async def test_section_history_is_separate_from_estimate(async_client, summary_env):
    """История раздела не смешивается с историей сметы той же карточки."""
    edited = _estimate_rows(1500)
    edited[0]["price_work"] = 2500
    await async_client.post(
        _url(summary_env, "/apply"), json={"rev": 0, "rows": edited},
        headers=_auth(summary_env["pm1"], "project_manager"))

    section_history = await async_client.get(
        _url(summary_env, "/history"), headers=_auth(summary_env["pm1"], "project_manager"))
    estimate_history = await async_client.get(
        f"/documents/{summary_env['card_id']}/estimate/history",
        headers=_auth(summary_env["pm1"], "project_manager"))

    assert len(section_history.json()) == 1
    assert estimate_history.json() == []


# ---------------------------------------------------------------------------
# Права и режимы
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_foreign_project_section_not_accessible(async_client, summary_env):
    """Менеджер не открывает разделы чужого проекта."""
    resp = await async_client.get(
        _url(summary_env), headers=_auth(summary_env["pm2"], "project_manager"))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_head_of_sales_can_edit_foreign_section(async_client, db_session, summary_env):
    """Руководитель отдела продаж правит разделы любого проекта."""
    edited = _estimate_rows(1500)
    edited[0]["price_work"] = 7000

    resp = await async_client.post(
        _url(summary_env, "/apply"), json={"rev": 0, "rows": edited},
        headers=_auth(summary_env["head"], "head_of_sales"))
    assert resp.status_code == 200, resp.text

    summary = await _reload_summary(db_session, summary_env)
    assert summary.sections[0]["rows"][0]["price_work"] == 7000


@pytest.mark.asyncio
async def test_section_editable_while_estimate_task_processing(
    async_client, db_session, summary_env
):
    """Идущий пересчёт сметы не запирает раздел: раздел — снимок, а не задача."""
    task = await db_session.get(Task, summary_env["task_id"])
    task.status = "processing"
    await db_session.commit()

    resp = await async_client.get(
        _url(summary_env), headers=_auth(summary_env["pm1"], "project_manager"))
    assert resp.status_code == 200
    assert resp.json()["can_write"] is True


# ---------------------------------------------------------------------------
# Старый путь сохранения сводной
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_legacy_summary_put_cannot_overwrite_section_rows(
    async_client, db_session, summary_env
):
    """`PUT /summary` сохраняет настройки бланка, но строки разделов не трогает.

    Иначе у строк раздела было бы два писателя: редактор и страница сводной, —
    и они разошлись бы ровно так же, как расходилась смета до Фазы 5.
    """
    edited = _estimate_rows(1500)
    edited[0]["price_work"] = 4200
    await async_client.post(
        _url(summary_env, "/apply"), json={"rev": 0, "rows": edited},
        headers=_auth(summary_env["pm1"], "project_manager"))

    # Страница сводной присылает свой (устаревший) снимок строк и новый налог.
    stale_sections = [{
        "card_id": summary_env["card_id"],
        "card_name": "АР",
        "version_id": summary_env["version_id"],
        "version_display_name": "Исходная смета",
        "rows": _estimate_rows(1500),
        "tax_pct": 5,
    }]
    resp = await async_client.put(
        f"/api/projects/{summary_env['project_id']}/summary",
        json={"sections": stale_sections, "total_for_customer": "123.45"},
        headers=_auth(summary_env["pm1"], "project_manager"))
    assert resp.status_code == 200, resp.text

    summary = await _reload_summary(db_session, summary_env)
    # Строки — из документа, налог раздела — из присланного бланка.
    assert summary.sections[0]["rows"][0]["price_work"] == 4200
    assert summary.sections[0]["tax_pct"] == 5
    assert float(summary.total_for_customer) == pytest.approx(123.45)


@pytest.mark.asyncio
async def test_legacy_summary_put_can_drop_and_add_sections(
    async_client, db_session, summary_env
):
    """Список разделов остаётся управляемым: убранный раздел исчезает из сводной."""
    resp = await async_client.put(
        f"/api/projects/{summary_env['project_id']}/summary",
        json={"sections": []},
        headers=_auth(summary_env["pm1"], "project_manager"))
    assert resp.status_code == 200, resp.text

    summary = await _reload_summary(db_session, summary_env)
    assert summary.sections == []
