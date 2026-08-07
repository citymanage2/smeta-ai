"""Расчёт бланка «Сводная» — тот же, что на экране.

Бланк считается на клиенте (`calcSummary` в `stores/summaryEditorStore.ts`) —
он и остаётся эталоном: там человек видит числа и принимает по ним решения.
Этот модуль повторяет его формулы один в один, чтобы скачиваемый файл сводной
показывал ровно то же.

Так было не всегда: до Фазы 9 генератор файла считал по формулам прежней версии
бланка — без коэффициента, без налогов разделов, без восьми из восемнадцати
строк расходов, с другой прибылью и старым НДС. На одном наборе данных экран
показывал 222 647,82 ₽, а файл — 143 713,91 ₽.

Регресс закрыт тестами `backend/tests/test_summary_calc.py`: набор данных и
ожидаемые числа взяты из фронтового регресс-теста.
"""
from __future__ import annotations

from typing import Any, Optional

# Ставка НДС, «зашитая» в самом бланке: суммы разделов приходят с НДС, а строки
# ручного ввода — без него.
VAT = 1.22

# Все восемнадцать строк расходов бланка в порядке показа.
FIXED_ROW_KEYS = (
    "works", "materials", "transport", "cleanup", "overhead",
    "daily_workers", "bank_guarantee", "cleaning", "ppr", "commissioning",
    "construction_control", "author_supervision", "passes", "site_office",
    "travel", "rp", "housing_rent", "workers_transport",
)

# Русские названия строк — для файла (в бланке они те же).
FIXED_ROW_LABELS = {
    "works": "Работы",
    "materials": "Материалы",
    "transport": "Транспортные расходы",
    "cleanup": "Уборка и вывоз мусора",
    "overhead": "Накладные",
    "daily_workers": "Разнорабочие ежедневно",
    "bank_guarantee": "Банковская гарантия",
    "cleaning": "Клининг",
    "ppr": "Рабочая документация (ППР)",
    "commissioning": "Разнорабочие мусор",
    "construction_control": "Строительный контроль",
    "author_supervision": "Авторский надзор",
    "passes": "Пропуски, корочки",
    "site_office": "Бытовка",
    "travel": "Командировочные",
    "rp": "РП",
    "housing_rent": "Аренда жилья",
    "workers_transport": "Транспортные расходы люди",
}

# Ручные строки хранятся без НДС; ключ настройки → ключ строки бланка.
_MANUAL_ROWS = (
    ("bank_guarantee", "bank_guarantee_cost"),
    ("cleaning", "cleaning_cost"),
    ("ppr", "ppr_cost"),
    ("commissioning", "commissioning_cost"),
    ("construction_control", "construction_control_cost"),
    ("author_supervision", "author_supervision_cost"),
    ("passes", "passes_cost"),
    ("site_office", "site_office_cost"),
    ("travel", "travel_cost"),
    ("rp", "rp_cost"),
    ("housing_rent", "housing_rent_cost"),
    ("workers_transport", "workers_transport_cost"),
)

_DEFAULTS = {
    "coefficient": 1.0,
    "transport_pct": 3.0,
    "cleanup_pct": 3.0,
    "overhead_pct": 3.0,
    "contingency_pct": 2.0,
    "profit_pct": 20.0,
    "vat_full_cost_pct": 22.0,
    "tax_pct": 2.0,
}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _section_tax(section: dict, side: str) -> float:
    """Ставка налога половины раздела: у работ и материалов она своя.

    `tax_pct` — одна ставка на обе половины, как было до раздельных налогов.
    Сохранённые раньше сводные лежат в базе именно так, поэтому она остаётся
    запасным значением. То же правило на экране — `sectionTaxPct` в
    `stores/summaryEditorStore.ts`.
    """
    value = section.get(f"tax_pct_{side}")
    if value is None or value == "":
        value = section.get("tax_pct")
    return _num(value)


def _billable_qty(qty: Any) -> float:
    """Объём для умножения на цену: вычет (< 0) стоимости не даёт.

    То же правило, что в `utils/negativeQty` на клиенте и в `price_coercion`
    на сервере: строка с отрицательным объёмом корректирует объём соседней
    позиции, а не является работой.
    """
    value = _num(qty)
    return value if value > 0 else 0.0


