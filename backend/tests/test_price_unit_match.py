"""Цена подбирается под единицу измерения позиции, а не только под название.

06.08.2026, реальная смета: «Смеси сухие … для затирки», позиция в кг, объём 30 —
цена 73 770 (это цена за тонну), стоимость 2 213 100 ₽ вместо 2 213 ₽.
«Вторая окраска стен», позиция в м2, объём 1061 — цена 18 000 (цена за 100 м2),
стоимость 19 104 480 ₽ вместо 191 045 ₽.

Название совпадало, единицу не сверял никто: ни прайс, ни кеш прошлых задач,
ни ИИ. Здесь закреплено, что теперь сверяют все трое.

Спека: specs/2026-08-06-edinica-izmereniya-v-podbore-ceny.md
"""
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.modules.setdefault("fitz", MagicMock())

from app.services.task_processor import TaskProcessor, UNIT_NOTE_KEY  # noqa: E402
from app.utils.unit_compat import (  # noqa: E402
    PRICE_CONVERTED_PREFIX,
    PRICE_UNIT_MISMATCH_PREFIX,
)


def _proc() -> TaskProcessor:
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    db.commit = AsyncMock()
    p = TaskProcessor("tid-unit", db=db)
    p.update_progress = AsyncMock(return_value=None)
    p.save_result = AsyncMock(return_value=None)
    p._save_progress_data = AsyncMock(return_value=None)
    p._result_filename = MagicMock(return_value="Смета.xlsx")
    p._check_cancelled = AsyncMock(return_value=None)
    return p


class _FakePriceSvc:
    """Прайс из одной позиции: чем ответит подбор, задаёт тест."""

    def __init__(self, work=None, material=None):
        self._work = work
        self._material = material

    def _exact_match_work(self, name):
        return self._work

    def _exact_match_material_row(self, name):
        return self._material

    def _exact_match_cache_work(self, name):
        return None

    def _exact_match_cache_material(self, name):
        return None

    # Поиск по эмбеддингам в тестах не нужен: подбор задаётся точным совпадением.
    async def batch_embedding_match_works(self, names):
        return [None] * len(names)

    async def batch_embedding_match_material_rows(self, names):
        return [None] * len(names)

    async def batch_embedding_match_cache_works(self, names):
        return [None] * len(names)

    async def batch_embedding_match_cache_materials(self, names):
        return [None] * len(names)

    def is_cache_loaded(self):
        return True


async def _run_lookup(monkeypatch, fake, items) -> tuple[dict, list[dict]]:
    """Прогнать шаг «поиск цен» и вернуть (найденное по индексу, позиции)."""
    from app.services import task_processor as tp

    monkeypatch.setattr(tp, "_price_svc", fake)

    p = _proc()
    p._run_estimate_step3 = AsyncMock(return_value=None)

    source_task = MagicMock()
    source_task.status = "completed"
    source_task.progress_data = {"items": items}
    p.db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=source_task))
    )

    task = MagicMock()
    task.user_prompt = '{"path": "B", "source_task_id": "src-1", "source_stage": 1}'
    task.progress_data = {}
    task.processing_mode = "fast"

    await p._handle_estimate_from_list(task)

    call = p._run_estimate_step3.await_args.args
    return (call[2], call[1])


# ---------------------------------------------------------------------------
# Прайс
# ---------------------------------------------------------------------------

async def test_cena_za_tonnu_v_pozicii_v_kg_pereschityvaetsya(monkeypatch):
    """Случай 405: 73 770 ₽/т в позиции в кг → 73,77 ₽/кг."""
    fake = _FakePriceSvc(material={"name": "Смеси сухие", "price": 73770.0, "unit": "т"})
    items = [{"type": "Материал", "name": "Смеси сухие", "unit": "кг", "quantity": 30}]

    matched, _ = await _run_lookup(monkeypatch, fake, items)

    assert matched[0]["material_price"] == 73.77
    assert PRICE_CONVERTED_PREFIX in matched[0][UNIT_NOTE_KEY]


