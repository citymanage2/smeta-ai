"""Допзапросы к ИИ помечаются в журнале затрат отдельно от основной обработки.

План: `plans/2026-08-06-metriki-zatrat-po-stadiyam.md`, Фаза 2.

Одна стадия сметы тратит деньги дважды: сначала обработчик формирует файл,
потом человек доспрашивает ИИ из редактора — ищет цену строки, аналоги,
предложения по оптимизации. В карточке это две разные цифры, и перепутать их
нельзя: именно по разнице видно, где утекают деньги.

До этой фичи шесть из семи таких мест не писали вызов в журнал вовсе — не было
`task_id`/`db`, и `_log_api_call` молча выходил. Здесь проверяется, что вызов
доезжает до журнала (`api_call_log`) с верной задачей и верным признаком. Подменён
только Claude API; журнал пишется своей сессией приложения в тестовую БД.
"""
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.models.analog_run import AnalogRun
from app.models.api_call_log import ApiCallLog
from app.models.task import Task
# document_locks ссылается на workflow_cards — без этого импорта метаданные
# таблиц неполны, и фикстура create_tables падает при запуске файла отдельно.
from app.models.workflow_card import WorkflowCard  # noqa: F401
from app.services import analogs_service, claude_service, price_service


@pytest_asyncio.fixture
async def task_id(db_session, app_sessions):
    """Посчитанная смета, к которой относятся вызовы; журнал и задача — после теста долой."""
    task = Task(
        id=str(uuid.uuid4()), owner_id=1, user_role="project_manager",
        task_type="ESTIMATE_FROM_LIST", status="completed",
        input_files=[], input_file_data=[], chat_history=[],
    )
    db_session.add(task)
    await db_session.commit()
    tid = str(task.id)
    yield tid
    await db_session.rollback()
    await db_session.execute(delete(ApiCallLog).where(ApiCallLog.task_id == tid))
    await db_session.execute(delete(AnalogRun).where(AnalogRun.task_id == tid))
    await db_session.execute(delete(Task).where(Task.id == tid))
    await db_session.commit()


async def _journal(db_session, task_id: str) -> list[tuple[str, bool]]:
    """Строки журнала затрат задачи: (task_id, is_extra)."""
    db_session.expire_all()
    rows = (
        await db_session.execute(select(ApiCallLog).where(ApiCallLog.task_id == task_id))
    ).scalars().all()
    return [(str(r.task_id), r.is_extra) for r in rows]


@pytest.mark.asyncio
async def test_analogs_search_logged_as_extra(db_session, task_id, claude_api):
    """Поиск аналогов идёт по уже сформированному документу → доп."""
    claude_api({"items": []})
    run = AnalogRun(
        task_id=task_id, document_kind="estimate", status="queued",
        requested=analogs_service.prepare_positions(
            [{"row_id": "r1", "name": "Кирпич", "unit": "шт", "price": 25}]
        ),
        results=[], processed=0, total=1,
    )
    db_session.add(run)
    await db_session.commit()

    await analogs_service.process_run(db_session, str(run.id))  # так его зовёт воркер

    assert await _journal(db_session, task_id) == [(task_id, True)]


@pytest.mark.asyncio
async def test_web_search_work_price_logged_as_extra(db_session, task_id, claude_api, price_db):
    """Цены работы нет в прайсе — веб-поиск платный, это доп этой задачи."""
    await price_db.load()  # прайс пуст: ни точного, ни похожего совпадения
    claude_api({"price": 900, "unit": "м3", "source": "example.ru"})

    found = await price_service.find_work_price("Кладка стен", task_id=task_id, db=db_session)

    assert found is not None and found["min_price"] == 900
    assert await _journal(db_session, task_id) == [(task_id, True)]


@pytest.mark.asyncio
async def test_find_material_price_threads_task_through(db_session, task_id, claude_api, price_db):
    """Прайс-лист и эмбеддинги бесплатны — task_id доезжает до веб-поиска."""
    await price_db.load()
    claude_api({"price": 20, "unit": "шт", "source": "example.ru"})

    price = await price_service.find_material_price(
        "Кирпич керамический", task_id=task_id, db=db_session
    )

    assert price == 20
    assert await _journal(db_session, task_id) == [(task_id, True)]


@pytest.mark.asyncio
async def test_main_processing_is_not_extra(db_session, task_id, claude_api):
    """Обработчик задачи по умолчанию пишет вызов как основной, а не как доп."""
    claude_api({})

    await claude_service.call_claude(
        messages=[{"role": "user", "content": "привет"}],
        task_id=task_id,
        db=db_session,
    )

    assert await _journal(db_session, task_id) == [(task_id, False)]
