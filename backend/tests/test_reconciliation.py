"""Сверка: что выдал ИИ, что сделал сервис, что поправил человек.

План: plans/2026-09-10-sverka-i-obuchenie-na-pravkah.md, Фаза 2.

Главное, что здесь проверяется, — три колонки не путаются местами. Между
ответом ИИ и правкой человека строку меняет сам сервис (подбор цен, проверка
единиц, коэффициент), и без разделения «сервис поставил» / «человек поставил»
отчёт о качестве назначал бы человеку чужие изменения и наоборот.
"""
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.ai_baseline import AiBaseline
from app.models.correction_signal import CorrectionSignal
from app.models.document_lock import DocumentLock
from app.models.estimate_version import EstimateVersion
from app.models.history import TaskHistory
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.models.workflow_card import WorkflowCard
from app.services import ai_baseline
from app.utils.auth import create_access_token, hash_password

_MODELS = (AiBaseline, CorrectionSignal, DocumentLock, EstimateVersion,
           TaskHistory, WorkflowCard, Task, Project, User)


def _auth(user_id: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id, 'project_manager', 'pm1')}"}


def _estimate_rows(price_work: float = 3000.0, qty: float = 4) -> list[dict]:
    """Смета: две строки, стоимость считается row_cost — qty × цена."""
    return [
        {"id": "e1", "lineage_id": "e1", "type": "work", "name": "Кладка стен",
         "unit": "м3", "qty": qty, "price_work": price_work, "price_material": None,
         "price_list_name": "Прайс подрядчика №2"},
        {"id": "e2", "lineage_id": "e2", "type": "material", "name": "Кирпич",
         "unit": "шт", "qty": 100, "price_work": None, "price_material": 25.0},
    ]


@pytest_asyncio.fixture
async def env(db_session, fake_s3):
    for model in _MODELS:
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

    version = EstimateVersion(
        task_id=str(task.id), version_number=0, version_label="original",
        version_display_name="V0", rows=_estimate_rows(),
        file_slot="estimate", task_type="ESTIMATE_FROM_LIST",
    )
    db_session.add(version)
    await db_session.commit()

    yield {"pm1": pm1.id, "card_id": str(card.id), "task_id": str(task.id),
           "version_id": str(version.id)}

    for model in _MODELS:
        await db_session.execute(model.__table__.delete())
    await db_session.commit()