async def test_cena_za_sto_kvadratov_v_pozicii_v_kvadrate(monkeypatch):
    """Случай 531: 18 000 ₽ за «100 м2» в позиции в м2 → 180 ₽/м2."""
    fake = _FakePriceSvc(work={"name": "Вторая окраска стен", "min_price": 18000.0, "unit": "100 м2"})
    items = [{"type": "Работа", "name": "Вторая окраска стен", "unit": "м2", "quantity": 1061}]

    matched, _ = await _run_lookup(monkeypatch, fake, items)

    assert matched[0]["work_price"] == 180.0
    assert PRICE_CONVERTED_PREFIX in matched[0][UNIT_NOTE_KEY]


async def test_nesvodimaya_edinica_cenu_ne_daet(monkeypatch):
    """Цена за мешок в позиции в кг не берётся: вес мешка неизвестен."""
    fake = _FakePriceSvc(material={"name": "Смеси сухие", "price": 500.0, "unit": "мешок"})
    items = [{"type": "Материал", "name": "Смеси сухие", "unit": "кг", "quantity": 30}]

    matched, out_items = await _run_lookup(monkeypatch, fake, items)

    assert matched == {}, "позиция не должна считаться найденной"
    assert PRICE_UNIT_MISMATCH_PREFIX in out_items[0][UNIT_NOTE_KEY]


async def test_sovpavshaya_edinica_beretsya_kak_ran_she(monkeypatch):
    """Единицы совпали — поведение прежнее, без пометок."""
    fake = _FakePriceSvc(work={"name": "Окраска", "min_price": 180.0, "unit": "м2"})
    items = [{"type": "Работа", "name": "Окраска", "unit": "м2", "quantity": 10}]

    matched, _ = await _run_lookup(monkeypatch, fake, items)

    assert matched[0]["work_price"] == 180.0
    assert UNIT_NOTE_KEY not in matched[0]


async def test_prays_bez_edinicy_ne_lomaet_podbor(monkeypatch):
    """В прайсе единицу не заполнили → цена берётся, как и раньше.

    Иначе весь старый прайс без единиц уехал бы в платный поиск через ИИ.
    """
    fake = _FakePriceSvc(work={"name": "Окраска", "min_price": 180.0, "unit": None})
    items = [{"type": "Работа", "name": "Окраска", "unit": "м2", "quantity": 10}]

    matched, _ = await _run_lookup(monkeypatch, fake, items)

    assert matched[0]["work_price"] == 180.0
    assert UNIT_NOTE_KEY not in matched[0]


# ---------------------------------------------------------------------------
# Кеш прошлых задач
# ---------------------------------------------------------------------------

async def test_pozicii_ishodnoy_zadachi_ne_pravyatsya(monkeypatch):
    """Причина отказа пишется в позиции сметы, а не в задачу-перечень.

    По Path B список приходит прямо из progress_data перечня — общий объект.
    Правка в нём означала бы, что расчёт сметы молча меняет чужую задачу.
    """
    fake = _FakePriceSvc(material={"name": "Смеси сухие", "price": 500.0, "unit": "мешок"})
    source_items = [{"type": "Материал", "name": "Смеси сухие", "unit": "кг", "quantity": 30}]

    matched, out_items = await _run_lookup(monkeypatch, fake, source_items)

    assert PRICE_UNIT_MISMATCH_PREFIX in out_items[0][UNIT_NOTE_KEY]
    assert UNIT_NOTE_KEY not in source_items[0], "позиция перечня осталась нетронутой"


async def test_kesh_tozhe_sveryaet_edinicu(monkeypatch):
    class _CacheSvc(_FakePriceSvc):
        def _exact_match_cache_material(self, name):
            return {"name": name, "price": 500.0, "unit": "мешок", "updated_at": None,
                    "sources": "src"}

    fake = _CacheSvc()
    items = [{"type": "Материал", "name": "Смеси сухие", "unit": "кг", "quantity": 30}]

    matched, out_items = await _run_lookup(monkeypatch, fake, items)

    assert matched == {}
    assert PRICE_UNIT_MISMATCH_PREFIX in out_items[0][UNIT_NOTE_KEY]


