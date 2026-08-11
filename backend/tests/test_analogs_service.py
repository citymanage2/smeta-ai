"""«Найти аналоги» — поиск более дешёвой замены через ИИ.

Фаза 11 плана `plans/2026-08-02-edinyy-redaktor-tablic.md`.

Поиск идёт в интернете и стоит денег: смета обходится примерно в $10, из них
68% — веб-поиск. Поэтому здесь проверяется не только «нашлись варианты», но и
всё, что защищает от лишних трат и от испорченной сметы:

- действие есть только там, где у позиций есть цены (смета и оптимизация);
- пока идёт прогон, второй запуск по тому же документу не стартует;
- запущенный прогон можно остановить;
- вариант дороже исходной цены отбрасывается: смысл действия — удешевить;
- найденное — предложение, а не правка: документ сам по себе не меняется.

Решение пользователя (2026-08-03): ограничения на число позиций за запуск и
суточного потолка расходов нет — тормозом остаётся подтверждение с оценкой.
"""
import json

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.analog_run import (
    STATUS_CANCELLED,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    AnalogRun,
)
from app.models.document_lock import DocumentLock
from app.models.estimate_version import EstimateVersion
from app.models.history import TaskHistory
from app.models.job import Job
from app.models.project import Project
from app.models.result import TaskResult
from app.models.task import Task
from app.models.user import User
from app.models.workflow_card import WorkflowCard
from app.services import analogs_service
from app.utils.auth import create_access_token, hash_password


def _auth(user_id: int, role: str = "project_manager") -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id, role)}"}


def _rows() -> list:
    return [
        {"id": "r1", "type": "work", "name": "Кладка стен из кирпича", "unit": "м3",
         "qty": 10, "price_work": 1000, "price_material": None},
        {"id": "r2", "type": "material", "name": "Кирпич керамический М100",
         "unit": "шт", "qty": 500, "price_work": None, "price_material": 25},
    ]


def _selection() -> list:
    return [
        {"row_id": "r1", "name": "Кладка стен из кирпича", "unit": "м3",
         "qty": 10, "price": 1000, "kind": "work"},
        {"row_id": "r2", "name": "Кирпич керамический М100", "unit": "шт",
         "qty": 500, "price": 25, "kind": "material"},
    ]


def _reply(variants_by_row: dict) -> str:
    items = [
        {"row_id": row_id, "variants": variants}
        for row_id, variants in variants_by_row.items()
    ]
    return json.dumps({"items": items}, ensure_ascii=False)


@pytest_asyncio.fixture
async def analog_env(db_session, fake_s3):
    """Проект → карточка → задача «Смета из перечня» с рабочей версией."""
    for model in (AnalogRun, DocumentLock, EstimateVersion, TaskHistory, TaskResult,
                  Job, WorkflowCard, Task, Project, User):
        await db_session.execute(model.__table__.delete())
    await db_session.commit()

    pm = User(username="pm1", role="project_manager", full_name="Иванов Иван",
              password_hash=hash_password("p1"))
    other = User(username="pm2", role="project_manager", full_name="Петров Пётр",
                 password_hash=hash_password("p2"))
    db_session.add_all([pm, other])
    await db_session.flush()

    project = Project(name="Объект АР", owner_id=pm.id)
    db_session.add(project)
    await db_session.flush()

    task = Task(
        owner_id=pm.id, user_role="project_manager", task_type="ESTIMATE_FROM_LIST",
        status="completed", input_files=[], input_file_data=[], chat_history=[],
        project_id=str(project.id), progress_data={"items": []},
    )
    db_session.add(task)
    await db_session.flush()

    version = EstimateVersion(
        task_id=str(task.id), version_number=0, version_label="original",
        version_display_name="V0 — Оригинал", file_slot="estimate",
        task_type="ESTIMATE_FROM_LIST", rows=_rows(),
    )
    card = WorkflowCard(project_id=str(project.id), name="АР", stage="estimate",
                        estimate_task_id=str(task.id))
    db_session.add_all([version, card])
    await db_session.commit()

    yield {
        "pm": pm.id, "other": other.id, "project_id": str(project.id),
        "card_id": str(card.id), "task_id": str(task.id), "version_id": str(version.id),
    }

    for model in (AnalogRun, DocumentLock, EstimateVersion, TaskHistory, TaskResult,
                  Job, WorkflowCard, Task, Project, User):
        await db_session.execute(model.__table__.delete())
    await db_session.commit()


