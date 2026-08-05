"""Справочник комплектов материалов к каркасным работам ГКЛ/ГВЛ.

Зачем: в ЛСР ГРАНД-Сметы материалы, учтённые расценкой, по наименованиям не
раскрываются — под работой «Устройство перегородок из ГВЛ» в файле заказчика нет
ни листов, ни профилей, ни крепежа, только сумма в строке «М». Перечень берёт из
файла то, что там написано, поэтому комплект надо восстановить самим.

Почему справочником, а не запросом к ИИ: ошибка в норме расхода уезжает в каждую
смету и стоит денег на тендере. Числа здесь проверяются тестами с точным
результатом, ИИ на тех же данных каждый раз отвечает по-разному. Работы вне
справочника по-прежнему разбирает ИИ на шаге «Полнота».

**Нормы даны на 1 м² конструкции и без запаса на подрезку** (решение
2026-08-06): в таблицу попадает то же число, которое сметчик получает в уме.
Запас закладывает человек, если считает нужным.

Источник числовых норм — комплектные системы КНАУФ (С-111/С-112 для перегородок,
С-623 для облицовок, П-113 для потолков) при шаге стойки 600 мм. Значения
ориентировочные и подлежат уточнению по проекту — там, где параметр конструкции
из наименования не читается, строка это прямо говорит.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass(frozen=True)
class KitParams:
    """Параметры конструкции, вычитанные из наименования работы."""

    layers: int
    sides: int
    explicit: bool
    """Оба параметра названы в наименовании. False — часть принята по умолчанию."""


@dataclass(frozen=True)
class KitMaterial:
    """Одна позиция комплекта.

    `per_unit` — расход на 1 единицу работы: число либо функция от параметров
    конструкции (лист считается как «слои × стороны»).
    `present` — как узнать этот материал среди уже имеющихся у работы позиций.
    Сравнение по ключевым словам, а не по полному имени: заказчик пишет
    «Материалы теплоизоляционные из минеральных волокон» там, где у нас
    «Плита минераловатная».
    """

    name: str
    unit: str
    per_unit: float | Callable[[KitParams], float]
    present: Callable[[str], bool]
    source: str
    applies: Optional[Callable[[KitParams], bool]] = None
    """Позиция нужна не всегда: шурупы второго слоя — только при двухслойной обшивке."""

    def rate(self, params: KitParams) -> float:
        return self.per_unit(params) if callable(self.per_unit) else self.per_unit

    def needed(self, params: KitParams) -> bool:
        return True if self.applies is None else self.applies(params)


@dataclass(frozen=True)
class MaterialKit:
    """Конструктивная система: как её узнать и из чего она состоит."""

    id: str
    title: str
    work_unit: str
    default_layers: int
    default_sides: int
    requires_all: tuple[str, ...]
    """Все эти признаки должны найтись в наименовании работы."""
    requires_any: tuple[str, ...] = ()
    materials: tuple[KitMaterial, ...] = field(default_factory=tuple)
    source: str = ""


# ── как узнать материал среди уже имеющихся позиций ──────────────────────────

def _sheets(name: str) -> bool:
    return any(k in name for k in ("гвл", "гкл", "гипсоволок", "гипсокарт"))


def _profile(*marks: str) -> Callable[[str], bool]:
    def check(name: str) -> bool:
        if "профил" not in name:
            return False
        return any(mark in f" {name} " for mark in marks)
    return check


def _any_of(*keywords: str) -> Callable[[str], bool]:
    def check(name: str) -> bool:
        return any(k in name for k in keywords)
    return check


def _screws(size: str) -> Callable[[str], bool]:
    def check(name: str) -> bool:
        if not any(k in name for k in ("шуруп", "саморез")):
            return False
        return size in name
    return check


# ── общие позиции каркасных систем ───────────────────────────────────────────

SHEET_PLACEHOLDER = "{sheet}"
"""Имя листа обшивки известно только по наименованию работы: ГВЛ или ГКЛ.

