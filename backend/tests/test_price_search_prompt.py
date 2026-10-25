"""
Поиск цен в интернете идёт в регионе компании и с указаниями пользователя.

Цена без региона — средняя по стране, а торги — в Екатеринбурге: сумма
контракта съезжает молча. Поэтому регион закреплён в каждом запросе к ИИ, где
ищется рыночная цена: оптимизация (работа и материал), расчёт сметы, «Проставить
цены» в версиях оптимизации и кнопка «Цена» у строки сметы. Проверяется текст,
который действительно ушёл в Anthropic API (подменён только клиент API).

Указания из мастера оптимизации тоже обязаны доехать до запроса.
"""
import pytest

import app.services.price_service as ps
from app.routers.estimate_versions import _run_fill_prices_step
from app.services import estimate_store

REGION = "Екатеринбург"
WORK_ANSWER = '{"price": 500, "unit": "м2", "source": "test"}'


async def _estimate_with_unpriced_work(processor_env):
    """Готовая смета, в которой у работы нет цены."""
    task = await processor_env.task("ESTIMATE_FROM_LIST", status="completed")
    await estimate_store.write_items(processor_env.db, task, [
        {"type": "Работа", "name": "Кладка стен", "unit": "м3", "quantity": 12, "work_price": None},
    ])
    return task


# Почему поиск цены оптимизации помечен xfail: `price_service` зовёт свою
# обёртку `call_claude(messages, system_prompt, use_web_search)` с `task_id`,
# `db` и `is_extra` (с коммита 4f14718, 06.08.2026). Обёртка падает на
# TypeError, ошибку глотает `except Exception`, и поиск цены в интернете при
# оптимизации молча не выполняется вовсе — запрос до Anthropic не доходит.
# Старые тесты подменяли саму обёртку с `**kwargs` и этого не видели.
# Починят обёртку — strict-маркер упадёт как XPASS: тогда его просто снять.
WEB_SEARCH_BROKEN = pytest.mark.xfail(
    strict=True,
    reason="price_service.call_claude не принимает task_id/db/is_extra — "
           "веб-поиск оптимизации не уходит в API (см. комментарий выше)",
)


async def _optimization_work(processor_env):
    await ps._web_search_work_price("Укладка кирпича", user_prompt="")


async def _optimization_material(processor_env):
    await ps._web_search_material_price("Кирпич М150", user_prompt="")


async def _estimate_from_list(processor_env):
    task = await processor_env.estimate_task(
        [{"type": "Работа", "name": "Кладка стен", "unit": "м3", "quantity": 12}],
    )
    await processor_env.run(task)


async def _fill_prices_step(processor_env):
    task = await _estimate_with_unpriced_work(processor_env)
    await _run_fill_prices_step(str(task.id))


def _sent_with_region(ai) -> bool:
    return bool(ai.calls) and all(REGION in ai.prompt(i) for i in range(len(ai.calls)))


@pytest.mark.parametrize(
    "search",
    [
        pytest.param(_optimization_work, marks=WEB_SEARCH_BROKEN, id="optimization-work"),
        pytest.param(_optimization_material, marks=WEB_SEARCH_BROKEN, id="optimization-material"),
        pytest.param(_estimate_from_list, id="estimate"),
        pytest.param(_fill_prices_step, id="fill-prices"),
    ],
)
async def test_web_price_search_names_the_region(processor_env, claude_api, search):
    ai = claude_api('{"items": []}', repeat=True)

    await search(processor_env)

    assert _sent_with_region(ai), "запрос к ИИ не ушёл или ушёл без региона"


async def test_reprice_button_names_the_region(
    processor_env, claude_api, async_client, user_token,
):
    """Кнопка «Цена» у строки сметы — тот же поиск, тот же регион."""
    ai = claude_api('{"work_price": 700, "unit": "м3", "sources": "test"}')
    task = await _estimate_with_unpriced_work(processor_env)

    response = await async_client.post(
        f"/tasks/{task.id}/estimate-items/0/reprice", headers={"Authorization": user_token},
    )

    assert response.status_code == 200
    assert _sent_with_region(ai)


@pytest.mark.parametrize(
    "find, name",
    [(ps._web_search_material_price, "Кирпич М150"), (ps._web_search_work_price, "Укладка кирпича")],
    ids=["material", "work"],
)
@WEB_SEARCH_BROKEN
async def test_web_search_includes_user_prompt(claude_api, find, name):
    """Указание из мастера оптимизации попадает в запрос поиска цены."""
    ai = claude_api(WORK_ANSWER)
    user_prompt = "найди самую низкую цену от официальных дилеров"

    await find(name, user_prompt=user_prompt)

    assert user_prompt in ai.prompt(0)