async def _start(async_client, env, rows=None, kind="estimate", user="pm"):
    return await async_client.post(
        f"/documents/{env['card_id']}/{kind}/analogs",
        json={"rows": _selection() if rows is None else rows},
        headers=_auth(env[user]),
    )


def _mock_claude(monkeypatch, reply, calls=None):
    """Подменить обращение к ИИ. Веб-поиск в тестах не гоняем — он платный."""
    async def _fake(*args, **kwargs):
        if calls is not None:
            calls.append(kwargs)
        if isinstance(reply, Exception):
            raise reply
        return reply(*args, **kwargs) if callable(reply) else reply

    monkeypatch.setattr(analogs_service, "call_claude", _fake)


# ---------------------------------------------------------------------------
# Оценка объёма — её человек видит до запуска
# ---------------------------------------------------------------------------

class TestEffortEstimate:
    def test_estimate_grows_with_positions(self):
        small = analogs_service.estimate_effort(5)
        big = analogs_service.estimate_effort(200)

        assert big["minutes"] > small["minutes"]
        assert big["searches"] > small["searches"]

    def test_estimate_never_promises_zero_minutes(self):
        assert analogs_service.estimate_effort(1)["minutes"] >= 1

    def test_estimate_of_nothing_is_zero(self):
        assert analogs_service.estimate_effort(0)["positions"] == 0


# ---------------------------------------------------------------------------
# Запуск
# ---------------------------------------------------------------------------

class TestStart:
    @pytest.mark.asyncio
    async def test_start_creates_run_and_job(self, async_client, db_session, analog_env):
        r = await _start(async_client, analog_env)

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == STATUS_QUEUED
        assert body["total"] == 2
        assert body["estimate"]["positions"] == 2

        run = (await db_session.execute(select(AnalogRun))).scalar_one()
        assert run.total == 2
        assert len(run.requested) == 2

        job = (await db_session.execute(select(Job))).scalar_one()
        assert job.kind == "document.analogs"
        assert job.payload["run_id"] == str(run.id)

    @pytest.mark.asyncio
    async def test_positions_without_name_or_price_are_dropped(
        self, async_client, db_session, analog_env
    ):
        """Удешевлять нечего: без цены не с чем сравнивать, без имени — нечего искать."""
        await _start(async_client, analog_env, rows=[
            {"row_id": "r1", "name": "Кладка", "unit": "м3", "qty": 10,
             "price": 1000, "kind": "work"},
            {"row_id": "r2", "name": "  ", "unit": "м3", "qty": 1,
             "price": 500, "kind": "work"},
            {"row_id": "r3", "name": "Без цены", "unit": "м3", "qty": 1,
             "price": None, "kind": "work"},
        ])

        run = (await db_session.execute(select(AnalogRun))).scalar_one()
        assert run.total == 1
        assert run.requested[0]["row_id"] == "r1"

    @pytest.mark.asyncio
    async def test_empty_selection_rejected(self, async_client, analog_env):
        r = await _start(async_client, analog_env, rows=[])

        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_not_available_for_flat_documents(
        self, async_client, db_session, analog_env
    ):
        """У перечня и полноты нет ни цен, ни типов строк — искать нечего."""
        task = Task(
            owner_id=analog_env["pm"], user_role="project_manager",
            task_type="LIST_FROM_GRAND", status="completed",
            input_files=[], input_file_data=[], chat_history=[],
            project_id=analog_env["project_id"],
        )
        db_session.add(task)
        await db_session.flush()
        card = await db_session.get(WorkflowCard, analog_env["card_id"])
        card.list_task_id = str(task.id)
        db_session.add(EstimateVersion(
            task_id=str(task.id), version_number=0, version_label="original",
            version_display_name="V0", rows=[], file_slot="result",
            task_type="LIST_FROM_GRAND",
        ))
        await db_session.commit()

        r = await _start(async_client, analog_env, kind="list")

        assert r.status_code == 409

    @pytest.mark.asyncio
    async def test_second_run_while_first_is_active_rejected(
        self, async_client, db_session, analog_env
    ):
        """Повторный запуск не создаёт второй прогон — иначе платим дважды."""
        first = await _start(async_client, analog_env)
        assert first.status_code == 200

        second = await _start(async_client, analog_env)

        assert second.status_code == 409
        runs = (await db_session.execute(select(AnalogRun))).scalars().all()
        assert len(runs) == 1

    @pytest.mark.asyncio
    async def test_new_run_allowed_after_previous_finished(
        self, async_client, db_session, analog_env
    ):
        await _start(async_client, analog_env)
        run = (await db_session.execute(select(AnalogRun))).scalar_one()
        run.status = STATUS_DONE
        await db_session.commit()

        again = await _start(async_client, analog_env)

        assert again.status_code == 200
        runs = (await db_session.execute(select(AnalogRun))).scalars().all()
        assert len(runs) == 2

    @pytest.mark.asyncio
    async def test_abandoned_run_does_not_block_forever(
        self, async_client, db_session, analog_env
    ):
        """Воркер упал вместе с прогоном — документ не должен остаться запертым."""
        from datetime import datetime, timedelta, timezone

        await _start(async_client, analog_env)
        stuck = (await db_session.execute(select(AnalogRun))).scalar_one()
        stuck.status = STATUS_RUNNING
        stuck.created_at = (
            datetime.now(timezone.utc)
            - timedelta(hours=analogs_service.ABANDONED_AFTER_HOURS + 1)
        )
        await db_session.commit()

        again = await _start(async_client, analog_env)

        assert again.status_code == 200
        await db_session.refresh(stuck)
        assert stuck.status == STATUS_FAILED

    @pytest.mark.asyncio
    async def test_failed_worker_releases_the_run(
        self, async_client, db_session, analog_env
    ):
        """Задача упала — прогон помечается несостоявшимся, а не висит «идущим»."""
        await _start(async_client, analog_env)
        run = (await db_session.execute(select(AnalogRun))).scalar_one()

        await analogs_service.mark_failed(db_session, str(run.id), "воркер упал")
        await db_session.refresh(run)

        assert run.status == STATUS_FAILED
        assert "воркер упал" in run.error

    @pytest.mark.asyncio
    async def test_colleague_starts_run_on_shared_document(self, async_client, analog_env):
        """Документы общие: поиск аналогов запускает и не владелец."""
        r = await _start(async_client, analog_env, user="other")

        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Обработка прогона (то, что делает воркер)
