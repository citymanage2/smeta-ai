"""Цели оптимизации: расчёт отклонений в сводной.

План `plans/2026-09-01-celi-optimizacii.md`, Фазы 1–2.

Набор данных — тот же, что в `test_summary_calc.py` и во фронтовом
регресс-тесте: числа фактов уже закреплены там, здесь к ним добавлены цели.
Те же ожидания продублированы на экране
(`frontend/src/__tests__/summaryTargets.test.ts`) — правило проекта №4: экран и
файл считают по одной формуле.

Цель не задана — это не цель 0: у раздела «ОВ» цели по работам нет вовсе, и
отклонение по ним не считается ни в строке раздела, ни в ИТОГО.
"""
import pytest

from app.utils.summary_calc import calc_summary

from tests.test_summary_calc import OVERRIDES as BASE_OVERRIDES, SECTIONS as BASE_SECTIONS

# Цели: у «АР» заданы обе, у «ОВ» — только материалы.
SECTIONS = [
    {**BASE_SECTIONS[0], "target_works": 15000, "target_materials": 20000},
    {**BASE_SECTIONS[1], "target_materials": 40000},
]
OVERRIDES = {**BASE_OVERRIDES, "target_total_for_customer": 200000}


def _sections(calc):
    return {s["card_name"]: s for s in calc["section_totals"]}


def test_deviation_is_fact_minus_target_in_cost_basis():
    """База «из сметы (с/с)»: сравниваем с себестоимостью раздела."""
    calc = calc_summary(SECTIONS, {**OVERRIDES, "target_basis": "cost"})
    ar = _sections(calc)["АР"]

    assert ar["target_works"] == pytest.approx(15000)
    assert ar["works_fact"] == pytest.approx(17932.53125, rel=1e-9)
    assert ar["works_deviation"] == pytest.approx(2932.53125, rel=1e-9)
    assert ar["works_deviation_pct"] == pytest.approx(19.550208333333334, rel=1e-9)

    assert ar["materials_fact"] == pytest.approx(18921.024, rel=1e-9)
    assert ar["materials_deviation"] == pytest.approx(-1078.976, rel=1e-9)
    assert ar["materials_deviation_pct"] == pytest.approx(-5.39488, rel=1e-9)


def test_default_basis_is_cost():
    """База не указана — считаем по себестоимости, как у сводных до этой функции."""
    calc = calc_summary(SECTIONS, OVERRIDES)
    assert calc["target_basis"] == "cost"
    assert _sections(calc)["АР"]["works_fact"] == pytest.approx(17932.53125, rel=1e-9)


def test_deviation_in_vat_basis_uses_section_tax():
    """База «с НДС»: факт — сумма раздела после его собственного налога."""
    calc = calc_summary(SECTIONS, {**OVERRIDES, "target_basis": "with_vat"})
    ar = _sections(calc)["АР"]

    assert ar["works_fact"] == pytest.approx(20981.0615625, rel=1e-9)
    assert ar["works_deviation"] == pytest.approx(5981.0615625, rel=1e-9)
    assert ar["materials_fact"] == pytest.approx(22137.59808, rel=1e-9)
    assert ar["materials_deviation"] == pytest.approx(2137.59808, rel=1e-9)


def test_section_without_target_has_no_deviation():
    """У «ОВ» цели по работам нет — отклонения нет, а не ноль."""
    ov = _sections(calc_summary(SECTIONS, OVERRIDES))["ОВ"]
    assert ov["target_works"] is None
    assert ov["works_deviation"] is None
    assert ov["works_deviation_pct"] is None
    assert ov["target_materials"] == pytest.approx(40000)
    assert ov["materials_deviation"] == pytest.approx(125, rel=1e-9)


