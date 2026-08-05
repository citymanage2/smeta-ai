"""Номер позиции исходной сметы → позиция перечня.

ИИ разбирает чанк строк Гранд-сметы в позиции перечня, но номер позиции ЛСР
через него не гоняется: выдуманный номер хуже пустой ячейки, а лишнее поле в
промпте стоит токенов на каждом чанке. Вместо этого позиции сопоставляются со
строками того же чанка здесь, в коде — по наименованию, которое промпт запрещает
менять.

Сопоставление внутри чанка: одинаковые наименования в разных разделах не
перепутаются, а чанк границу листа не пересекает (`file_parser.chunk_rows`).

План: plans/2026-08-06-nomer-pozicii-iz-ishodnoj-smety.md
"""
from __future__ import annotations

import re

# Наименование, короче которого совпадение по началу — совпадение случайное.
_MIN_PREFIX_LEN = 15

_SPACES = re.compile(r"\s+")


def _key(name) -> str:
    """Наименование в сравнимом виде: регистр и лишние пробелы значения не имеют."""
    return _SPACES.sub(" ", str(name or "").replace("\xa0", " ")).strip().lower()


def _exact(pool: dict, key: str):
    """Первый неиспользованный номер строки с ровно таким наименованием."""
    for entry in pool.get(key, ()):
        if not entry["used"]:
            return entry
    return None


def _by_prefix(entries: list, key: str):
    """Единственный кандидат, у которого наименование — начало другого.

    ИИ иногда обрезает хвост длинного наименования Гранд-сметы. Кандидатов
    больше одного — не берём ничего: чужой номер хуже пустой ячейки.
    """
    if len(key) < _MIN_PREFIX_LEN:
        return None

    found = None
    for entry in entries:
        if entry["used"]:
            continue
        other = entry["key"]
        if len(other) < _MIN_PREFIX_LEN:
            continue
        if not (other.startswith(key) or key.startswith(other)):
            continue
        if found is not None:
            return None
        found = entry
    return found


def attach_source_numbers(items: list, rows: list) -> None:
    """Проставить позициям `source_no` по строкам исходного файла. На месте.

    Позиции без пары поля не получают вовсе — колонка в перечне появляется,
    только если номер нашёлся хоть у кого-то.
    """
    entries: list = []
    pool: dict = {}
    for row in rows or []:
        if not isinstance(row, dict) or row.get("is_section"):
            continue
        number = str(row.get("source_no") or "").strip()
        if not number:
            continue
        entry = {"key": _key(row.get("name")), "no": number, "used": False}
        entries.append(entry)
        pool.setdefault(entry["key"], []).append(entry)

    if not entries:
        return

    for item in items or []:
        if not isinstance(item, dict):
            continue
        key = _key(item.get("name"))
        if not key:
            continue
        entry = _exact(pool, key) or _by_prefix(entries, key)
        if entry is None:
            continue
        entry["used"] = True
        item["source_no"] = entry["no"]
