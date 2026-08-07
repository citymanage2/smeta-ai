"""Журнал корректировок: что система посчитала и что человек поставил вместо.

План: plans/2026-08-07-obuchenie-na-korrektirovkah.md, Фаза 1.

Единственный источник записи — `document_service.apply_rows`: правка попадает в
журнал ровно тогда, когда человек нажал «Применить», и ровно в том виде, в
каком её уже посчитал `diff_rows`. Второй проход по строкам здесь не делается
специально: сопоставление строк живёт в одном месте, иначе журнал и история
разошлись бы в том, что считать изменением.

Три правила, без которых журнал врёт:

1. **Только ручная правка.** Проверка единиц, коэффициент, откат, оптимизация и
   миграция идут через тот же `apply_rows` — это система правит саму себя, и
   сигналом об ошибке они не являются. Отсекаются по `operation_type`.
2. **Только первое касание ячейки** считается ошибкой системы. `apply_rows`
   сравнивает новые строки с текущими рабочими, а не с тем, что выдал ИИ:
   вторая правка той же ячейки дала бы «было 2500 → стало 2400», где 2500 —
   уже человеческое число. Такие сигналы пишутся с `is_first_touch = false`.
3. **Цена берётся из строки, а не с экрана.** В строке лежит исходная цена, на
   экране — умноженная на коэффициент документа (правило 3 CLAUDE.md).

Запись идёт отдельной транзакцией после того, как правка уже сохранена: журнал
полезен, но правка документа важнее, и его сбой не имеет права её отменить.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.correction_signal import CorrectionSignal

logger = structlog.get_logger()

# Операция, которая означает «человек поправил руками». Всё остальное — система.
MANUAL_OPERATION = "document_edit"

# Потолок на одно применение: вставка целого файла в редактор не должна
# порождать десятки тысяч записей. Превышение не молчаливое — пишется в лог.
MAX_SIGNALS_PER_APPLY = 5000

_TYPE_LABELS = {
    "работа": "work", "работы": "work", "work": "work",
    "материал": "material", "материалы": "material", "material": "material",
    "раздел": "section", "section": "section",
}

# Имена колонок перечня и полноты, из которых берём единицу и тип строки.
# Сравнение — по «схлопнутому» ключу: в файлах заказчика встречаются
# «Ед. изм», «Ед.изм.», «Единица измерения».
_UNIT_KEYS = {"едизм", "единица", "единицаизмерения", "ед"}
_TYPE_KEYS = {"тип", "видработ", "вид"}


def _squash(key: str) -> str:
    return "".join(ch for ch in str(key).lower() if ch.isalnum())


def _cells(row: Any) -> dict:
    if not isinstance(row, dict):
        return {}
    cells = row.get("cells")
    return cells if isinstance(cells, dict) else {}


def _cell_by_keys(row: Any, keys: set) -> Optional[str]:
    for key, value in _cells(row).items():
        if _squash(key) in keys:
            text = str(value or "").strip()
            if text:
                return text
    return None


def _row_type(row: Any, row_format: str) -> Optional[str]:
    raw = (
        _cell_by_keys(row, _TYPE_KEYS) if row_format == "generic"
        else (row.get("type") if isinstance(row, dict) else None)
    )
    if raw is None:
        return None
    return _TYPE_LABELS.get(str(raw).strip().lower())


def _row_unit(row: Any, row_format: str) -> Optional[str]:
    if row_format == "generic":
        return _cell_by_keys(row, _UNIT_KEYS)
    if not isinstance(row, dict):
        return None
    unit = str(row.get("unit") or "").strip()
    return unit or None


def _price_source(row: Any) -> Optional[str]:
    """Откуда система взяла цену: имя прайса или пометка веб-поиска."""
    if not isinstance(row, dict):
        return None
    source = str(row.get("price_list_name") or "").strip()
    return source or None


def _as_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_number(value: Any) -> Optional[Decimal]:
    """Число для агрегатов. Нечисловое значение — не ошибка, просто None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, ValueError, AttributeError):
        return None
    return number if number.is_finite() else None


