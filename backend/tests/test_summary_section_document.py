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
async def test_apply_writes_into_source_estimate(async_client, db_session, summary_env):
    """Правка раздела меняет саму смету.

    Раньше раздел был отдельной копией: человек правил сводную неделю, а смета
    оставалась прежней, и при пересборке разделов работа исчезала. Теперь
    сводная и смета — одно и то же (план 2026-08-04).
    """
    edited = _estimate_rows(1500)
    edited[0]["price_work"] = 2500

    await async_client.post(
        _url(summary_env, "/apply"), json={"rev": 0, "rows": edited},
        headers=_auth(summary_env["pm1"], "project_manager"))

    db_session.expire_all()
    version = await db_session.get(EstimateVersion, summary_env["version_id"])
    assert version.rows[0]["price_work"] == 2500


@pytest.mark.asyncio
async def test_estimate_edit_reaches_the_section(async_client, db_session, summary_env):
    """Правка сметы видна в разделе сводной без пересборки."""
    edited = _estimate_rows(1000)
    edited[0]["price_work"] = 777

    resp = await async_client.post(
        f"/documents/{summary_env['card_id']}/estimate/apply",
        json={"rev": 0, "rows": edited},
        headers=_auth(summary_env["pm1"], "project_manager"))
    assert resp.status_code == 200, resp.text

    summary = await _reload_summary(db_session, summary_env)
    assert summary.sections[0]["rows"][0]["price_work"] == 777

    rows_resp = await async_client.get(
        _url(summary_env, "/rows"), headers=_auth(summary_env["pm1"], "project_manager"))
    assert rows_resp.json()["rows"][0]["price_work"] == 777


@pytest.mark.asyncio
async def test_section_from_older_version_moves_to_the_working_one(
    async_client, db_session, summary_env
):
    """Раздел, собранный из прежней версии, при правке переезжает на рабочую.

    Решение пользователя: правка сводной уходит в смету всегда. Значит и ссылка
    раздела должна указывать туда, где строки теперь лежат, — иначе следующая
    смена состава собрала бы раздел из устаревшей версии.
    """
    # Рабочая версия сметы — первая непокатанная по номеру, то есть та, что уже
    # есть в фикстуре. Раздел же соберём из более поздней, отдельной версии.
    older = EstimateVersion(
        task_id=summary_env["task_id"], version_number=1, version_label="custom",
        version_display_name="Прежний вариант", rows=_estimate_rows(1100),
        file_slot="estimate", task_type="ESTIMATE_FROM_LIST",
    )
    db_session.add(older)
    await db_session.flush()
    older_id = str(older.id)

    summary = await _reload_summary(db_session, summary_env)
    summary.sections = [{**summary.sections[0], "version_id": older_id}]
    await db_session.commit()
    working_id = summary_env["version_id"]

    edited = _estimate_rows(1500)
    edited[0]["price_work"] = 2500
    resp = await async_client.post(
        _url(summary_env, "/apply"), json={"rev": 0, "rows": edited},
        headers=_auth(summary_env["pm1"], "project_manager"))
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    fresh = await db_session.get(EstimateVersion, working_id)
    assert fresh.rows[0]["price_work"] == 2500, "правка не дошла до рабочей версии"

    summary = await _reload_summary(db_session, summary_env)
    assert summary.sections[0]["version_id"] == working_id


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
async def test_colleague_opens_section_of_other_project(async_client, summary_env):
    """Проекты общие: раздел сводной открывает любой сотрудник."""
    resp = await async_client.get(
        _url(summary_env), headers=_auth(summary_env["pm2"], "project_manager"))
    assert resp.status_code == 200, resp.text
    assert resp.json()["can_write"] is True


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
async def test_section_readonly_while_estimate_task_processing(
    async_client, db_session, summary_env
):
    """Пока смета считается, раздел открыт только на чтение.

    Раньше раздел был снимком и от расчёта не зависел. Теперь правка раздела
    пишется в саму смету — а расчёт, закончившись, перезапишет строки целиком:
    работа человека исчезла бы без следа.
    """
    task = await db_session.get(Task, summary_env["task_id"])
    task.status = "processing"
    await db_session.commit()

    resp = await async_client.get(
        _url(summary_env), headers=_auth(summary_env["pm1"], "project_manager"))
    assert resp.status_code == 200
    assert resp.json()["can_write"] is False
    assert resp.json()["readonly_reason"] == "task_processing"

    edited = _estimate_rows(1500)
    edited[0]["price_work"] = 2500
    apply_resp = await async_client.post(
        _url(summary_env, "/apply"), json={"rev": 0, "rows": edited},
        headers=_auth(summary_env["pm1"], "project_manager"))
    assert apply_resp.status_code == 409


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


