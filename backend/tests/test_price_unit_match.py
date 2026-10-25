"""Цена подбирается под единицу измерения позиции, а не только под название.

06.08.2026, реальная смета: «Смеси сухие … для затирки», позиция в кг, объём 30 —
цена 73 770 (это цена за тонну), стоимость 2 213 100 ₽ вместо 2 213 ₽.
«Вторая окраска стен», позиция в м2, объём 1061 — цена 18 000 (цена за 100 м2),
стоимость 19 104 480 ₽ вместо 191 045 ₽.

Название совпадало, единицу не сверял никто: ни прайс, ни кеш прошлых задач,
ни ИИ. Здесь закреплено, что теперь сверяют все трое.

Каждый тест — настоящий расчёт сметы из перечня (`processor_env`): прайс и кеш
лежат в БД, подменён только ИИ, результат читается из рабочей версии сметы.

Спека: specs/2026-08-06-edinica-izmereniya-v-podbore-ceny.md
"""
import json

import pytest

from app.models.task import Task
from app.utils.unit_compat import (
    PRICE_CONVERTED_PREFIX,
    PRICE_UNIT_MISMATCH_PREFIX,
)
from tests.helpers.prices import axis, similar

SMES_KG = {"type": "Материал", "name": "Смеси сухие", "unit": "кг", "quantity": 30}


def _no_price_from_ai(kwargs: dict) -> dict:
    """ИИ цены не нашёл: позиция вернулась без цены (и в доборе — тоже)."""
    return {"items": [{"id": 0, "type": "Материал", "name": "Смеси сухие", "unit": "кг",
                       "material_price": None}]}


# ---------------------------------------------------------------------------
# Прайс
# ---------------------------------------------------------------------------

async def test_cena_za_tonnu_v_pozicii_v_kg_pereschityvaetsya(processor_env, price_db, claude_api):
    """Случай 405: 73 770 ₽/т в позиции в кг → 73,77 ₽/кг, а не 2 213 100 ₽ стоимости."""
    price_db.material("Смеси сухие", unit="т", price=73770.0)
    ai = claude_api()  # цена нашлась в прайсе — в ИИ позиция не уходит
    task = await processor_env.estimate_task(
        [{"type": "Материал", "name": "Смеси сухие", "unit": "кг", "quantity": 30}]
    )

    task = await processor_env.run(task)

    assert task.status == "completed"
    (item,) = await processor_env.estimate_items(task)
    assert item["material_price"] == 73.77
    assert PRICE_CONVERTED_PREFIX in item["notes"]
    # 30 кг × 73,77 = 2 213,10 + 3 % транспортных = 2 279,49.
    assert float(task.cost) == 2279.49
    assert ai.calls == []


async def test_cena_za_sto_kvadratov_v_pozicii_v_kvadrate(processor_env, price_db, claude_api):
    """Случай 531: 18 000 ₽ за «100 м2» в позиции в м2 → 180 ₽/м2."""
    price_db.work("Вторая окраска стен", unit="100 м2", prices={"Подрядчик": 18000.0})
    ai = claude_api()
    task = await processor_env.estimate_task(
        [{"type": "Работа", "name": "Вторая окраска стен", "unit": "м2", "quantity": 1061}]
    )

    task = await processor_env.run(task)

    assert task.status == "completed"
    (item,) = await processor_env.estimate_items(task)
    assert item["work_price"] == 180.0
    assert item["unit"] == "м2"
    assert PRICE_CONVERTED_PREFIX in item["notes"]
    # 1061 м2 × 180 = 190 980 + 3 % накладных = 196 709,40 — а не 19 млн.
    assert float(task.cost) == 196709.4
    assert ai.calls == []


@pytest.mark.parametrize("price_unit", ["м2", None], ids=["edinica-sovpala", "v-prayse-bez-edinicy"])
async def test_sovpavshaya_ili_pustaya_edinica_beretsya_kak_ran_she(
    processor_env, price_db, claude_api, price_unit,
):
    """Единицы совпали — цена берётся без пометок.

    Единицу в прайсе не заполнили — тоже берётся, как и раньше: иначе весь
    старый прайс без единиц уехал бы в платный поиск через ИИ.
    """
    price_db.work("Окраска", unit=price_unit, prices={"Подрядчик": 180.0})
    ai = claude_api()
    task = await processor_env.estimate_task(
        [{"type": "Работа", "name": "Окраска", "unit": "м2", "quantity": 10}]
    )

    task = await processor_env.run(task)

    (item,) = await processor_env.estimate_items(task)
    assert item["work_price"] == 180.0
    assert item["price_list_name"] == "Прайс"
    assert PRICE_CONVERTED_PREFIX not in (item["notes"] or "")
    assert PRICE_UNIT_MISMATCH_PREFIX not in (item["notes"] or "")
    assert ai.calls == []


async def test_pometka_o_pereschete_ne_zatiraetsya_istochnikom_ceny(
    processor_env, price_db, claude_api,
):
    """Примечание строки называет позицию прайса — пометка о пересчёте рядом уцелела.

    Шаг сборки сметы пишет в примечание источник цены заново; пометка о
    пересчёте дописывается после и не должна им затираться.
    """
    price_db.work("Окраска стен вторая", unit="100 м2", prices={"Подрядчик": 18000.0},
                  vector=axis(0))
    price_db.knows("Вторая окраска стен", similar(0.97, to=0))
    claude_api()
    task = await processor_env.estimate_task(
        [{"type": "Работа", "name": "Вторая окраска стен", "unit": "м2", "quantity": 10}]
    )

    task = await processor_env.run(task)

    (item,) = await processor_env.estimate_items(task)
    assert item["work_price"] == 180.0
    assert "Окраска стен вторая" in item["notes"], "источник цены остался в примечании"
    assert PRICE_CONVERTED_PREFIX in item["notes"]