def test_totals_count_only_sections_with_target():
    """ИТОГО сравнивает факт тех же разделов, у которых цель задана."""
    calc = calc_summary(SECTIONS, OVERRIDES)

    # Работы: цель есть только у «АР».
    assert calc["targets_total_works"] == pytest.approx(15000)
    assert calc["targets_fact_works"] == pytest.approx(17932.53125, rel=1e-9)
    assert calc["targets_deviation_works"] == pytest.approx(2932.53125, rel=1e-9)

    # Материалы: цели у обоих разделов.
    assert calc["targets_total_materials"] == pytest.approx(60000)
    assert calc["targets_fact_materials"] == pytest.approx(59046.024, rel=1e-9)
    assert calc["targets_deviation_materials"] == pytest.approx(-953.976, rel=1e-9)
    assert calc["targets_deviation_materials_pct"] == pytest.approx(-1.58996, rel=1e-9)


def test_object_target_compares_with_total_for_customer():
    calc = calc_summary(SECTIONS, OVERRIDES)
    assert calc["target_total_for_customer"] == pytest.approx(200000)
    assert calc["total_deviation"] == pytest.approx(22647.819977202656, rel=1e-9)
    assert calc["total_deviation_pct"] == pytest.approx(11.32390998860133, rel=1e-9)


def test_zero_target_gives_deviation_but_no_percent():
    """Цель 0 — заданная цель: отклонение равно факту, процента нет."""
    calc = calc_summary(
        [{**BASE_SECTIONS[1], "target_works": 0}],
        {"coefficient": 1, "target_total_for_customer": 0},
    )
    section = calc["section_totals"][0]
    assert section["target_works"] == pytest.approx(0)
    assert section["works_deviation"] == pytest.approx(3999.96, rel=1e-9)
    assert section["works_deviation_pct"] is None
    assert calc["total_deviation_pct"] is None


def test_negative_target_is_treated_as_absent():
    """Отрицательной цели не бывает — считаем, что цели нет."""
    calc = calc_summary(
        [{**BASE_SECTIONS[1], "target_works": -100}],
        {"coefficient": 1, "target_total_for_customer": -5},
    )
    assert calc["section_totals"][0]["target_works"] is None
    assert calc["section_totals"][0]["works_deviation"] is None
    assert calc["target_total_for_customer"] is None
    assert calc["total_deviation"] is None


def test_target_from_json_string_is_a_number():
    """Цель могла приехать из JSON строкой — считаем её числом."""
    calc = calc_summary(
        [{**BASE_SECTIONS[1], "target_works": "4000"}],
        {"coefficient": 1},
    )
    section = calc["section_totals"][0]
    assert section["target_works"] == pytest.approx(4000)
    assert section["works_deviation"] == pytest.approx(-0.04, abs=1e-9)


def test_summary_without_targets_is_unchanged():
    """Сводная без целей: целей нет, отклонений нет, остальные числа прежние."""
    calc = calc_summary(BASE_SECTIONS, BASE_OVERRIDES)
    assert calc["has_section_targets"] is False
    assert calc["target_total_for_customer"] is None
    assert calc["total_deviation"] is None
    assert all(s["target_works"] is None for s in calc["section_totals"])
    assert calc["total_for_customer"] == pytest.approx(222647.81997720266, rel=1e-9)


def test_has_section_targets_notices_a_single_target():
    calc = calc_summary(SECTIONS, OVERRIDES)
    assert calc["has_section_targets"] is True


def test_empty_summary_does_not_crash():
    calc = calc_summary([], {"target_total_for_customer": 100})
    assert calc["targets_total_works"] is None
    assert calc["total_deviation"] == pytest.approx(-100, rel=1e-9)


# ---------------------------------------------------------------------------
# Хранение целей (Фаза 2)
# ---------------------------------------------------------------------------
#
# Цель — атрибут раздела сводной, как ставка налога: живёт в
# `summary_estimates.sections[i]` и едет тем же путём. Проверяем, что путь
# сквозной: цель не режется схемой, переживает сохранение бланка и смену
# версии раздела, а цель по объекту доезжает до карточки проекта и списка.

import pytest_asyncio
from sqlalchemy import select

from app.models.estimate_version import EstimateVersion
from app.models.project import Project
from app.models.summary_estimate import SummaryEstimate
from app.models.summary_section_doc import SummarySectionDoc
from app.models.task import Task
from app.models.user import User
from app.models.workflow_card import WorkflowCard
from app.utils.auth import create_access_token, hash_password

