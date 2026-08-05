"""Разворачивание комплекта материалов к каркасной работе по нормам расхода.

Проблема: под работой «Устройство перегородок из ГВЛ … с двухслойной обшивкой с
обеих сторон», 5,475 м², в перечне нет ни листов, ни профилей, ни крепежа — в ЛСР
они скрыты внутри расценки. А если бы лист и попал, объём взяли бы равным объёму
работы, тогда как правильный — 5,475 × 2 слоя × 2 стороны = 21,9 м².

Здесь считается детерминированно, без ИИ: справочник `app/data/material_kits.py`
задаёт норму на 1 м² конструкции, наименование работы даёт число слоёв и сторон,
объём получается умножением. Числа закреплены тестами.

Правила, принятые 2026-08-06:

* объём **чистый**, без запаса на подрезку — то же число, что сметчик получает
  в уме;
* материал, уже имеющийся у работы, **не задваивается**; расходящийся объём
  заказчика **не правится**, а помечается — решает человек;
* пустой объём у имеющегося материала проставить можно: терять там нечего;
* параметры конструкции, не названные в наименовании, берутся типовыми, и строка
  об этом прямо говорит.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Optional

from app.data.material_kits import (
    STOP_WORDS,
    KitParams,
    MaterialKit,
    SHEET_PLACEHOLDER,
    kits,
    sheet_name,
)

KIT_ADDED_PREFIX = "Добавлено по норме"
KIT_MISMATCH_PREFIX = "Расхождение с нормой"

# Расхождение объёма в пределах этой доли — подрезка, округление или другой
# типоразмер, а не ошибка. Помечать такое значит приучить человека к шуму.
MISMATCH_TOLERANCE = 0.05

_MATERIAL_LABELS = ("материал", "material", "материалы")
_WORK_LABELS = ("работа", "work", "работы")
_SECTION_LABELS = ("раздел", "section")

_UNIT_ALIASES = {
    "м2": "м2", "м²": "м2", "кв.м": "м2", "кв м": "м2", "м^2": "м2", "m2": "м2",
    "м3": "м3", "м³": "м3", "куб.м": "м3", "куб м": "м3",
    "м": "м", "пог.м": "м", "пог м": "м", "п.м": "м", "м.п": "м", "мп": "м", "пм": "м",
    "шт": "шт", "штук": "шт", "шт.": "шт",
    "кг": "кг", "л": "л", "т": "т",
}


@dataclass(frozen=True)
class MatchedKit:
    kit: MaterialKit
    params: KitParams
    sheet_kind: str
    """ГВЛ или ГКЛ — что именно указано в наименовании работы."""


@dataclass
class ExpandResult:
    items: list[dict]
    added: int = 0
    flagged: int = 0
    handled_works: list[str] = field(default_factory=list)
    """Работы, комплект которых посчитан здесь. ИИ их трогать не должен."""


# ── нормализация ─────────────────────────────────────────────────────────────

def _norm(text: object) -> str:
    """Имя в сравнимый вид: нижний регистр, ё→е, только буквы, цифры и пробелы."""
    lowered = str(text or "").lower().replace("ё", "е")
    cleaned = re.sub(r"[^0-9a-zа-я]+", " ", lowered)
    return " ".join(cleaned.split())


def _unit(text: object) -> str:
    raw = str(text or "").strip().lower().replace("ё", "е").rstrip(".")
    raw = raw.replace(" ", "")
    for alias, canonical in _UNIT_ALIASES.items():
        if raw == alias.replace(" ", "").rstrip("."):
            return canonical
    return raw


def _qty(value: object) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace(",", ".").replace(" ", "").replace("\xa0", "")
    if not text:
        return None
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return number


def _fmt(value: Decimal | float | int) -> str:
    """Число для человека: 21.9 → «21,9», 5.475 → «5,475»."""
    decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    text = format(decimal_value.normalize(), "f")
    return text.replace(".", ",")


def _plural(count: int, one: str, few: str, many: str) -> str:
    tail_100 = count % 100
    tail_10 = count % 10
    if 11 <= tail_100 <= 14:
        word = many
    elif tail_10 == 1:
        word = one
    elif 2 <= tail_10 <= 4:
        word = few
    else:
        word = many
    return f"{count} {word}"


def _item_type(item: dict) -> str:
    value = str(item.get("type", "") or "").strip().lower()
    if value in _MATERIAL_LABELS:
        return "material"
    if value in _WORK_LABELS:
        return "work"
    if value in _SECTION_LABELS:
        return "section"
    return value


# ── распознавание конструкции ────────────────────────────────────────────────

def _read_layers(name: str) -> tuple[int, bool]:
    """Число слоёв обшивки.

    «Одинарный металлический каркас» — про каркас, а не про обшивку, поэтому
    смотрим только на слова со слоем.
    """
    if re.search(r"(трех|трёх)слойн|три слоя|3 слоя", name):
        return 3, True
    if re.search(r"двухслойн|двойной обшивк|два слоя|2 слоя|в два слоя", name):
        return 2, True
    if re.search(r"однослойн|одинарной обшивк|один слой|1 слой|в один слой", name):
        return 1, True
    return 0, False


def _read_sides(name: str) -> tuple[int, bool]:
    if re.search(r"с обеих сторон|с двух сторон|двусторонн|двухсторонн", name):
        return 2, True
    if re.search(r"с одной стороны|односторонн", name):
        return 1, True
    return 0, False


def match_kit(name: str, unit: str) -> Optional[MatchedKit]:
    """Конструктивная система по наименованию работы, либо None.

    Единица обязана совпасть с той, на которую задана норма: расценка в м³ с
    нормой «на 1 м²» дала бы объём материала, умноженный не на ту величину.
    """
    normalized = _norm(name)
    if not normalized:
        return None
    if any(stop in normalized for stop in STOP_WORDS):
        return None

    canonical_unit = _unit(unit)
    for kit in kits():
        if canonical_unit != kit.work_unit:
            continue
        if not all(mark in normalized for mark in kit.requires_all):
            continue
        if kit.requires_any and not any(mark in normalized for mark in kit.requires_any):
            continue

        layers, layers_explicit = _read_layers(normalized)
        sides, sides_explicit = _read_sides(normalized)
        params = KitParams(
            layers=layers or kit.default_layers,
            sides=sides or kit.default_sides,
            explicit=layers_explicit and sides_explicit,
        )
        kind = "ГВЛ" if ("гвл" in normalized or "гипсоволок" in normalized) else "ГКЛ"
        return MatchedKit(kit=kit, params=params, sheet_kind=kind)
    return None


# ── расчёт объёма ────────────────────────────────────────────────────────────

def _calc_qty(work_qty: Decimal, rate: float, unit: str) -> Decimal:
    """Объём материала = объём работы × норма. Без запаса на подрезку.

    Штуки не дробят: 8,76 дюбеля — это 9 дюбелей. Это не запас, а неделимость
    единицы, поэтому округление вверх, а не отбрасывание.
    """
    value = work_qty * Decimal(str(rate))
    if unit == "шт":
        return value.to_integral_value(rounding=ROUND_CEILING)
    return value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def _qty_out(value: Decimal, unit: str) -> float | int:
    return int(value) if unit == "шт" else float(value)


def _formula_note(matched: MatchedKit, work_qty: Decimal, rate: float,
                  qty: Decimal, unit: str, is_sheet: bool, source: str) -> str:
    params = matched.params
    if is_sheet:
        factor = (
            f"{_fmt(rate)} "
            f"({_plural(params.layers, 'слой', 'слоя', 'слоёв')} × "
            f"{_plural(params.sides, 'сторона', 'стороны', 'сторон')})"
        )
    else:
        factor = _fmt(rate)

    note = (
        f"{KIT_ADDED_PREFIX}: {_fmt(work_qty)} × {factor} = {_fmt(qty)} {unit}. {source}."
    )
    if not params.explicit:
        note += (
            " Слои и стороны в наименовании работы не указаны, приняты по умолчанию"
            f" ({_plural(params.layers, 'слой', 'слоя', 'слоёв')} ×"
            f" {_plural(params.sides, 'сторона', 'стороны', 'сторон')}) — проверьте."
        )
    return note


def _with_note(item: dict, note: str) -> dict:
    """Пометка встаёт первой: по её началу строка подсвечивается в редакторе."""
    existing = str(item.get("notes") or "").strip()
    item["notes"] = f"{note} | {existing}" if existing else note
    return item


# ── разворачивание ───────────────────────────────────────────────────────────

def _expand_block(work: dict, materials: list[dict], result: ExpandResult) -> list[dict]:
    """Материалы блока «работа + её материалы» после добавления комплекта."""
    matched = match_kit(work.get("name", ""), work.get("unit", ""))
    if matched is None:
        return materials

    work_qty = _qty(work.get("quantity"))
    if work_qty is None or work_qty <= 0:
        # Без объёма работы считать нечего. Нули в смете хуже пропуска: их не видно.
        return materials

    result.handled_works.append(str(work.get("name", "")))
    known = [(mat, _norm(mat.get("name"))) for mat in materials]
    sheet = work.get("sheet")
    additions: list[dict] = []

    for kit_material in matched.kit.materials:
        if not kit_material.needed(matched.params):
            continue

        rate = kit_material.rate(matched.params)
        unit = kit_material.unit
        expected = _calc_qty(work_qty, rate, unit)
        is_sheet = kit_material.name == SHEET_PLACEHOLDER
        name = sheet_name(matched.sheet_kind) if is_sheet else kit_material.name
        note = _formula_note(
            matched, work_qty, rate, expected, unit, is_sheet, kit_material.source
        )

        existing = next(
            (item for item, norm_name in known if kit_material.present(norm_name)), None
        )
        if existing is not None:
            existing_qty = _qty(existing.get("quantity"))
            if existing_qty is None or existing_qty == 0:
                # Пустой объём терять нечего — проставляем расчётный.
                existing["quantity"] = _qty_out(expected, unit)
                _with_note(existing, note)
                result.added += 1
            elif _unit(existing.get("unit")) == unit and expected > 0:
                deviation = abs(existing_qty - expected) / expected
                if deviation > Decimal(str(MISMATCH_TOLERANCE)):
                    _with_note(existing, (
                        f"{KIT_MISMATCH_PREFIX}: по норме {_fmt(expected)} {unit}, "
                        f"в файле {_fmt(existing_qty)} {_unit(existing.get('unit'))} — проверьте."
                    ))
                    result.flagged += 1
            continue

        addition = {
            "type": "Материал",
            "name": name,
            "unit": unit,
            "quantity": _qty_out(expected, unit),
            "notes": note,
        }
        if sheet:
            addition["sheet"] = sheet
        additions.append(addition)
        result.added += 1

    return materials + additions


def expand_completeness_items(items: list[dict]) -> ExpandResult:
    """Перечень с дописанными комплектами материалов к каркасным работам.

    Порядок сохраняется: комплект встаёт в конец блока своей работы — после её
    собственных материалов и перед следующей работой или разделом.
    """
    result = ExpandResult(items=[])
    if not items:
        return result

    output: list[dict] = []
    current_work: Optional[dict] = None
    current_materials: list[dict] = []

    def flush() -> None:
        nonlocal current_work, current_materials
        if current_work is None:
            output.extend(current_materials)
        else:
            output.append(current_work)
            output.extend(_expand_block(current_work, current_materials, result))
        current_work = None
        current_materials = []

    for item in items:
        if not isinstance(item, dict):
            continue
        kind = _item_type(item)
        if kind == "material":
            current_materials.append(item)
            continue
        flush()
        if kind == "work":
            current_work = item
        else:
            output.append(item)

    flush()
    result.items = output
    return result
