"""Единица сверяется и при доборе цен, и при пересчёте одной строки.

Основной проход сметы цену за мешок в позицию с килограммами больше не пустит,
а вот кнопки «Исправить пустые цены» и «Цена» ходят к ИИ отдельно. Если правило
живёт только в основном проходе, ошибка возвращается через кнопку — теми же
разами, только по одной строке.

Спека: specs/2026-08-06-edinica-izmereniya-v-podbore-ceny.md
"""
import pytest

from app.services import estimate_store
from app.utils.unit_compat import (
    PRICE_CONVERTED_PREFIX,
    PRICE_UNIT_MISMATCH_PREFIX,
    prices_for_unit,
)


# ---------------------------------------------------------------------------
# Общее правило для ответа ИИ
# ---------------------------------------------------------------------------

def test_cena_za_meshok_v_pozicii_v_kg_ne_beretsya():
    work, material, notes = prices_for_unit(None, 500.0, "мешок", "кг")
    assert material is None
    assert work is None
    assert any(PRICE_UNIT_MISMATCH_PREFIX in n for n in notes)


def test_cena_za_tonnu_pereschityvaetsya():
    work, material, notes = prices_for_unit(None, 73770.0, "т", "кг")
    assert material == 73.77
    assert any(PRICE_CONVERTED_PREFIX in n for n in notes)


def test_sovpavshaya_edinica_bez_pometok():
    work, material, notes = prices_for_unit(180.0, None, "м2", "м2")
    assert work == 180.0
    assert notes == []


def test_ii_ne_ukazal_edinicu_cena_beretsya():
    """ИИ не вернул unit — возражать нечем, поведение прежнее."""
    work, material, notes = prices_for_unit(180.0, None, None, "м2")
    assert work == 180.0
    assert notes == []


# ---------------------------------------------------------------------------
# Добор пустых цен и кнопка «Цена» — на готовой смете в БД
# ---------------------------------------------------------------------------

SMES_KG = {"type": "Материал", "name": "Смеси сухие", "unit": "кг",
           "quantity": 30, "material_price": None}
OKRASKA_M2 = {"type": "Работа", "name": "Окраска", "unit": "м2",
              "quantity": 1061, "work_price": None}


async def _estimate(processor_env, items: list[dict]):
    """Готовая смета: рабочая версия с этими позициями (как после расчёта)."""
    task = await processor_env.task("ESTIMATE_FROM_LIST", status="completed")
    await estimate_store.write_items(processor_env.db, task, [dict(it) for it in items])
    return task


# (позиция, ответ ИИ, цена работ, цена материала, пометка, стоимость сметы)
CASES = [
    pytest.param(
        SMES_KG, {"unit": "мешок", "material_price": 500.0},
        None, None, PRICE_UNIT_MISMATCH_PREFIX, 0.0,
        id="cena-za-meshok-ne-pishetsya",
    ),
    pytest.param(
        # 1061 м2 × 180 = 190 980 + 3 % накладных = 196 709,40.
        OKRASKA_M2, {"unit": "100 м2", "work_price": 18000.0},
        180.0, None, PRICE_CONVERTED_PREFIX, 196709.4,
        id="cena-za-100-m2-pereschityvaetsya",
    ),
    pytest.param(
        # 30 кг × 73,77 = 2 213,10 + 3 % транспортных = 2 279,49.
        SMES_KG, {"unit": "т", "material_price": 73770.0},
        None, 73.77, PRICE_CONVERTED_PREFIX, 2279.49,
        id="cena-za-tonnu-pereschityvaetsya",
    ),
]


@pytest.mark.parametrize("item, answer, work_price, material_price, note, cost", CASES)
async def test_dobor_pustyh_cen_sveryaet_edinicu(
    processor_env, claude_api, item, answer, work_price, material_price, note, cost,
):
    """«Исправить пустые цены»: цена ИИ приводится к единице строки или не берётся."""
    task = await _estimate(processor_env, [item])
    claude_api({"items": [{"id": 0, "type": item["type"], **answer}]})

    await processor_env.processor(task).fix_empty_prices()

    task = await processor_env.reload(task)
    assert task.status == "completed"
    (row,) = await processor_env.estimate_items(task)
    assert row["work_price"] == work_price
    assert row["material_price"] == material_price
    assert row["unit"] == item["unit"]
    assert note in row["notes"]
    assert float(task.cost) == cost


@pytest.mark.parametrize("item, answer, work_price, material_price, note, cost", CASES)
async def test_knopka_cena_sveryaet_edinicu(
    async_client, user_token, processor_env, claude_api,
    item, answer, work_price, material_price, note, cost,
):
    """Кнопка «Цена» (одна строка): то же правило единиц, что и в расчёте сметы.

    Цена за мешок в строке с килограммами — пусто и причина; сводимая единица —
    пересчёт, и цена встаёт в смету.
    """
    task = await _estimate(processor_env, [item])
    claude_api({"sources": "источник", "notes": "", **answer})

    r = await async_client.post(
        f"/tasks/{task.id}/estimate-items/0/reprice",
        headers={"Authorization": user_token},
    )

    assert r.status_code == 200, r.text
    data = r.json()
    assert data["work_price"] == work_price
    assert data["material_price"] == material_price
    assert note in data["notes"]
    task = await processor_env.reload(task)
    (row,) = await processor_env.estimate_items(task)
    assert row["work_price"] == work_price
    assert row["material_price"] == material_price
    assert float(task.cost) == cost