# ---------------------------------------------------------------------------
# Смена состава разделов не теряет правки (план 2026-08-04, Фаза 1)
# ---------------------------------------------------------------------------
#
# «Изменить разделы» удаляла сводную целиком и собирала разделы заново из смет.
# Человек правил разделы неделю, выгрузил файл — а после смены состава всё
# вернулось к тому, «как посчиталось». Предупреждения не было: кнопка выглядит
# как «поменять состав».


async def _second_card(db_session, env: dict) -> dict:
    """Вторая карточка со сметой — чтобы менять состав разделов было чем."""
    task = Task(
        owner_id=env["pm1"], user_role="project_manager",
        task_type="ESTIMATE_FROM_LIST", status="completed",
        input_files=[], input_file_data=[], chat_history=[],
        project_id=env["project_id"],
    )
    db_session.add(task)
    await db_session.flush()

    version = EstimateVersion(
        task_id=str(task.id), version_number=0, version_label="original",
        version_display_name="Смета ВК", rows=_estimate_rows(700),
        file_slot="estimate", task_type="ESTIMATE_FROM_LIST",
    )
    db_session.add(version)
    await db_session.flush()

    card = WorkflowCard(project_id=env["project_id"], name="ВК", stage="estimate",
                        estimate_task_id=str(task.id))
    db_session.add(card)
    await db_session.flush()
    await db_session.commit()
    return {"card_id": str(card.id), "version_id": str(version.id)}


async def _change_sections(async_client, env: dict, sections: list):
    return await async_client.post(
        f"/api/projects/{env['project_id']}/summary",
        json={"sections": sections},
        headers=_auth(env["pm1"], "project_manager"))


def _section_input(env: dict) -> dict:
    return {"card_id": env["card_id"], "version_id": env["version_id"]}


@pytest.mark.asyncio
async def test_adding_section_keeps_rows_of_existing_ones(
    async_client, db_session, summary_env
):
    """Добавили раздел — правки в прежних остались на месте."""
    edited = _estimate_rows(1500)
    edited[0]["price_work"] = 4200
    await async_client.post(
        _url(summary_env, "/apply"), json={"rev": 0, "rows": edited},
        headers=_auth(summary_env["pm1"], "project_manager"))

    second = await _second_card(db_session, summary_env)
    resp = await _change_sections(
        async_client, summary_env, [_section_input(summary_env), _section_input(second)])

    assert resp.status_code in (200, 201), resp.text
    summary = await _reload_summary(db_session, summary_env)
    kept = next(s for s in summary.sections if s["card_id"] == summary_env["card_id"])
    assert kept["rows"][0]["price_work"] == 4200, "правка раздела пропала"
    assert len(summary.sections) == 2


@pytest.mark.asyncio
async def test_removing_section_keeps_the_others(
    async_client, db_session, summary_env
):
    """Убрали один раздел — остальные не тронуты."""
    edited = _estimate_rows(1500)
    edited[0]["price_work"] = 4200
    await async_client.post(
        _url(summary_env, "/apply"), json={"rev": 0, "rows": edited},
        headers=_auth(summary_env["pm1"], "project_manager"))

    second = await _second_card(db_session, summary_env)
    await _change_sections(
        async_client, summary_env, [_section_input(summary_env), _section_input(second)])

    resp = await _change_sections(async_client, summary_env, [_section_input(summary_env)])

    assert resp.status_code in (200, 201), resp.text
    summary = await _reload_summary(db_session, summary_env)
    assert [s["card_id"] for s in summary.sections] == [summary_env["card_id"]]
    assert summary.sections[0]["rows"][0]["price_work"] == 4200


@pytest.mark.asyncio
async def test_changing_sections_keeps_draft_and_rev(
    async_client, db_session, summary_env
):
    """Черновик и счётчик правок переживают смену состава.

    Иначе человек, вернувшись к разделу, потерял бы несохранённую работу, а
    открытый рядом редактор получил бы отказ на ровном месте.
    """
    applied = _estimate_rows(1500)
    applied[0]["price_work"] = 4200
    await async_client.post(
        _url(summary_env, "/apply"), json={"rev": 0, "rows": applied},
        headers=_auth(summary_env["pm1"], "project_manager"))
    draft = _estimate_rows(1900)
    await async_client.put(
        _url(summary_env, "/draft"), json={"rows": draft},
        headers=_auth(summary_env["pm1"], "project_manager"))

    second = await _second_card(db_session, summary_env)
    await _change_sections(
        async_client, summary_env, [_section_input(summary_env), _section_input(second)])

    db_session.expire_all()
    res = await db_session.execute(
        select(SummarySectionDoc).where(
            SummarySectionDoc.card_id == summary_env["card_id"])
    )
    doc = res.scalar_one()
    assert doc.draft_rows is not None, "черновик раздела пропал"
    assert doc.draft_rows[0]["price_work"] == 1900
    assert doc.rev == 1


