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


def _diff_count(left: list, right: list) -> int:
    """Сколько позиций расходится между двумя копиями сметы."""
    a, b = items_signature(left), items_signature(right)
    if len(a) != len(b):
        return max(len(a), len(b)) - min(len(a), len(b)) + sum(
            1 for x, y in zip(a, b) if x != y
        )
    return sum(1 for x, y in zip(a, b) if x != y)


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


def describe_diff(items: list, version_items: list) -> dict:
    """Объяснить расхождение словами, а не числом.

    Отвечает на три вопроса, без которых человек не может решить, чью сторону
    брать: одинаковые ли деньги, одинаковый ли набор строк и что именно
    разошлось. Примеров даётся не больше трёх — отчёт должен читаться, а не
    превращаться в простыню.
    """
    left, right = items_signature(items), items_signature(version_items)
    same_totals = round(items_total(items), 2) == round(items_total(version_items), 2)
    # Набор строк тот же, отличается только порядок: перезаписывать нечего.
    only_order = sorted(left, key=repr) == sorted(right, key=repr)

    samples: list = []
    for sig_a, sig_b in zip(left, right):
        if len(samples) >= SAMPLE_LIMIT:
            break
        if sig_a == sig_b:
            continue
        samples.append({
            "name": sig_a[1] or sig_b[1] or "(без названия)",
            "items": _row_text(sig_a),
            "version": _row_text(sig_b),
        })

    # Строки, которых нет на одной из сторон, — тоже расхождение.
    if len(samples) < SAMPLE_LIMIT and len(left) != len(right):
        longer, side = (left, "items") if len(left) > len(right) else (right, "version")
        for sig in longer[min(len(left), len(right)):]:
            if len(samples) >= SAMPLE_LIMIT:
                break
            samples.append({
                "name": sig[1] or "(без названия)",
                "items": _row_text(sig) if side == "items" else "строки нет",
                "version": _row_text(sig) if side == "version" else "строки нет",
            })

    return {
        "only_order": only_order,
        "same_totals": same_totals,
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

        if not items or items_signature(items) == items_signature(version_items):
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
            diff_count=_diff_count(items, version_items),
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
