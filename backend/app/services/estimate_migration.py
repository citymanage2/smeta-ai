"""Перевод смет на единый источник правды — общая логика.

До Фазы 5 плана `2026-08-02-edinyy-redaktor-tablic.md` смета жила в двух местах:
`task.progress_data['items']` (что выдал расчёт) и `EstimateVersion.rows` (что
видит редактор). Они молча расходились. Правда теперь одна — рабочая версия.

Этот модуль создаёт версию тем сметам, у которых её нет, и показывает те, где
две стороны разошлись. **Единственное необратимое действие во всём плане**,
поэтому:

  * по умолчанию — только отчёт, ничего не меняется;
  * смета с расхождением НЕ мигрируется сама: она ждёт решения человека;
  * повторный запуск ничего не делает — операция идемпотентна;
  * перед перезаписью строк обе стороны целиком сохраняются в историю задачи.

Логика живёт здесь, а не в `scripts/`, потому что запускается из двух мест:
из админки (`routers/admin.py`) и из консольного скрипта
`scripts/migrate_estimate_items.py`, который остаётся запасным путём.
"""
from __future__ import annotations

import uuid as _uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.history import TaskHistory
from app.models.task import Task
from app.services import estimate_store
from app.utils.estimate_rows import (
    items_signature,
    items_to_rows,
    items_total,
    rows_to_items,
)


ESTIMATE_TASK_TYPE = "ESTIMATE_FROM_LIST"

# Что случилось с каждой сметой.
STATUS_EMPTY = "empty"                    # позиций нет — мигрировать нечего
STATUS_EXCLUDED = "excluded"              # задача в списке исключений
STATUS_NEEDS_VERSION = "needs_version"    # версии нет, создаётся из позиций
STATUS_IN_SYNC = "in_sync"                # оба хранилища совпадают
STATUS_CONFLICT = "conflict"              # разошлись, решает человек
STATUS_RESOLVED = "resolved"              # расхождение разобрано по --prefer

_STATUS_LABEL = {
    STATUS_EMPTY: "нет позиций",
    STATUS_EXCLUDED: "исключена",
    STATUS_NEEDS_VERSION: "нужна версия",
    STATUS_IN_SYNC: "совпадает",
    STATUS_CONFLICT: "РАСХОЖДЕНИЕ",
    STATUS_RESOLVED: "расхождение разобрано",
}


@dataclass
class Entry:
    task_id: str
    task_name: str
    status: str
    items_count: int = 0
    version_count: int = 0
    diff_count: int = 0
    items_total: float = 0.0
    version_total: float = 0.0
    # Разбор расхождения: по одному числу «расходится позиций» решение принять
    # нельзя — непонятно, изменились цифры или строки просто переставлены.
    only_order: bool = False
    same_totals: bool = False
    samples: list = field(default_factory=list)


@dataclass
class Report:
    entries: list = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    applied: bool = False

    def add(self, entry: Entry) -> None:
        self.entries.append(entry)
        self.counts[entry.status] = self.counts.get(entry.status, 0) + 1


def comparable(items: list) -> list:
    """Слепок сметы в том виде, в каком она будет храниться.

    Сравнивать «что выдал ИИ» со «строками редактора» напрямую нельзя: это
    разные поколения записи одного и того же. Расчёт хранит тип так, как его
    назвал ИИ («работы»), и ноль в количестве; редактор — приведённое к своему
    виду («Работа») и пустоту вместо нуля. На боевых данных шесть смет из
    девяти «расходились» именно так — при итогах, совпадающих до рубля.

    Поэтому сравнивается не сырое с записанным, а **то, что миграция записала
    бы**, с тем, что уже записано: обе стороны проходят одно приведение.
    """
    signature = items_signature(rows_to_items(items_to_rows(items)))
    # Ноль и пустое количество — одно и то же: обе строки дают нулевую
    # стоимость и пустую ячейку в файле.
    return [(t, n, u, qty or None, w, m) for t, n, u, qty, w, m in signature]


def _opcodes(left: list, right: list) -> list:
    """Выравнивание двух смет строка к строке.

    Пропущенная строка сдвигает всё, что идёт за ней: сравнение «первая с
    первой» показывало 618 расхождений там, где не хватало пяти строк.
    `autojunk` отключён — иначе на сметах длиннее двухсот строк часто
    встречающиеся строки молча выпадают из сравнения.
    """
    return SequenceMatcher(None, left, right, autojunk=False).get_opcodes()


def _diff_count(left: list, right: list) -> int:
    """Сколько строк расходится между двумя копиями сметы."""
    a, b = comparable(left), comparable(right)
    return sum(
        max(i2 - i1, j2 - j1)
        for tag, i1, i2, j1, j2 in _opcodes(a, b)
        if tag != "equal"
    )


SAMPLE_LIMIT = 3