@pytest.mark.asyncio
async def test_changing_sections_to_the_same_set_changes_nothing(
    async_client, db_session, summary_env
):
    """Повторный вызов с тем же составом безопасен."""
    edited = _estimate_rows(1500)
    edited[0]["price_work"] = 4200
    await async_client.post(
        _url(summary_env, "/apply"), json={"rev": 0, "rows": edited},
        headers=_auth(summary_env["pm1"], "project_manager"))

    before = await _reload_summary(db_session, summary_env)
    summary_id, sections = before.id, [dict(s) for s in before.sections]

    await _change_sections(async_client, summary_env, [_section_input(summary_env)])

    after = await _reload_summary(db_session, summary_env)
    assert after.id == summary_id, "сводная пересоздана — история и черновики потеряны"
    assert after.sections == sections


# ---------------------------------------------------------------------------
# Унаследованные расхождения (план 2026-08-04, Фаза 3)
# ---------------------------------------------------------------------------
#
# До этой работы раздел был отдельной копией сметы и мог годами жить со своими
# числами. Такие снимки нельзя ни молча затереть сметой, ни молча записать в
# смету: в первом случае пропадает работа человека, во втором — результат
# расчёта. Поэтому расхождение показывается, а сторону выбирает человек.


@pytest.mark.asyncio
async def test_divergence_is_reported(async_client, summary_env):
    """Снимок раздела (1500) и смета (1000) разошлись — это видно при открытии."""
    resp = await async_client.get(
        _url(summary_env), headers=_auth(summary_env["pm1"], "project_manager"))

    assert resp.status_code == 200, resp.text
    diff = resp.json()["divergence"]
    assert diff is not None, "расхождение снимка и сметы должно быть видно"
    assert diff["section_rows"] == 2
    assert diff["estimate_rows"] == 2
    assert diff["section_total"] != diff["estimate_total"]


@pytest.mark.asyncio
async def test_no_divergence_when_sides_match(async_client, db_session, summary_env):
    """Когда стороны совпадают, тревожить человека нечем."""
    await async_client.post(
        f"/documents/{summary_env['card_id']}/estimate/apply",
        json={"rev": 0, "rows": _estimate_rows(1500)},
        headers=_auth(summary_env["pm1"], "project_manager"))

    resp = await async_client.get(
        _url(summary_env), headers=_auth(summary_env["pm1"], "project_manager"))

    assert resp.json()["divergence"] is None


@pytest.mark.asyncio
async def test_resolve_keeps_section_and_writes_it_into_estimate(
    async_client, db_session, summary_env
):
    """«Правки раздела верны» — они уезжают в смету."""
    resp = await async_client.post(
        _url(summary_env, "/divergence/resolve"), json={"prefer": "section"},
        headers=_auth(summary_env["pm1"], "project_manager"))
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    version = await db_session.get(EstimateVersion, summary_env["version_id"])
    assert version.rows[0]["price_work"] == 1500

    meta = await async_client.get(
        _url(summary_env), headers=_auth(summary_env["pm1"], "project_manager"))
    assert meta.json()["divergence"] is None


@pytest.mark.asyncio
async def test_resolve_takes_estimate_and_keeps_old_snapshot_in_history(
    async_client, db_session, summary_env
):
    """«Смета верна» — раздел берёт её строки, а прежние уходят в историю."""
    resp = await async_client.post(
        _url(summary_env, "/divergence/resolve"), json={"prefer": "estimate"},
        headers=_auth(summary_env["pm1"], "project_manager"))
    assert resp.status_code == 200, resp.text

    summary = await _reload_summary(db_session, summary_env)
    assert summary.sections[0]["rows"][0]["price_work"] == 1000

    res = await db_session.execute(
        select(TaskHistory).where(TaskHistory.document_kind == "summary-section"))
    entries = list(res.scalars().all())
    assert entries, "прежние строки раздела должны остаться в истории"
    assert entries[0].previous_value["rows"][0]["price_work"] == 1500


@pytest.mark.asyncio
async def test_colleague_resolves_divergence(async_client, summary_env):
    """Расхождение разруливает любой сотрудник — работа общая."""
    resp = await async_client.post(
        _url(summary_env, "/divergence/resolve"), json={"prefer": "estimate"},
        headers=_auth(summary_env["pm2"], "project_manager"))

    assert resp.status_code == 200, resp.text
