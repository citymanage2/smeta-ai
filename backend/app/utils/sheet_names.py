"""Листы Excel: допустимые имена и группировка строк по листам.

Файл заказчика бывает разбит на несколько листов — по листу на раздел, корпус
или этап работ. Признак листа едет по всему циклу полем `sheet` у позиции и у
строки документа, а генераторы xlsx пишут по листу на группу.

Имя листа Excel принимает не любое: под запретом `: \\ / ? * [ ]`, длина больше
31 символа, пустое имя и повтор (сравнение без учёта регистра — так же
проверяет openpyxl). Приводим имя один раз здесь, чтобы четыре генератора
(перечень, смета, оптимизация, выгрузка) не разошлись в правилах.

Приведённое имя — то же самое, что попадает в строку документа и на вкладку
редактора: документ пересобирается из файла и обратно, и разные имена на
вкладке и на листе означали бы, что после первого сохранения вкладки
переименовались сами.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Optional

# Больше 31 символа Excel не принимает.
SHEET_TITLE_LIMIT = 31
# Имя листа, когда исходное пустое или состоит из одних запрещённых символов.
DEFAULT_SHEET_TITLE = "Лист"
# Поле, в котором строка и позиция несут свой лист.
SHEET_FIELD = "sheet"

_FORBIDDEN = re.compile(r"[:\\/?*\[\]]")
_SPACES = re.compile(r"\s+")


def _clean(name: Any) -> str:
    text = _FORBIDDEN.sub(" ", "" if name is None else str(name))
    # Апостроф по краям Excel тоже не принимает.
    text = _SPACES.sub(" ", text).strip().strip("'").strip()
    return text or DEFAULT_SHEET_TITLE


def safe_sheet_title(name: Any, used: Optional[set] = None) -> str:
    """Имя листа, пригодное для Excel и не совпадающее с уже занятыми.

    `used` — множество занятых имён в нижнем регистре; функция сама добавляет
    туда выданное имя, поэтому один и тот же набор можно прогонять подряд.
    """
    text = _clean(name)
    title = text[:SHEET_TITLE_LIMIT].strip() or DEFAULT_SHEET_TITLE

    if used is None:
        return title

    if title.lower() not in used:
        used.add(title.lower())
        return title

    # Совпало с уже занятым — добавляем номер, не выходя за предел длины.
    for number in range(2, 1000):
        suffix = f" ({number})"
        base = text[: SHEET_TITLE_LIMIT - len(suffix)].strip() or DEFAULT_SHEET_TITLE
        candidate = f"{base}{suffix}"
        if candidate.lower() not in used:
            used.add(candidate.lower())
            return candidate

    # Тысяча листов с одним именем — такого файла не бывает, но молча писать
    # поверх чужого листа нельзя.
    raise ValueError(f"Не удалось подобрать имя листа для {name!r}")


def sheet_of(record: Any, key: str = SHEET_FIELD) -> Optional[str]:
    """Лист строки или позиции. `None` — документ из одного безымянного листа.

    `key` отличается у строк выгрузки: там ключи полей приходят из колонок
    документа, и служебное поле помечено `__`, чтобы не столкнуться с колонкой,
    которую заказчик назвал «sheet».
    """
    if not isinstance(record, dict):
        return None
    value = record.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def group_by_sheet(records: Iterable[Any], key: str = SHEET_FIELD) -> list:
    """Строки по листам в порядке первого появления: `[(имя, строки), ...]`.

    Строки без листа собираются в группу с именем `None` — так документы,
    созданные до появления вкладок, остаются одним безымянным листом.
    """
    order: list = []
    groups: dict = {}
    for record in records or []:
        title = sheet_of(record, key)
        if title not in groups:
            groups[title] = []
            order.append(title)
        groups[title].append(record)
    return [(title, groups[title]) for title in order]


def sheet_titles(records: Iterable[Any], key: str = SHEET_FIELD) -> list:
    """Имена листов в порядке появления, без строк без листа."""
    return [title for title, _ in group_by_sheet(records, key) if title is not None]