def _money(value) -> str:
    """Число так, как человек читает его в смете. Числа нет — прочерк."""
    if value is None:
        return "—"
    return f"{value:,.2f}".replace(",", " ")


def _row_text(sig: tuple) -> str:
    """Строка сметы одной фразой: количество, единица и обе цены.

    Количества и цен может не быть вовсе — так выглядит заголовок раздела.
    Раньше количество печаталось безусловно, и одна такая строка роняла отчёт
    по всем сметам.
    """
    _type, _name, unit, qty, work, material = sig
    parts = []
    if qty is not None:
        parts.append(f"{_money(qty)} {unit}".strip())
    elif unit:
        parts.append(unit)
    if work:
        parts.append(f"работа {_money(work)}")
    if material:
        parts.append(f"материал {_money(material)}")
    return ", ".join(parts) if parts else "без количества и цен"


# Поля слепка строки в том порядке, в каком они лежат в `items_signature`.
_FIELDS = (
    (0, "тип строки"),
    (1, "название"),
    (2, "единица"),
    (3, "количество"),
    (4, "цена работы"),
    (5, "цена материала"),
)


def _text(value) -> str:
    return f"«{value}»" if value else "пусто"


def _what_changed(sig_a: tuple, sig_b: tuple) -> str:
    """Назвать поля, которыми строки отличаются, и обе величины.

    Без этого пример выглядел как две одинаковые строки: расхождение сидело в
    том, чего отчёт не показывал.
    """
    parts = []
    for index, label in _FIELDS:
        left, right = sig_a[index], sig_b[index]
        if left == right:
            continue
        show = _money if index >= 3 else _text
        parts.append(f"{label}: расчёт {show(left)}, редактор {show(right)}")
    return "; ".join(parts) if parts else "строки одинаковые"


def _sample(sig_a: Optional[tuple], sig_b: Optional[tuple]) -> dict:
    """Одно различие так, как его прочтёт человек."""
    if sig_a is None:
        return {
            "name": sig_b[1] or "(без названия)",
            "what": "строки нет в расчёте — она есть только в редакторе",
            "items": "строки нет", "version": _row_text(sig_b),
        }
    if sig_b is None:
        return {
            "name": sig_a[1] or "(без названия)",
            "what": "строки нет в редакторе — она есть только в расчёте",
            "items": _row_text(sig_a), "version": "строки нет",
        }
    return {
        "name": sig_a[1] or sig_b[1] or "(без названия)",
        "what": _what_changed(sig_a, sig_b),
        "items": _row_text(sig_a), "version": _row_text(sig_b),
    }


def describe_diff(items: list, version_items: list) -> dict:
    """Объяснить расхождение словами, а не числом.

    Отвечает на вопросы, без которых человек не может решить, чью сторону
    брать: одинаковые ли деньги, одинаковый ли набор строк, сколько строк
    разошлось и что именно в них разное. Примеров даётся не больше трёх —
    отчёт должен читаться, а не превращаться в простыню.

    Строки сопоставляются выравниванием, а не по номеру: иначе одна пропавшая
    строка делает «разошедшимися» все, что идут за ней.
    """
    left, right = comparable(items), comparable(version_items)
    same_totals = round(items_total(items), 2) == round(items_total(version_items), 2)
    # Набор строк тот же, отличается только порядок: перезаписывать нечего.
    only_order = sorted(left, key=repr) == sorted(right, key=repr)

    samples: list = []
    diff_count = 0
    for tag, i1, i2, j1, j2 in _opcodes(left, right):
        if tag == "equal":
            continue
        width = max(i2 - i1, j2 - j1)
        diff_count += width
        for offset in range(width):
            if len(samples) >= SAMPLE_LIMIT:
                break
            samples.append(_sample(
                left[i1 + offset] if i1 + offset < i2 else None,
                right[j1 + offset] if j1 + offset < j2 else None,
            ))

    return {
        "only_order": only_order,
        "same_totals": same_totals,
        "diff_count": diff_count,
        "items_rows": len(left),
        "version_rows": len(right),
        "samples": samples,
    }


async def _backup(db: AsyncSession, task: Task, rows: list, items: list) -> None:
    """Сохранить обе стороны целиком — единственный способ вернуться назад."""
    db.add(TaskHistory(
        id=str(_uuid.uuid4()),
        task_id=str(task.id),
        operation_type="estimate_migration",
        slot=estimate_store.ESTIMATE_SLOT,
        description=(
            "Перевод сметы на единый источник правды: строки версии заменены "
            "позициями расчёта. Обе стороны сохранены здесь."
        ),
        previous_value={"rows": rows, "items": items},
        new_value={"migrated_at": datetime.now(timezone.utc).isoformat()},
        document_kind="estimate",
    ))