# ---------------------------------------------------------------------------
# Ответ ИИ (шаг 3 — общий для обычного прогона, batch и возобновления)
# ---------------------------------------------------------------------------

async def _step3(items, matched, claude_results) -> list[dict]:
    p = _proc()
    await p._run_estimate_step3(MagicMock(), items, matched, claude_results)
    return p._save_progress_data.await_args.args[0]["items"]


async def test_ii_vernul_cenu_za_meshok_cena_ne_zapisyvaetsya():
    items = [{"type": "Материал", "name": "Смеси сухие", "unit": "кг", "quantity": 30}]
    claude = {0: {"id": 0, "type": "Материал", "unit": "мешок",
                  "material_price": 500.0, "sources": "источник"}}

    saved = await _step3(items, {}, claude)

    assert saved[0]["material_price"] is None
    assert PRICE_UNIT_MISMATCH_PREFIX in saved[0]["notes"]


async def test_ii_vernul_cenu_za_sto_kvadratov_pereschityvaem():
    items = [{"type": "Работа", "name": "Окраска", "unit": "м2", "quantity": 1061}]
    claude = {0: {"id": 0, "type": "Работа", "unit": "100 м2",
                  "work_price": 18000.0, "sources": "источник"}}

    saved = await _step3(items, {}, claude)

    assert saved[0]["work_price"] == 180.0
    assert PRICE_CONVERTED_PREFIX in saved[0]["notes"]


async def test_edinica_stroki_beretsya_iz_perechnya_a_ne_ot_ii():
    """Объём посчитан в единице перечня — подменять её ответом ИИ нельзя."""
    items = [{"type": "Материал", "name": "Смеси сухие", "unit": "кг", "quantity": 30}]
    claude = {0: {"id": 0, "type": "Материал", "unit": "мешок", "material_price": 500.0}}

    saved = await _step3(items, {}, claude)

    assert saved[0]["unit"] == "кг"


async def test_prichina_otkaza_vidna_kogda_ceny_ne_nashlos():
    """Ни один источник цену не дал — в примечании причина, а не «не определена»."""
    items = [{
        "type": "Материал", "name": "Смеси сухие", "unit": "кг", "quantity": 30,
        UNIT_NOTE_KEY: f"{PRICE_UNIT_MISMATCH_PREFIX} — прайс: «мешок», позиция: «кг».",
    }]

    saved = await _step3(items, {}, {})

    assert PRICE_UNIT_MISMATCH_PREFIX in saved[0]["notes"]
    assert saved[0]["notes"] != "Цена не определена"


async def test_pometka_o_pereschete_ne_zatiraetsya_istochnikom_ceny():
    """Шаг 3 пересобирает notes под источник цены — пометка должна уцелеть."""
    items = [{"type": "Материал", "name": "Смеси сухие", "unit": "кг", "quantity": 30}]
    matched = {0: {
        "type": "Материал", "name": "Смеси сухие", "unit": "кг", "quantity": 30,
        "material_price": 73.77, "price_list_name": "Прайс",
        "_price_source_name": "Смеси сухие",
        UNIT_NOTE_KEY: f"{PRICE_CONVERTED_PREFIX}: 73770 ₽/т → 73,77 ₽/кг (прайс).",
    }}

    saved = await _step3(items, matched, {})

    assert saved[0]["material_price"] == 73.77
    assert PRICE_CONVERTED_PREFIX in saved[0]["notes"]
    assert "Смеси сухие" in saved[0]["notes"], "источник цены тоже должен остаться"


async def test_promt_trebuet_cenu_za_edinicu_pozicii():
    """Требование к ИИ живёт в промпте: без него он вернёт цену за упаковку."""
    from app.services.task_processor import PROMPT_ESTIMATE_FROM_LIST

    assert "ЕДИНИЦУ ИЗМЕРЕНИЯ" in PROMPT_ESTIMATE_FROM_LIST
    assert "мешок 25 кг" in PROMPT_ESTIMATE_FROM_LIST