# ---------------------------------------------------------------------------
# Несводимая единица: прайс и кеш прошлых задач
# ---------------------------------------------------------------------------

def _put_price_per_bag(price_db, source: str) -> None:
    if source == "прайс":
        price_db.material("Смеси сухие", unit="мешок", price=500.0)
    else:
        price_db.cache_material("Смеси сухие", unit="мешок", price=500.0)


@pytest.mark.parametrize("source", ["прайс", "кеш"])
async def test_nesvodimaya_edinica_cenu_ne_daet(processor_env, price_db, claude_api, source):
    """Цена за мешок в позиции в кг не берётся: вес мешка неизвестен.

    Позиция идёт к следующему источнику — ИИ, — и в смету встаёт его цена за кг.
    """
    _put_price_per_bag(price_db, source)
    ai = claude_api({"items": [{
        "id": 0, "type": "Материал", "name": "Смеси сухие", "unit": "кг",
        "material_price": 75.0, "sources": "источник",
    }]})
    task = await processor_env.estimate_task([dict(SMES_KG)])

    task = await processor_env.run(task)

    assert task.status == "completed"
    assert "Смеси сухие" in ai.prompt(0), "позиция ушла в ИИ, а не взята из прайса"
    (item,) = await processor_env.estimate_items(task)
    assert item["material_price"] == 75.0
    assert item["price_list_name"] == "Интернет"
    # 30 кг × 75 = 2 250 + 3 % транспортных = 2 317,50 (с ценой за мешок было бы 15 450).
    assert float(task.cost) == 2317.5


@pytest.mark.parametrize("source", ["прайс", "кеш"])
async def test_prichina_otkaza_vidna_kogda_ceny_ne_nashlos(
    processor_env, price_db, claude_api, source,
):
    """Ни один источник цену не дал — в примечании причина, а не «не определена»."""
    _put_price_per_bag(price_db, source)
    claude_api(_no_price_from_ai, repeat=True)
    task = await processor_env.estimate_task([dict(SMES_KG)])

    task = await processor_env.run(task)

    assert task.status == "completed"
    (item,) = await processor_env.estimate_items(task)
    assert item["material_price"] is None
    assert PRICE_UNIT_MISMATCH_PREFIX in item["notes"]
    assert "мешок" in item["notes"] and "кг" in item["notes"], "названы обе единицы"


async def test_pozicii_ishodnoy_zadachi_ne_pravyatsya(processor_env, price_db, claude_api):
    """Причина отказа пишется в позиции сметы, а не в задачу-перечень.

    По Path B список приходит прямо из progress_data перечня — общий объект.
    Правка в нём означала бы, что расчёт сметы молча меняет чужую задачу: в
    сессии расчёта лежит тот же объект перечня, и любая его запись (или
    следующая смета из того же перечня в этой сессии) унесла бы чужую пометку.
    """
    price_db.material("Смеси сухие", unit="мешок", price=500.0)
    claude_api(_no_price_from_ai, repeat=True)
    task = await processor_env.estimate_task([dict(SMES_KG)])
    source = await processor_env.db.get(
        Task, json.loads(task.user_prompt)["source_task_id"],
    )
    await price_db.load()

    # Без `run()`: он перечитывает всё из БД, а смотреть надо на объект в сессии.
    await processor_env.processor(task).process()

    assert source.progress_data["items"] == [SMES_KG], "позиция перечня осталась нетронутой"
    (item,) = await processor_env.estimate_items(task)
    assert PRICE_UNIT_MISMATCH_PREFIX in item["notes"], "пометка — в позиции сметы"


# ---------------------------------------------------------------------------
# Ответ ИИ
# ---------------------------------------------------------------------------

async def test_ii_vernul_cenu_za_meshok_cena_ne_zapisyvaetsya(processor_env, claude_api):
    """Прайс цены не знает, ИИ нашёл цену за мешок — в смету она не идёт."""
    ai = claude_api({"items": [{
        "id": 0, "type": "Материал", "name": "Смеси сухие", "unit": "мешок",
        "material_price": 500.0, "sources": "источник",
    }]})
    task = await processor_env.estimate_task(
        [{"type": "Материал", "name": "Смеси сухие", "unit": "кг", "quantity": 30}]
    )

    task = await processor_env.run(task)

    assert task.status == "completed"
    (item,) = await processor_env.estimate_items(task)
    assert item["material_price"] is None
    assert item["unit"] == "кг"
    assert PRICE_UNIT_MISMATCH_PREFIX in item["notes"]
    assert len(ai.calls) == 1, "цена за мешок — ответ, а не пропуск: повторного запроса нет"


async def test_ii_vernul_cenu_za_sto_kvadratov_pereschityvaem(processor_env, claude_api):
    """ИИ ответил ценой за «100 м2» — в строке м2 цена за м2, единица и объём перечня."""
    claude_api({"items": [{
        "id": 0, "type": "Работа", "name": "Окраска", "unit": "100 м2",
        "work_price": 18000.0, "sources": "источник",
    }]})
    task = await processor_env.estimate_task(
        [{"type": "Работа", "name": "Окраска", "unit": "м2", "quantity": 1061}]
    )

    task = await processor_env.run(task)

    (item,) = await processor_env.estimate_items(task)
    assert item["work_price"] == 180.0
    # Объём посчитан в единице перечня — подменять её ответом ИИ нельзя.
    assert item["unit"] == "м2"
    assert item["quantity"] == 1061
    assert PRICE_CONVERTED_PREFIX in item["notes"]
    assert float(task.cost) == 196709.4