# ---------------------------------------------------------------------------

class TestProcess:
    @pytest.mark.asyncio
    async def test_successful_run_collects_variants(
        self, async_client, db_session, analog_env, monkeypatch
    ):
        await _start(async_client, analog_env)
        run = (await db_session.execute(select(AnalogRun))).scalar_one()

        _mock_claude(monkeypatch, _reply({
            "r1": [{"name": "Кладка из газобетона", "unit": "м3", "price": 700,
                    "reason": "тот же результат дешевле", "source": "https://example.ru"}],
            "r2": [{"name": "Кирпич силикатный М150", "unit": "шт", "price": 18,
                    "reason": "аналог по прочности", "source": "https://shop.ru"}],
        }))

        await analogs_service.process_run(db_session, str(run.id))
        await db_session.refresh(run)

        assert run.status == STATUS_DONE
        assert run.processed == run.total == 2
        by_row = {item["row_id"]: item for item in run.results}
        assert by_row["r1"]["variants"][0]["name"] == "Кладка из газобетона"
        assert by_row["r2"]["variants"][0]["price"] == 18

    @pytest.mark.asyncio
    async def test_money_difference_counted_by_volume(
        self, async_client, db_session, analog_env, monkeypatch
    ):
        """Разницу считает сервер: 10 м3 × (1000 − 700) = 3000 ₽."""
        await _start(async_client, analog_env)
        run = (await db_session.execute(select(AnalogRun))).scalar_one()

        _mock_claude(monkeypatch, _reply({
            "r1": [{"name": "Газобетон", "unit": "м3", "price": 700,
                    "reason": "дешевле", "source": "https://example.ru"}],
        }))

        await analogs_service.process_run(db_session, str(run.id))
        await db_session.refresh(run)

        variant = next(i for i in run.results if i["row_id"] == "r1")["variants"][0]
        assert variant["delta"] == 3000

    @pytest.mark.asyncio
    async def test_more_expensive_variants_dropped(
        self, async_client, db_session, analog_env, monkeypatch
    ):
        """Смысл действия — удешевить. Вариант дороже исходного — не аналог."""
        await _start(async_client, analog_env)
        run = (await db_session.execute(select(AnalogRun))).scalar_one()

        _mock_claude(monkeypatch, _reply({
            "r1": [
                {"name": "Дороже", "unit": "м3", "price": 1500, "reason": "", "source": ""},
                {"name": "Дешевле", "unit": "м3", "price": 800, "reason": "", "source": ""},
            ],
        }))

        await analogs_service.process_run(db_session, str(run.id))
        await db_session.refresh(run)

        names = [v["name"] for i in run.results if i["row_id"] == "r1"
                 for v in i["variants"]]
        assert names == ["Дешевле"]

    @pytest.mark.asyncio
    async def test_at_most_three_variants_per_position(
        self, async_client, db_session, analog_env, monkeypatch
    ):
        await _start(async_client, analog_env)
        run = (await db_session.execute(select(AnalogRun))).scalar_one()

        _mock_claude(monkeypatch, _reply({
            "r1": [
                {"name": f"Вариант {i}", "unit": "м3", "price": 900 - i,
                 "reason": "", "source": ""}
                for i in range(6)
            ],
        }))

        await analogs_service.process_run(db_session, str(run.id))
        await db_session.refresh(run)

        variants = next(i for i in run.results if i["row_id"] == "r1")["variants"]
        assert len(variants) == 3

    @pytest.mark.asyncio
    async def test_answer_without_variants_is_not_an_error(
        self, async_client, db_session, analog_env, monkeypatch
    ):
        """Аналог нашёлся не для всякой позиции — это нормальный исход."""
        await _start(async_client, analog_env)
        run = (await db_session.execute(select(AnalogRun))).scalar_one()

        _mock_claude(monkeypatch, _reply({}))

        await analogs_service.process_run(db_session, str(run.id))
        await db_session.refresh(run)

        assert run.status == STATUS_DONE
        assert all(item["variants"] == [] for item in run.results)

    @pytest.mark.asyncio
    async def test_broken_answer_does_not_lose_the_whole_run(
        self, async_client, db_session, analog_env, monkeypatch
    ):
        """Мусор вместо JSON — пачка остаётся без вариантов, прогон доходит до конца."""
        await _start(async_client, analog_env)
        run = (await db_session.execute(select(AnalogRun))).scalar_one()

        _mock_claude(monkeypatch, "не json, а извинения")

        await analogs_service.process_run(db_session, str(run.id))
        await db_session.refresh(run)

        assert run.status == STATUS_DONE
        assert run.processed == run.total

    @pytest.mark.asyncio
    async def test_ai_failure_marks_run_failed_with_readable_error(
        self, async_client, db_session, analog_env, monkeypatch
    ):
        await _start(async_client, analog_env)
        run = (await db_session.execute(select(AnalogRun))).scalar_one()

        _mock_claude(monkeypatch, RuntimeError("Claude недоступен"))

        await analogs_service.process_run(db_session, str(run.id))
        await db_session.refresh(run)

        assert run.status == STATUS_FAILED
        assert run.error
        assert "Claude недоступен" in run.error

    @pytest.mark.asyncio
    async def test_web_search_is_used(
        self, async_client, db_session, analog_env, monkeypatch
    ):
        """Источник цен — интернет: без веб-поиска модель выдумает цифры."""
        await _start(async_client, analog_env)
        run = (await db_session.execute(select(AnalogRun))).scalar_one()
        calls: list = []
        _mock_claude(monkeypatch, _reply({}), calls=calls)

        await analogs_service.process_run(db_session, str(run.id))

        assert calls and all(call.get("use_web_search") for call in calls)

    @pytest.mark.asyncio
    async def test_cancelled_run_stops_and_keeps_what_was_found(
        self, async_client, db_session, analog_env, monkeypatch
    ):
        """Прогон без потолка позиций должен останавливаться по требованию."""
        rows = [
            {"row_id": f"r{i}", "name": f"Позиция {i}", "unit": "м3", "qty": 1,
             "price": 1000, "kind": "work"}
            for i in range(analogs_service.BATCH_SIZE * 2)
        ]
        await _start(async_client, analog_env, rows=rows)
        run = (await db_session.execute(select(AnalogRun))).scalar_one()

        async def _cancel_after_first_batch(*args, **kwargs):
            run.status = STATUS_CANCELLED
            await db_session.commit()
            return _reply({})

        monkeypatch.setattr(analogs_service, "call_claude", _cancel_after_first_batch)

        await analogs_service.process_run(db_session, str(run.id))
        await db_session.refresh(run)

        assert run.status == STATUS_CANCELLED
        assert run.processed < run.total

    @pytest.mark.asyncio
    async def test_results_of_every_batch_are_saved(
        self, async_client, db_session, analog_env, monkeypatch
    ):
        """Прогон длиннее одной пачки: сохраниться должны все пачки, не только первая."""
        count = analogs_service.BATCH_SIZE * 3
        rows = [
            {"row_id": f"r{i}", "name": f"Позиция {i}", "unit": "м3", "qty": 1,
             "price": 1000, "kind": "work"}
            for i in range(count)
        ]
        await _start(async_client, analog_env, rows=rows)
        run = (await db_session.execute(select(AnalogRun))).scalar_one()

        async def _answer(*args, **kwargs):
            # Отвечаем на все позиции разом: сервис возьмёт только те row_id,
            # которые есть в текущей пачке.
            return _reply({
                f"r{i}": [{"name": f"Аналог {i}", "unit": "м3", "price": 800,
                           "reason": "", "source": ""}]
                for i in range(count)
            })

        monkeypatch.setattr(analogs_service, "call_claude", _answer)

        await analogs_service.process_run(db_session, str(run.id))
        db_session.expire(run)
        await db_session.refresh(run)

        assert len(run.results) == count
        assert all(item["variants"] for item in run.results)

    @pytest.mark.asyncio
    async def test_partial_failures_are_reported(
        self, async_client, db_session, analog_env, monkeypatch
    ):
        """Часть пачек не прошла — прогон завершается, но об этом сказано."""
        rows = [
            {"row_id": f"r{i}", "name": f"Позиция {i}", "unit": "м3", "qty": 1,
             "price": 1000, "kind": "work"}
            for i in range(analogs_service.BATCH_SIZE * 2)
        ]
        await _start(async_client, analog_env, rows=rows)
        run = (await db_session.execute(select(AnalogRun))).scalar_one()

        attempts: list = []

        async def _fail_second(*args, **kwargs):
            attempts.append(1)
            if len(attempts) == 2:
                raise RuntimeError("таймаут поиска")
            return _reply({})

        monkeypatch.setattr(analogs_service, "call_claude", _fail_second)

        await analogs_service.process_run(db_session, str(run.id))
        await db_session.refresh(run)

        assert run.status == STATUS_DONE
        assert run.error and "не удалось" in run.error.lower()

    @pytest.mark.asyncio
    async def test_document_rows_untouched_by_run(
        self, async_client, db_session, analog_env, monkeypatch
    ):
        """Найденное — предложение. Смету меняет только человек кнопкой «Заменить»."""
        await _start(async_client, analog_env)
        run = (await db_session.execute(select(AnalogRun))).scalar_one()
        _mock_claude(monkeypatch, _reply({
            "r1": [{"name": "Газобетон", "unit": "м3", "price": 700,
                    "reason": "", "source": ""}],
        }))

        await analogs_service.process_run(db_session, str(run.id))

        version = await db_session.get(EstimateVersion, analog_env["version_id"])
        assert version.rows == _rows()
        assert version.rev == 0