def _truncate(value: Optional[str], limit: int) -> Optional[str]:
    if value is None:
        return None
    return value[:limit]


async def _known_cells(db: AsyncSession, task_id: str, document_kind: str) -> set:
    """Ячейки задачи, по которым сигнал уже писали — для «первого касания».

    Один запрос на применение: проверять каждую ячейку отдельно значило бы
    сотни запросов на одно нажатие «Применить».
    """
    rows = await db.execute(
        select(CorrectionSignal.row_key, CorrectionSignal.field).where(
            CorrectionSignal.task_id == task_id,
            CorrectionSignal.document_kind == document_kind,
        )
    )
    return {(row_key, field) for row_key, field in rows.all()}


async def record_edit_signals(
    db: AsyncSession,
    *,
    task_id: str,
    document_kind: str,
    row_format: str,
    changes: list,
    old_rows: list,
    new_rows: list,
    user_id: Optional[int],
    user_name: Optional[str],
) -> int:
    """Записать сигналы по уже посчитанным изменениям. Возвращает их число.

    Никогда не бросает: журнал не имеет права уронить сохранение правки.
    """
    try:
        return await _record(
            db, task_id=task_id, document_kind=document_kind, row_format=row_format,
            changes=changes, old_rows=old_rows, new_rows=new_rows,
            user_id=user_id, user_name=user_name,
        )
    except Exception as error:  # noqa: BLE001 — журнал не важнее правки
        logger.warning(
            "correction_signals_failed",
            task_id=task_id, kind=document_kind, error=str(error),
        )
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return 0


async def _record(
    db: AsyncSession,
    *,
    task_id: str,
    document_kind: str,
    row_format: str,
    changes: list,
    old_rows: list,
    new_rows: list,
    user_id: Optional[int],
    user_name: Optional[str],
) -> int:
    if not changes:
        return 0

    if len(changes) > MAX_SIGNALS_PER_APPLY:
        logger.info(
            "correction_signals_capped",
            task_id=task_id, kind=document_kind,
            changes=len(changes), kept=MAX_SIGNALS_PER_APPLY,
        )
        changes = changes[:MAX_SIGNALS_PER_APPLY]

    new_by_key = _index_rows(new_rows)
    old_by_key = _index_rows(old_rows)
    known = await _known_cells(db, task_id, document_kind)

    signals: list[CorrectionSignal] = []
    for change in changes:
        if not isinstance(change, dict):
            continue
        field = change.get("field_key")
        row_key = change.get("row_key")
        if not field or not row_key:
            continue

        # Строку берём ту, что есть: у удалённой остаётся только прежняя.
        row = new_by_key.get(row_key)
        if row is None:
            row = old_by_key.get(row_key)

        cell = (str(row_key), str(field))
        signals.append(CorrectionSignal(
            task_id=task_id,
            document_kind=document_kind,
            row_key=_truncate(str(row_key), 80),
            row_name=_as_text(change.get("row_name")),
            row_type=_row_type(row, row_format),
            unit=_truncate(_row_unit(row, row_format), 50),
            field=_truncate(str(field), 200),
            previous_value=_as_text(change.get("previous")),
            new_value=_as_text(change.get("new")),
            previous_num=_as_number(change.get("previous")),
            new_num=_as_number(change.get("new")),
            is_first_touch=cell not in known,
            price_source=_price_source(row),
            user_id=user_id,
            user_name=user_name,
        ))
        known.add(cell)

    if not signals:
        return 0

    db.add_all(signals)
    await db.commit()
    return len(signals)


def _index_rows(rows: list) -> dict:
    """Строки по тому же ключу, каким их сопоставляет `diff_rows`."""
    indexed: dict = {}
    for idx, row in enumerate(rows or []):
        key = None
        if isinstance(row, dict):
            raw = row.get("row_id") or row.get("id")
            key = str(raw) if raw is not None else None
        indexed[key if key is not None else f"__pos_{idx}"] = row
    return indexed
