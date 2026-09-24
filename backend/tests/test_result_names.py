"""Файл сметы и оптимизации называется по карточке.

Раньше каждая смета проекта скачивалась как «Смета_из_перечня.xlsx», а
оптимизация — как «optimized.xlsx», и в загрузках их было не различить.
Теперь имя повторяет отличительную часть названия карточки — то, что после
двоеточия: «Перечень из Гранд-сметы: ПОМЕЩЕНИЯ №93» → «Смета_ПОМЕЩЕНИЯ_№93.xlsx».
"""
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.estimate_version import EstimateVersion
from app.models.project import Project
from app.models.result import TaskResult
from app.models.task import Task
from app.models.user import User
from app.models.workflow_card import WorkflowCard
from app.services import estimate_store, result_names
from app.utils.auth import hash_password


class TestStageFileName:
    def test_takes_part_after_colon(self):
        assert result_names.stage_file_name(
            "Смета", "Перечень из Гранд-сметы: ПОМЕЩЕНИЯ_№_93_АПС_по_плану",
        ) == "Смета_ПОМЕЩЕНИЯ_№_93_АПС_по_плану.xlsx"

    def test_spaces_become_underscores(self):
        assert result_names.stage_file_name(
            "Оптимизация", "Перечень из проекта: Помещения №93 АПС",
        ) == "Оптимизация_Помещения_№93_АПС.xlsx"

    def test_whole_name_without_colon(self):
        assert result_names.stage_file_name("Смета", "Корпус 2") == "Смета_Корпус_2.xlsx"

    def test_only_first_colon_splits(self):
        assert result_names.stage_file_name(
            "Смета", "Перечень: Этап 1: кровля",
        ) == "Смета_Этап_1__кровля.xlsx"

    def test_forbidden_characters_replaced(self):
        assert result_names.stage_file_name(
            "Смета", 'Перечень: Секция 1/2 "А"?',
        ) == "Смета_Секция_1_2__А.xlsx"

    def test_empty_tail_falls_back_to_whole_name(self):
        assert result_names.stage_file_name("Смета", "Перечень:") == "Смета_Перечень.xlsx"

    def test_no_name_gives_none(self):
        assert result_names.stage_file_name("Смета", None) is None
        assert result_names.stage_file_name("Смета", "   ") is None

    def test_long_name_is_cut(self):
        name = result_names.stage_file_name("Смета", "Перечень: " + "А" * 300)
        assert name == "Смета_" + "А" * 100 + ".xlsx"


def _items() -> list[dict]:
    return [{
        "type": "Работа", "name": "Кладка стен", "unit": "м3", "quantity": 4,
        "work_price": 1000.0, "material_price": None,
    }]


@pytest_asyncio.fixture
async def env(db_session, fake_s3):
    for model in (EstimateVersion, TaskResult, WorkflowCard, Task, Project, User):
        await db_session.execute(model.__table__.delete())
    await db_session.commit()

    pm = User(username="pm1", role="project_manager", password_hash=hash_password("p1"))
    db_session.add(pm)
    await db_session.flush()
    project = Project(name="Объект", owner_id=pm.id)
    db_session.add(project)
    await db_session.flush()
    task = Task(
        owner_id=pm.id, user_role="project_manager", task_type="ESTIMATE_FROM_LIST",
        status="completed", input_files=[], input_file_data=[], chat_history=[],
        project_id=str(project.id), progress_data={"items": _items()},
    )
    db_session.add(task)
    await db_session.flush()
    db_session.add(WorkflowCard(
        project_id=str(project.id), name="Перечень из Гранд-сметы: ПОМЕЩЕНИЯ №93",
        stage="estimate", estimate_task_id=str(task.id),
    ))
    await db_session.commit()

    yield task

    for model in (EstimateVersion, TaskResult, WorkflowCard, Task, Project, User):
        await db_session.execute(model.__table__.delete())
    await db_session.commit()


async def _estimate_file_name(db, task_id: str) -> str:
    db.expire_all()
    res = await db.execute(select(TaskResult).where(
        TaskResult.task_id == task_id, TaskResult.slot == "estimate",
    ))
    return res.scalar_one().file_name


@pytest.mark.asyncio
async def test_task_file_name_by_card(db_session, env):
    assert await result_names.task_file_name(
        db_session, str(env.id), "Смета", "Смета_из_перечня.xlsx",
    ) == "Смета_ПОМЕЩЕНИЯ_№93.xlsx"


@pytest.mark.asyncio
async def test_task_without_card_keeps_fallback(db_session, env):
    assert await result_names.task_file_name(
        db_session, "00000000-0000-0000-0000-000000000000", "Смета", "Смета_из_перечня.xlsx",
    ) == "Смета_из_перечня.xlsx"


@pytest.mark.asyncio
async def test_new_estimate_file_named_by_card(db_session, env):
    await estimate_store.write_items(db_session, env, _items())

    assert await _estimate_file_name(db_session, str(env.id)) == "Смета_ПОМЕЩЕНИЯ_№93.xlsx"


@pytest.mark.asyncio
async def test_legacy_default_name_is_upgraded(db_session, env):
    """Смета, посчитанная до функции, получает имя по карточке при следующей записи."""
    db_session.add(TaskResult(
        task_id=str(env.id), slot="estimate", file_name="Смета_из_перечня.xlsx",
        mime_type=estimate_store.XLSX_MIME, storage_key="old", size_bytes=1,
    ))
    await db_session.commit()

    await estimate_store.write_items(db_session, env, _items())

    assert await _estimate_file_name(db_session, str(env.id)) == "Смета_ПОМЕЩЕНИЯ_№93.xlsx"


@pytest.mark.asyncio
async def test_name_given_by_person_is_kept(db_session, env):
    db_session.add(TaskResult(
        task_id=str(env.id), slot="estimate", file_name="Моя смета.xlsx",
        mime_type=estimate_store.XLSX_MIME, storage_key="old", size_bytes=1,
    ))
    await db_session.commit()

    await estimate_store.write_items(db_session, env, _items())

    assert await _estimate_file_name(db_session, str(env.id)) == "Моя смета.xlsx"