async def _recon(async_client, env) -> dict:
    r = await async_client.get(
        f"/documents/{env['card_id']}/estimate/reconciliation",
        headers=_auth(env["pm1"]),
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _apply(async_client, env, rows: list, rev: int = 0):
    r = await async_client.post(
        f"/documents/{env['card_id']}/estimate/apply",
        json={"version_id": env["version_id"], "rev": rev, "rows": rows},
        headers=_auth(env["pm1"]),
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
async def test_without_snapshot_says_so_and_breaks_nothing(async_client, env):
    """Задача, посчитанная до появления снимков, отдаёт пустую честную сверку."""
    data = await _recon(async_client, env)

    assert data["has_baseline"] is False
    assert data["rows"] == []
    assert data["totals"]["ai_total"] is None
    # Стоимость документа считается и без снимка, по формуле редактора:
    # 12 000 работ × 1,03 + 2 500 материалов × 1,03 = 14 935.
    assert data["totals"]["current_total"] == 14935.0


@pytest.mark.asyncio
async def test_human_edit_shows_three_columns(async_client, db_session, env):
    """Правка человека: ИИ 3000 → сервис 3000 → сейчас 2500, автор — человек."""
    await ai_baseline.save_once(
        db_session, task_id=env["task_id"], document_kind="estimate",
        rows=_estimate_rows(3000.0),
    )

    await _apply(async_client, env, _estimate_rows(2500.0))

    data = await _recon(async_client, env)
    assert data["has_baseline"] is True

    row = next(r for r in data["rows"] if r["row_key"] == "e1")
    cell = next(c for c in row["cells"] if c["field_key"] == "price_work")

    assert cell["ai_value"] == "3000.0"
    assert cell["service_value"] == "3000.0"
    assert cell["current_value"] == "2500.0"
    assert cell["changed_by"] == "human"
    assert cell["delta"] == -500.0
    assert cell["price_source"] == "Прайс подрядчика №2"
    assert cell["user_name"] == "Иванов Иван"


@pytest.mark.asyncio
async def test_service_change_is_not_blamed_on_human(async_client, db_session, env):
    """Цену поменял не человек, а сам сервис — сигнала нет, автор «сервис».

    Тот же случай, что подбор цен по прайсу: строки поехали, журнал молчит.
    """
    await ai_baseline.save_once(
        db_session, task_id=env["task_id"], document_kind="estimate",
        rows=_estimate_rows(3000.0),
    )

    version = await db_session.get(EstimateVersion, env["version_id"])
    version.rows = _estimate_rows(2800.0)
    await db_session.commit()

    data = await _recon(async_client, env)
    cell = next(
        c for r in data["rows"] if r["row_key"] == "e1"
        for c in r["cells"] if c["field_key"] == "price_work"
    )

    assert cell["ai_value"] == "3000.0"
    assert cell["current_value"] == "2800.0"
    # Ключевое: «сервис поставил» = «сейчас», человек к ячейке не прикасался.
    assert cell["service_value"] == "2800.0"
    assert cell["changed_by"] == "service"
    assert cell["user_name"] is None


@pytest.mark.asyncio
async def test_service_then_human_keeps_both_steps_visible(
    async_client, db_session, env
):
    """ИИ 3000 → сервис 2800 → человек 2500: видно оба шага, а не один."""
    await ai_baseline.save_once(
        db_session, task_id=env["task_id"], document_kind="estimate",
        rows=_estimate_rows(3000.0),
    )

    # Сервис поправил цену сам, журнала не оставив.
    version = await db_session.get(EstimateVersion, env["version_id"])
    version.rows = _estimate_rows(2800.0)
    await db_session.commit()

    # Теперь правит человек — это «Применить», сигнал будет.
    await _apply(async_client, env, _estimate_rows(2500.0))

    data = await _recon(async_client, env)
    cell = next(
        c for r in data["rows"] if r["row_key"] == "e1"
        for c in r["cells"] if c["field_key"] == "price_work"
    )

    assert cell["ai_value"] == "3000.0"
    assert cell["service_value"] == "2800.0"
    assert cell["current_value"] == "2500.0"
    assert cell["changed_by"] == "human"
    # Промах считается от ответа ИИ: 2500 − 3000.
    assert cell["delta"] == -500.0


@pytest.mark.asyncio
async def test_second_edit_does_not_move_service_column(
    async_client, db_session, env
):
    """Правка правки не подменяет «сервис поставил» человеческим числом."""
    await ai_baseline.save_once(
        db_session, task_id=env["task_id"], document_kind="estimate",
        rows=_estimate_rows(3000.0),
    )

    await _apply(async_client, env, _estimate_rows(2500.0), rev=0)
    await _apply(async_client, env, _estimate_rows(2400.0), rev=1)

    data = await _recon(async_client, env)
    cell = next(
        c for r in data["rows"] if r["row_key"] == "e1"
        for c in r["cells"] if c["field_key"] == "price_work"
    )

    # 2500 — уже человеческое число, в колонку сервиса оно попасть не должно.
    assert cell["service_value"] == "3000.0"
    assert cell["current_value"] == "2400.0"


@pytest.mark.asyncio
async def test_added_and_removed_rows_are_visible(async_client, db_session, env):
    """Пропущенная и выдуманная позиция — самый ценный сигнал, он не теряется."""
    await ai_baseline.save_once(
        db_session, task_id=env["task_id"], document_kind="estimate",
        rows=_estimate_rows(3000.0),
    )

    rows = _estimate_rows(3000.0)
    rows.pop()  # человек убрал «Кирпич»
    rows.append({"id": "e3", "lineage_id": "e3", "type": "work", "name": "Штукатурка",
                 "unit": "м2", "qty": 10, "price_work": 700.0, "price_material": None})
    await _apply(async_client, env, rows)

    data = await _recon(async_client, env)
    statuses = {r["row_key"]: r["status"] for r in data["rows"]}

    assert statuses["e3"] == "added"
    assert statuses["e2"] == "removed"
    assert data["counts"]["rows_added"] == 1
    assert data["counts"]["rows_removed"] == 1


@pytest.mark.asyncio
async def test_untouched_rows_do_not_clutter_the_list(async_client, db_session, env):
    """Строка без расхождений в список не попадает вовсе."""
    await ai_baseline.save_once(
        db_session, task_id=env["task_id"], document_kind="estimate",
        rows=_estimate_rows(3000.0),
    )

    await _apply(async_client, env, _estimate_rows(2500.0))

    data = await _recon(async_client, env)
    # Правили только «Кладку стен»; «Кирпич» не изменился и в сверке не нужен.
    assert [r["row_key"] for r in data["rows"]] == ["e1"]


@pytest.mark.asyncio
async def test_totals_match_document_cost(async_client, db_session, env):
    """Итог сверки сходится со стоимостью строк: та же формула, что в редакторе."""
    await ai_baseline.save_once(
        db_session, task_id=env["task_id"], document_kind="estimate",
        rows=_estimate_rows(3000.0),
    )

    await _apply(async_client, env, _estimate_rows(2500.0))

    data = (await _recon(async_client, env))["totals"]

    # Формула та же, что в редакторе: работы + 3% накладных + материалы + 3%
    # транспортных. ИИ: 12 000 × 1,03 + 2 500 × 1,03 = 14 935.
    # Стало: 10 000 × 1,03 + 2 500 × 1,03 = 12 875.
    assert data["ai_total"] == 14935.0
    assert data["current_total"] == 12875.0
    assert data["delta"] == -2060.0
    assert data["delta_pct"] == -13.79


@pytest.mark.asyncio
async def test_signals_are_written_for_the_same_task(async_client, db_session, env):
    """Страховка: сверка опирается на журнал, и журнал по этой правке есть."""
    await ai_baseline.save_once(
        db_session, task_id=env["task_id"], document_kind="estimate",
        rows=_estimate_rows(3000.0),
    )
    await _apply(async_client, env, _estimate_rows(2500.0))

    db_session.expire_all()
    signals = (await db_session.execute(
        select(CorrectionSignal).where(CorrectionSignal.task_id == env["task_id"])
    )).scalars().all()

    assert [s.field for s in signals if s.is_first_touch] == ["price_work"]


@pytest.mark.asyncio
async def test_rebuilt_rows_are_matched_by_name(async_client, db_session, env):
    """Строки пересобрали с новыми id — сверка не должна сойти с ума.

    Так делает миграция смет: `estimate_migration` строит строки из позиций без
    `row_id`, и каждая получает новый uuid. Сравнение по идентификаторам
    показало бы «ИИ выдал 2 позиции, обе удалены, человек добавил 2 своих».
    """
    await ai_baseline.save_once(
        db_session, task_id=env["task_id"], document_kind="estimate",
        rows=_estimate_rows(3000.0),
    )

    rebuilt = _estimate_rows(2500.0)
    for index, row in enumerate(rebuilt):
        row["id"] = f"new-{index}"
        row["lineage_id"] = f"new-{index}"
    version = await db_session.get(EstimateVersion, env["version_id"])
    version.rows = rebuilt
    await db_session.commit()

    data = await _recon(async_client, env)

    assert data["match_mode"] == "name_unit"
    # Позиция узнана по имени и единице: одна изменённая строка, а не четыре
    # «удалили/добавили».
    assert data["counts"]["rows_added"] == 0
    assert data["counts"]["rows_removed"] == 0
    cell = next(
        c for r in data["rows"] for c in r["cells"] if c["field_key"] == "price_work"
    )
    assert cell["ai_value"] == "3000.0"
    assert cell["current_value"] == "2500.0"


@pytest.mark.asyncio
async def test_service_change_after_human_is_not_credited_to_human(
    async_client, db_session, env
):
    """После правки человека ячейку изменил сервис — автором человек не остаётся.

    Иначе панель показывала бы машинное число как «поставил человек»: он такого
    не ставил, а по этой подписи потом учат прайс.
    """
    await ai_baseline.save_once(
        db_session, task_id=env["task_id"], document_kind="estimate",
        rows=_estimate_rows(3000.0),
    )

    await _apply(async_client, env, _estimate_rows(2500.0))

    # Теперь значение меняет сам сервис — например, проверка единиц.
    db_session.expire_all()
    version = await db_session.get(EstimateVersion, env["version_id"])
    version.rows = _estimate_rows(2700.0)
    await db_session.commit()

    data = await _recon(async_client, env)
    cell = next(
        c for r in data["rows"] if r["row_key"] == "e1"
        for c in r["cells"] if c["field_key"] == "price_work"
    )

    assert cell["current_value"] == "2700.0"
    assert cell["changed_by"] == "service"
    # Шаг человека при этом не теряется: видно, что он ставил 2500.
    assert cell["service_value"] == "3000.0"