_MODELS = (SummarySectionDoc, SummaryEstimate, EstimateVersion,
           WorkflowCard, Task, Project, User)


def _auth(user_id: int, role: str = "project_manager") -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id, role, 'pm1')}"}


def _rows() -> list:
    return [
        {"id": "row-1", "lineage_id": "row-1", "num": 1, "type": "work",
         "name": "Демонтаж", "unit": "м2", "qty": 10, "price_work": 1000,
         "price_material": None, "cost": 10000, "selected": False},
        {"id": "row-2", "lineage_id": "row-2", "num": 2, "type": "material",
         "name": "Гипсокартон", "unit": "лист", "qty": 20, "price_work": None,
         "price_material": 500, "cost": 10000, "selected": False},
    ]


@pytest_asyncio.fixture
async def targets_env(db_session, fake_s3):
    """Проект → карточка со сметой (две версии) → сводная с одним разделом."""
    for model in _MODELS:
        await db_session.execute(model.__table__.delete())
    await db_session.commit()

    pm1 = User(username="pm1", role="project_manager", full_name="Иванов",
               password_hash=hash_password("p1"))
    db_session.add(pm1)
    await db_session.flush()

    project = Project(name="Объект", owner_id=pm1.id)
    db_session.add(project)
    await db_session.flush()

    task = Task(owner_id=pm1.id, user_role="project_manager",
                task_type="ESTIMATE_FROM_LIST", status="completed",
                input_files=[], input_file_data=[], chat_history=[],
                project_id=str(project.id))
    db_session.add(task)
    await db_session.flush()

    v1 = EstimateVersion(task_id=str(task.id), version_number=0,
                         version_label="original", version_display_name="Исходная смета",
                         rows=_rows(), file_slot="estimate",
                         task_type="ESTIMATE_FROM_LIST")
    v2 = EstimateVersion(task_id=str(task.id), version_number=1,
                         version_label="v1", version_display_name="V1 — Оптимизация",
                         rows=_rows(), file_slot="estimate",
                         task_type="ESTIMATE_FROM_LIST")
    db_session.add_all([v1, v2])
    await db_session.flush()

    card = WorkflowCard(project_id=str(project.id), name="АР", stage="estimate",
                        estimate_task_id=str(task.id))
    db_session.add(card)
    await db_session.flush()

    summary = SummaryEstimate(
        project_id=str(project.id),
        sections=[{
            "card_id": str(card.id), "card_name": "АР",
            "version_id": str(v1.id), "version_display_name": "Исходная смета",
            "rows": _rows(),
        }],
        overrides={},
    )
    db_session.add(summary)
    await db_session.commit()

    yield {"pm1": pm1.id, "project_id": str(project.id), "card_id": str(card.id),
           "v1": str(v1.id), "v2": str(v2.id)}

    for model in _MODELS:
        await db_session.execute(model.__table__.delete())
    await db_session.commit()


async def _stored(db_session, env) -> SummaryEstimate:
    db_session.expire_all()
    res = await db_session.execute(
        select(SummaryEstimate).where(SummaryEstimate.project_id == env["project_id"]))
    return res.scalar_one()


def _section_payload(env, **extra) -> dict:
    return {"card_id": env["card_id"], "card_name": "АР",
            "version_id": env["v1"], "version_display_name": "Исходная смета",
            "rows": [], **extra}


@pytest.mark.asyncio
async def test_section_target_survives_save(async_client, db_session, targets_env):
    """Цель раздела доезжает до хранилища через обычное сохранение бланка."""
    resp = await async_client.put(
        f"/api/projects/{targets_env['project_id']}/summary",
        json={"sections": [_section_payload(targets_env, target_works=15000,
                                            target_materials=20000)]},
        headers=_auth(targets_env["pm1"]))
    assert resp.status_code == 200, resp.text

    stored = await _stored(db_session, targets_env)
    assert stored.sections[0]["target_works"] == 15000
    assert stored.sections[0]["target_materials"] == 20000
    # Строки раздела бланк не переписывает — писатель у них один.
    assert len(stored.sections[0]["rows"]) == 2