def calc_summary(sections: list, overrides: Optional[dict]) -> dict:
    """Итоги бланка «Сводная». Формулы — как в `calcSummary` на клиенте."""
    overrides = overrides or {}

    def _ov(key: str) -> float:
        return _num(overrides.get(key), _DEFAULTS.get(key, 0.0))

    coefficient = _ov("coefficient")
    hidden = set(overrides.get("hidden_fixed_rows") or [])

    # --- Разделы ---------------------------------------------------------
    section_totals: list[dict] = []
    for section in sections or []:
        works_raw = 0.0
        materials_raw = 0.0
        for row in (section.get("rows") or []):
            if str(row.get("type") or "") == "section":
                continue
            qty = _billable_qty(row.get("qty"))
            works_raw += _num(row.get("price_work")) * qty
            materials_raw += _num(row.get("price_material")) * qty

        works_raw *= coefficient
        materials_raw *= coefficient
        tax_pct_works = _section_tax(section, "works")
        tax_pct_materials = _section_tax(section, "materials")

        section_totals.append({
            "card_id": section.get("card_id"),
            "card_name": section.get("card_name") or "",
            "tax_pct_works": tax_pct_works,
            "tax_pct_materials": tax_pct_materials,
            "works_raw": works_raw,
            "materials_raw": materials_raw,
            "works_with_vat": works_raw * (VAT - tax_pct_works / 100),
            "materials_with_vat": materials_raw * (VAT - tax_pct_materials / 100),
        })

    works_with_vat = sum(s["works_with_vat"] for s in section_totals)
    materials_with_vat = sum(s["materials_with_vat"] for s in section_totals)
    base_with_vat = works_with_vat + materials_with_vat

    # --- Строки расходов --------------------------------------------------
    values_with_vat = {
        "works": works_with_vat,
        "materials": materials_with_vat,
        "transport": base_with_vat * _ov("transport_pct") / 100,
        "cleanup": base_with_vat * _ov("cleanup_pct") / 100,
        "overhead": base_with_vat * _ov("overhead_pct") / 100,
        # Разнорабочие: в настройке хранится количество людей, не сумма.
        "daily_workers": _num(overrides.get("daily_workers_cost")) * 5000,
    }
    values_without_vat = {key: values_with_vat[key] / VAT for key in values_with_vat}

    for row_key, setting_key in _MANUAL_ROWS:
        without_vat = _num(overrides.get(setting_key))
        values_without_vat[row_key] = without_vat
        values_with_vat[row_key] = without_vat * VAT

    # --- Себестоимость ----------------------------------------------------
    subtotal_with_vat = sum(
        values_with_vat[key] for key in FIXED_ROW_KEYS if key not in hidden
    )
    for custom in (overrides.get("custom_rows_before") or []):
        subtotal_with_vat += _num(custom.get("without_vat")) * VAT
    subtotal_without_vat = subtotal_with_vat / VAT

    # --- Низ бланка -------------------------------------------------------
    contingency_pct = _ov("contingency_pct")
    profit_pct = _ov("profit_pct")

    contingency_with_vat = subtotal_with_vat * contingency_pct / 100
    contingency_without_vat = subtotal_without_vat * contingency_pct / 100

    profit = (
        (profit_pct / 100) * (1 + contingency_pct / 100) * subtotal_without_vat
        / (1 - profit_pct / 100)
    ) if profit_pct != 100 else 0.0

    full_cost_without_vat = subtotal_without_vat + contingency_without_vat + profit
    vat = full_cost_without_vat * _ov("vat_full_cost_pct") / 100
    other_tax = full_cost_without_vat * _ov("tax_pct") / 100

    result = {
        "section_totals": section_totals,
        "subtotal_with_vat": subtotal_with_vat,
        "subtotal_without_vat": subtotal_without_vat,
        "contingency_with_vat": contingency_with_vat,
        "contingency_without_vat": contingency_without_vat,
        "contingency_pct": contingency_pct,
        "profit": profit,
        "profit_pct": profit_pct,
        "full_cost_without_vat": full_cost_without_vat,
        "vat": vat,
        "vat_pct": _ov("vat_full_cost_pct"),
        "other_tax": other_tax,
        "other_tax_pct": _ov("tax_pct"),
        "total_for_customer": full_cost_without_vat + vat + other_tax,
        "hidden_fixed_rows": hidden,
        "custom_rows_before": list(overrides.get("custom_rows_before") or []),
        "custom_rows_after": list(overrides.get("custom_rows_after") or []),
    }
    for key in FIXED_ROW_KEYS:
        result[f"{key}_with_vat"] = values_with_vat[key]
        result[f"{key}_without_vat"] = values_without_vat[key]
    return result