Справочник один на оба материала — различаются они ценой, а не нормой расхода,
— поэтому имя подставляется при расчёте через `sheet_name`.
"""


def sheet_name(kind: str) -> str:
    return (
        "Лист гипсоволокнистый ГВЛ 12,5 мм"
        if kind == "ГВЛ"
        else "Лист гипсокартонный ГКЛ 12,5 мм"
    )


def _sheet_material() -> KitMaterial:
    """Обшивка. Единственная позиция, объём которой зависит от слоёв и сторон."""
    return KitMaterial(
        name=SHEET_PLACEHOLDER,
        unit="м2",
        per_unit=lambda p: float(p.layers * p.sides),
        present=_sheets,
        source="КНАУФ С-111/С-112",
    )


_FASTENERS_AND_FINISH = (
    KitMaterial(
        name="Шурупы самонарезающие TN 25",
        unit="шт",
        per_unit=20.0,
        present=_screws("25"),
        source="КНАУФ С-111, крепление первого слоя",
    ),
    KitMaterial(
        name="Шурупы самонарезающие TN 35",
        unit="шт",
        per_unit=34.0,
        present=_screws("35"),
        source="КНАУФ С-112, крепление второго слоя",
        applies=lambda p: p.layers >= 2,
    ),
    KitMaterial(
        name="Дюбель-гвоздь 6х40",
        unit="шт",
        per_unit=1.6,
        present=_any_of("дюбел"),
        source="КНАУФ С-111, крепление направляющих",
    ),
    KitMaterial(
        name="Лента армирующая для швов (серпянка)",
        unit="м",
        per_unit=1.2,
        present=_any_of("серпянк", "армирующ"),
        source="КНАУФ С-111",
    ),
    KitMaterial(
        name="Шпаклёвка гипсовая для заделки швов",
        unit="кг",
        per_unit=0.5,
        present=_any_of("шпакл", "фугенфюллер"),
        source="КНАУФ С-111",
    ),
    KitMaterial(
        name="Грунтовка глубокого проникновения",
        unit="л",
        per_unit=0.1,
        present=_any_of("грунтовк"),
        source="КНАУФ С-111",
    ),
)

_MINERAL_WOOL = KitMaterial(
    name="Плита минераловатная звукоизоляционная 50 мм",
    unit="м2",
    per_unit=1.0,
    present=_any_of("минерал", "минват", "теплоизол", "звукоизол", "вата"),
    source="КНАУФ С-112, заполнение каркаса",
)


def _partition_kit() -> tuple[KitMaterial, ...]:
    return (
        _sheet_material(),
        KitMaterial(
            name="Профиль стоечный ПС 50х50 (0,6 мм)",
            unit="м",
            per_unit=2.0,
            present=_profile(" пс", "стоеч"),
            source="КНАУФ С-111, шаг стойки 600 мм",
        ),
        KitMaterial(
            name="Профиль направляющий ПН 50х40 (0,6 мм)",
            unit="м",
            per_unit=0.8,
            present=_profile(" пн", "направляющ"),
            source="КНАУФ С-111",
        ),
        KitMaterial(
            name="Лента уплотнительная 30 мм",
            unit="м",
            per_unit=0.8,
            present=_any_of("уплотнительн", "дихтунг"),
            source="КНАУФ С-111, примыкание направляющих",
        ),
        *_FASTENERS_AND_FINISH,
        _MINERAL_WOOL,
    )


def _lining_kit() -> tuple[KitMaterial, ...]:
    return (
        _sheet_material(),
        KitMaterial(
            name="Профиль стоечный ПС 50х50 (0,6 мм)",
            unit="м",
            per_unit=2.0,
            present=_profile(" пс", "стоеч"),
            source="КНАУФ С-623, шаг стойки 600 мм",
        ),
        KitMaterial(
            name="Профиль направляющий ПН 50х40 (0,6 мм)",
            unit="м",
            per_unit=0.8,
            present=_profile(" пн", "направляющ"),
            source="КНАУФ С-623",
        ),
        KitMaterial(
            name="Кронштейн (прямой подвес) для профиля",
            unit="шт",
            per_unit=1.6,
            present=_any_of("подвес", "кронштейн"),
            source="КНАУФ С-623",
        ),
        *_FASTENERS_AND_FINISH,
    )


def _ceiling_kit() -> tuple[KitMaterial, ...]:
    return (
        _sheet_material(),
        KitMaterial(
            name="Профиль потолочный ПП 60х27 (0,6 мм)",
            unit="м",
            per_unit=2.9,
            present=_profile(" пп", "потолочн"),
            source="КНАУФ П-113, шаг несущих 500 мм",
        ),
        KitMaterial(
            name="Профиль направляющий потолочный ППН 28х27 (0,6 мм)",
            unit="м",
            per_unit=0.9,
            present=_profile(" ппн", "направляющ"),
            source="КНАУФ П-113",
        ),
        KitMaterial(
            name="Подвес прямой для профиля ПП 60х27",
            unit="шт",
            per_unit=0.7,
            present=_any_of("подвес"),
            source="КНАУФ П-113",
        ),
        KitMaterial(
            name="Соединитель одноуровневый «краб»",
            unit="шт",
            per_unit=1.7,
            present=_any_of("краб", "соединител"),
            source="КНАУФ П-113",
        ),
        *_FASTENERS_AND_FINISH,
    )


# ── справочник ───────────────────────────────────────────────────────────────
#
# Порядок важен: первое совпадение выигрывает. Потолок и облицовка стоят выше
# перегородки, потому что «Облицовка перегородок ГКЛ» — это облицовка.

def kits() -> tuple[MaterialKit, ...]:
    return (
        MaterialKit(
            id="gkl_ceiling",
            title="Подвесной потолок ГКЛ/ГВЛ по металлическому каркасу",
            work_unit="м2",
            default_layers=1,
            default_sides=1,
            requires_all=("потол",),
            requires_any=("гкл", "гвл", "гипсокарт", "гипсоволок"),
            materials=_ceiling_kit(),
            source="КНАУФ П-113",
        ),
        MaterialKit(
            id="gkl_lining",
            title="Облицовка стен ГКЛ/ГВЛ по металлическому каркасу",
            work_unit="м2",
            default_layers=1,
            default_sides=1,
            requires_all=("облицов",),
            requires_any=("гкл", "гвл", "гипсокарт", "гипсоволок"),
            materials=_lining_kit(),
            source="КНАУФ С-623",
        ),
        MaterialKit(
            id="gkl_partition",
            title="Перегородка каркасная ГКЛ/ГВЛ",
            work_unit="м2",
            default_layers=1,
            default_sides=2,
            requires_all=("перегород",),
            requires_any=("гкл", "гвл", "гипсокарт", "гипсоволок"),
            materials=_partition_kit(),
            source="КНАУФ С-111/С-112",
        ),
    )


# Работы, к которым материалы не нужны: сносим, а не строим.
STOP_WORDS = (
    "разборк", "демонтаж", "снятие", "снят", "очистк", "разрушен",
    "утилизац", "вывоз", "погрузк",
)