@pytest.mark.asyncio
async def test_blank_settings_keep_target_basis_and_object_target(
    async_client, db_session, targets_env
):
    """Схема настроек не режет базу целей и цель по объекту."""
    resp = await async_client.put(
        f"/api/projects/{targets_env['project_id']}/summary",
        json={"overrides": {"target_basis": "with_vat",
                            "target_total_for_customer": "250000"}},
        headers=_auth(targets_env["pm1"]))
    assert resp.status_code == 200, resp.text
    assert resp.json()["overrides"]["target_basis"] == "with_vat"

    stored = await _stored(db_session, targets_env)
    assert stored.overrides["target_basis"] == "with_vat"
    assert float(stored.overrides["target_total_for_customer"]) == pytest.approx(250000)


@pytest.mark.asyncio
async def test_unknown_target_basis_is_rejected(async_client, targets_env):
    """База целей — только «с/с» или «с НДС»: опечатка не должна тихо сохраниться."""
    resp = await async_client.put(
        f"/api/projects/{targets_env['project_id']}/summary",
        json={"overrides": {"target_basis": "потом решим"}},
        headers=_auth(targets_env["pm1"]))
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_target_survives_section_version_change(
    async_client, db_session, targets_env
):
    """Сменили версию раздела — строки новые, цель прежняя."""
    await async_client.put(
        f"/api/projects/{targets_env['project_id']}/summary",
        json={"sections": [_section_payload(targets_env, target_works=15000)]},
        headers=_auth(targets_env["pm1"]))

    resp = await async_client.post(
        f"/api/projects/{targets_env['project_id']}/summary",
        json={"sections": [{"card_id": targets_env["card_id"],
                            "version_id": targets_env["v2"]}]},
        headers=_auth(targets_env["pm1"]))
    assert resp.status_code == 201, resp.text

    stored = await _stored(db_session, targets_env)
    assert stored.sections[0]["version_id"] == targets_env["v2"]
    assert stored.sections[0]["target_works"] == 15000


@pytest.mark.asyncio
async def test_removing_section_removes_its_target(
    async_client, db_session, targets_env
):
    """Раздел убрали — цель ушла с ним, сиротой не осталась."""
    await async_client.put(
        f"/api/projects/{targets_env['project_id']}/summary",
        json={"sections": [_section_payload(targets_env, target_works=15000)]},
        headers=_auth(targets_env["pm1"]))

    resp = await async_client.post(
        f"/api/projects/{targets_env['project_id']}/summary",
        json={"sections": []}, headers=_auth(targets_env["pm1"]))
    assert resp.status_code == 201, resp.text
    assert (await _stored(db_session, targets_env)).sections == []


@pytest.mark.asyncio
async def test_object_target_reaches_project_card_and_list(
    async_client, targets_env
):
    """Цель по объекту видна там же, где сводная сумма: на карточке и в списке."""
    await async_client.put(
        f"/api/projects/{targets_env['project_id']}/summary",
        json={"overrides": {"target_total_for_customer": "250000"},
              "total_for_customer": "300000"},
        headers=_auth(targets_env["pm1"]))

    card = await async_client.get(
        f"/projects/{targets_env['project_id']}", headers=_auth(targets_env["pm1"]))
    assert card.status_code == 200, card.text
    assert card.json()["summary_target_total"] == pytest.approx(250000)

    listing = await async_client.get("/projects", headers=_auth(targets_env["pm1"]))
    assert listing.status_code == 200, listing.text
    row = next(p for p in listing.json() if p["id"] == targets_env["project_id"])
    assert row["summary_target_total"] == pytest.approx(250000)
    assert row["summary_total"] == pytest.approx(300000)


@pytest.mark.asyncio
async def test_project_without_target_reports_none(async_client, targets_env):
    """Цели нет — на карточке ничего не появляется."""
    card = await async_client.get(
        f"/projects/{targets_env['project_id']}", headers=_auth(targets_env["pm1"]))
    assert card.json()["summary_target_total"] is None