async def migrate_estimates(
    db: AsyncSession,
    *,
    apply: bool = False,
    exclude: Optional[set] = None,
    prefer: Optional[str] = None,
) -> Report:
    """Пройти по всем сметам. Без `apply=True` не меняет ничего.

    `prefer` разбирает расхождения: `items` — победили позиции расчёта,
    `version` — победили строки редактора (версия и так правда, действий нет).
    Без него смета с расхождением остаётся нетронутой.
    """
    exclude = {str(x) for x in (exclude or set())}
    report = Report(applied=apply)

    res = await db.execute(
        select(Task).where(Task.task_type == ESTIMATE_TASK_TYPE).order_by(Task.created_at)
    )
    for task in res.scalars().all():
        task_id = str(task.id)
        name = task.name or "(без названия)"

        if task_id in exclude:
            report.add(Entry(task_id, name, STATUS_EXCLUDED))
            continue

        items = list((task.progress_data or {}).get("items") or [])
        version = await estimate_store.get_working_version(db, task_id)
        version_items = rows_to_items(version.rows) if version is not None else []

        if not items and version is None:
            report.add(Entry(task_id, name, STATUS_EMPTY))
            continue

        if version is None:
            entry = Entry(
                task_id, name, STATUS_NEEDS_VERSION,
                items_count=len(items), items_total=items_total(items),
            )
            if apply:
                await estimate_store.ensure_working_version(
                    db, task, items_to_rows(items), commit=False,
                )
            report.add(entry)
            continue

        if not items or comparable(items) == comparable(version_items):
            report.add(Entry(
                task_id, name, STATUS_IN_SYNC,
                items_count=len(items), version_count=len(version_items),
                items_total=items_total(items),
                version_total=items_total(version_items),
            ))
            continue

        explained = describe_diff(items, version_items)
        entry = Entry(
            task_id, name, STATUS_CONFLICT,
            items_count=len(items), version_count=len(version_items),
            diff_count=explained["diff_count"],
            items_total=items_total(items), version_total=items_total(version_items),
            only_order=explained["only_order"], same_totals=explained["same_totals"],
            samples=explained["samples"],
        )

        if apply and prefer == "items":
            await _backup(db, task, list(version.rows or []), items)
            await estimate_store.write_rows(db, task, items_to_rows(items), commit=False)
            entry.status = STATUS_RESOLVED
        elif apply and prefer == "version":
            # Версия уже является источником правды — записывать нечего.
            entry.status = STATUS_RESOLVED

        report.add(entry)

    if apply:
        await db.commit()
    return report


async def resolve_conflict(
    db: AsyncSession,
    task_id: str,
    prefer: str,
) -> Entry:
    """Разобрать расхождение по ОДНОЙ смете.

    В консольном скрипте `--prefer` применялся ко всем конфликтам разом. В
    интерфейсе так нельзя: у каждой сметы своя история, и «взять из расчёта»
    для одной может быть верным решением, а для другой — потерей правок
    человека. Поэтому сторона-победитель выбирается для конкретной сметы.
    """
    task = await db.get(Task, str(task_id))
    if task is None or task.task_type != ESTIMATE_TASK_TYPE:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Смета не найдена")

    items = list((task.progress_data or {}).get("items") or [])
    version = await estimate_store.get_working_version(db, str(task.id))
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="У этой сметы ещё нет рабочей версии — сначала создайте её",
        )

    version_items = rows_to_items(version.rows)
    entry = Entry(
        str(task.id), task.name or "(без названия)", STATUS_RESOLVED,
        items_count=len(items), version_count=len(version_items),
        diff_count=_diff_count(items, version_items),
        items_total=items_total(items), version_total=items_total(version_items),
    )

    if prefer == "items":
        await _backup(db, task, list(version.rows or []), items)
        await estimate_store.write_rows(db, task, items_to_rows(items), commit=False)
        await db.commit()
    elif prefer == "version":
        # Версия и так источник правды — записывать нечего, решение просто
        # фиксируем в отчёте.
        pass
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Выберите, чью сторону считать верной: расчёта или редактора",
        )

    return entry


def report_to_dict(report: Report) -> dict:
    """Отчёт в виде, пригодном для показа на экране."""
    return {
        "applied": report.applied,
        "counts": dict(report.counts),
        "labels": dict(_STATUS_LABEL),
        "entries": [
            {
                "task_id": e.task_id,
                "task_name": e.task_name,
                "status": e.status,
                "items_count": e.items_count,
                "version_count": e.version_count,
                "diff_count": e.diff_count,
                "items_total": round(e.items_total, 2),
                "version_total": round(e.version_total, 2),
                "only_order": e.only_order,
                "same_totals": e.same_totals,
                "items_rows": e.items_count,
                "version_rows": e.version_count,
                "samples": e.samples,
            }
            for e in report.entries
        ],
    }