# ---------------------------------------------------------------------------
# Чтение состояния и отмена
# ---------------------------------------------------------------------------

class TestReadAndCancel:
    @pytest.mark.asyncio
    async def test_status_shows_progress(self, async_client, db_session, analog_env):
        await _start(async_client, analog_env)
        run = (await db_session.execute(select(AnalogRun))).scalar_one()
        run.status = STATUS_RUNNING
        run.processed = 1
        await db_session.commit()

        r = await async_client.get(
            f"/documents/{analog_env['card_id']}/estimate/analogs",
            headers=_auth(analog_env["pm"]),
        )

        assert r.status_code == 200
        body = r.json()
        assert body["status"] == STATUS_RUNNING
        assert body["processed"] == 1
        assert body["total"] == 2

    @pytest.mark.asyncio
    async def test_no_runs_yet_reads_empty(self, async_client, analog_env):
        r = await async_client.get(
            f"/documents/{analog_env['card_id']}/estimate/analogs",
            headers=_auth(analog_env["pm"]),
        )

        assert r.status_code == 200
        assert r.json()["status"] is None

    @pytest.mark.asyncio
    async def test_cancel_marks_run_cancelled(
        self, async_client, db_session, analog_env
    ):
        await _start(async_client, analog_env)

        r = await async_client.post(
            f"/documents/{analog_env['card_id']}/estimate/analogs/cancel",
            headers=_auth(analog_env["pm"]),
        )

        assert r.status_code == 200
        run = (await db_session.execute(select(AnalogRun))).scalar_one()
        await db_session.refresh(run)
        assert run.status == STATUS_CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_without_active_run_is_harmless(
        self, async_client, analog_env
    ):
        r = await async_client.post(
            f"/documents/{analog_env['card_id']}/estimate/analogs/cancel",
            headers=_auth(analog_env["pm"]),
        )

        assert r.status_code == 200
