"""Эталонный прайс: цены из файла становятся единственно верными.

План `plans/2026-09-02-etalonnyy-prays-iz-smety.md`.

Обычная загрузка прайса (`admin._handle_price_upload`) — это **слияние**: цены
подрядчиков по той же позиции остаются рядом с новой. Здесь наоборот: файл
объявлен эталоном, и по его позициям в прайсе должна остаться ровно одна цена —
из файла. Операция необратима и трогает общий на всех справочник, поэтому
модуль разделён на два шага, и первый ничего не меняет:

- `parse_reference_file` — что вообще написано в файле (и что из него выброшено
  и почему);
- `build_plan` — что произойдёт с прайсом: где добавим, где сотрём чужую цену и
  чью именно, а где вытеснять отказываемся.

Отказ вытеснять — не осторожность ради осторожности. Единица измерения это
часть цены, а не подпись (правило №8 CLAUDE.md): цена за мешок и цена за кг
назначены за разное, и стереть первую ради второй значит молча исказить прайс
подрядчика. Такие позиции показываются человеку, а не чинятся догадкой.
"""
import csv
import io
from typing import Optional

import openpyxl
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.price import PriceMaterial, PriceWork
from app.services import price_service
from app.services.embedding_service import normalize_name
from app.services.price_bulk import SKIP_NO_NAME, SKIP_NO_PRICE, SKIP_NOT_PRICEABLE
from app.utils.price_change import MONEY_EPS
from app.utils.price_min import ESTIMATE_CONTRACTOR
from app.utils.unit_compat import STATUS_INCOMPATIBLE, compare_units
from app.utils.unit_normalizer import unit_price_factor

logger = structlog.get_logger()

# Потолок на один файл — тот же по смыслу, что `price_bulk.MAX_ITEMS`: эталон
# это десятки позиций, а не выгрузка чужой базы целиком. Файл сверх потолка
# отклоняется целиком: молча взять первые 500 строк хуже, чем не взять ничего.
MAX_REFERENCE_ITEMS = 500

ACTION_ADD = "add"          # позиции в прайсе нет — стирать нечего
ACTION_REPRICE = "reprice"  # позиция есть — цена из файла вытеснит остальные
ACTION_BLOCKED = "blocked"  # вытеснять нельзя, решает человек

BLOCK_UNIT_MISMATCH = "ед. изм. несводима"

# Сколько кандидатов-дублей показывать на одну позицию файла.
DUPLICATE_TOP_N = 5

# Насколько порог показа дубля ниже порога, по которому цена подставляется в
# смету. Порог подбора настроен так, чтобы **не взять** чужую цену; здесь цена
# не подставляется, а показывается человеку — и скрытый дубль обходится дороже
# лишней строки в списке, потому что молча продолжит подставляться в расчёт.
DUPLICATE_MARGIN = 0.08

KIND_WORK = "work"
KIND_MATERIAL = "material"

# Что в колонке «Тип» файла сметы означает работу и материал. Всё остальное
# (раздел, пустая ячейка) ценой не является.
_TYPE_WORK = "работа"
_TYPE_MATERIAL = "материал"


class ReferenceFileError(Exception):
    """Файл нельзя принять целиком: не разобрали или он больше потолка."""


# ---------------------------------------------------------------------------
# Разбор файла
# ---------------------------------------------------------------------------

def _rows_from_bytes(data: bytes, filename: str) -> list[list]:
    """Строки файла. Из книги берётся первый лист, где есть слово «наименование»."""
    lower = filename.lower()

    if lower.endswith(".xlsx") or lower.endswith(".xls"):
        try:
            wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
        except Exception as e:  # noqa: BLE001 — наружу уходит человеческий текст
            raise ReferenceFileError(f"Не удалось прочитать книгу Excel: {e}") from e
        for sheet_name in wb.sheetnames:
            rows = [list(row) for row in wb[sheet_name].iter_rows(values_only=True)]
            if _header_index(rows) is not None:
                return rows
        raise ReferenceFileError(
            "В файле не найден заголовок с колонкой «Наименование»."
        )

    if lower.endswith(".csv") or lower.endswith(".txt"):
        text = data.decode("utf-8-sig", errors="replace")
        try:
            delimiter = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","
        return [list(row) for row in csv.reader(io.StringIO(text), delimiter=delimiter)]

    raise ReferenceFileError("Принимаются файлы Excel, CSV и TXT.")


def _header_index(rows: list[list]) -> Optional[int]:
    """Номер строки заголовка — первой, где встречается «наименование»."""
    for i, row in enumerate(rows):
        for cell in row:
            if isinstance(cell, str) and "наименование" in cell.lower():
                return i
    return None


def _columns(headers: list[str]) -> dict:
    """Заголовки → номера нужных колонок.

    «Цена работы» и «Цена материала» ищутся до общей «Цены»: в файле сметы есть
    и то и другое, и общая колонка забрала бы первую попавшуюся. «Стоимость»
    берётся только как последняя надежда простого прайса — в смете так
    называется сумма за всю позицию, а не цена за единицу.
    """
    columns: dict = {
        "name": None, "unit": None, "type": None,
        "price_work": None, "price_material": None, "price": None,
    }
    fallback_price = None

    for i, raw in enumerate(headers):
        lower = str(raw or "").strip().lower()
        if not lower:
            continue
        if "наименование" in lower or "название" in lower or lower == "name":
            if columns["name"] is None:
                columns["name"] = i
        elif lower == "тип":
            columns["type"] = i
        # Цены разбираются до единицы: заголовок «Цена работы (за ед.)» тоже
        # содержит «ед.», и проверка единицы забрала бы колонку цены себе.
        elif "цена работы" in lower or "цена работ" in lower:
            columns["price_work"] = i
        elif "цена материала" in lower or "цена матер" in lower:
            columns["price_material"] = i
        elif "цена" in lower:
            if columns["price"] is None:
                columns["price"] = i
        elif ("ед" in lower and ("изм" in lower or "." in lower)) or lower in ("ед", "unit"):
            if columns["unit"] is None:
                columns["unit"] = i
        elif "стоимость" in lower or lower == "price":
            if fallback_price is None:
                fallback_price = i

    if columns["price"] is None and columns["price_work"] is None \
            and columns["price_material"] is None:
        columns["price"] = fallback_price

    return columns


def _cell(row: list, index: Optional[int]):
    if index is None or index >= len(row):
        return None
    return row[index]


def _amount(value: object) -> Optional[float]:
    """Цена из ячейки. Ноль, пустая строка и мусор — это «цены нет»."""
    if value is None:
        return None
    text = str(value).strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if number > 0 else None


def _kind_from_type(value: object) -> Optional[str]:
    text = str(value or "").strip().lower()
    if text.startswith(_TYPE_WORK):
        return KIND_WORK
    if text.startswith(_TYPE_MATERIAL):
        return KIND_MATERIAL
    return None


def parse_reference_file(
    data: bytes,
    filename: str,
    kind: Optional[str],
) -> "tuple[list[dict], dict[str, int]]":
    """Файл → (позиции, причины пропуска).

    Поддерживаются два вида файла:

    - **смета нашего формата** — есть колонки «Цена работы (за ед.)» и «Цена
      материала (за ед.)»; тип строки читается из колонки «Тип», а при её
      отсутствии — из того, в какой колонке стоит цена. Работы и материалы
      приезжают одним файлом;
    - **простой прайс** — «Наименование / Ед. изм. / Цена»; тип в файле не
      написан, поэтому его называет человек (`kind`). Выдумывать тип по имени
      позиции нельзя: ошибка отправит цену работы в прайс материалов.
    """
    rows = _rows_from_bytes(data, filename)
    header_idx = _header_index(rows)
    if header_idx is None:
        raise ReferenceFileError("В файле не найден заголовок с колонкой «Наименование».")

    headers = [str(h).strip() if h is not None else "" for h in rows[header_idx]]
    columns = _columns(headers)
    if columns["name"] is None:
        raise ReferenceFileError("В файле не найдена колонка «Наименование».")

    split_prices = columns["price_work"] is not None or columns["price_material"] is not None
    if not split_prices:
        if columns["price"] is None:
            raise ReferenceFileError("В файле не найдена колонка с ценой.")
        if kind not in (KIND_WORK, KIND_MATERIAL):
            raise ReferenceFileError(
                "В файле не написано, где работы, а где материалы — выберите тип."
            )

    prepared: dict = {}
    skipped: dict[str, int] = {}
    accepted = 0

    def _skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    for row in rows[header_idx + 1:]:
        if not row or all(cell is None or str(cell).strip() == "" for cell in row):
            continue

        name = str(_cell(row, columns["name"]) or "").strip()

        if split_prices:
            row_kind = _kind_from_type(_cell(row, columns["type"])) if columns["type"] is not None else None
            work_price = _amount(_cell(row, columns["price_work"]))
            material_price = _amount(_cell(row, columns["price_material"]))
            if row_kind is None:
                # Колонки «Тип» нет или в ней раздел — тип подсказывает та
                # колонка, где стоит цена. Обе сразу — строка про две разные
                # позиции сразу, разбирать её догадкой мы не беремся.
                if work_price is not None and material_price is None:
                    row_kind = KIND_WORK
                elif material_price is not None and work_price is None:
                    row_kind = KIND_MATERIAL
            if row_kind is None:
                if not name:
                    _skip(SKIP_NO_NAME)
                else:
                    _skip(SKIP_NOT_PRICEABLE)
                continue
            price = work_price if row_kind == KIND_WORK else material_price
        else:
            row_kind = kind
            price = _amount(_cell(row, columns["price"]))

        if not name:
            _skip(SKIP_NO_NAME)
            continue
        if str(name).lower() in ("итого", "всего", "total"):
            continue
        if price is None:
            _skip(SKIP_NO_PRICE)
            continue

        # Цена за «100 м2» — это не цена за м2 (правило №3 плана).
        unit, factor = unit_price_factor(_cell(row, columns["unit"]))
        accepted += 1
        if accepted > MAX_REFERENCE_ITEMS:
            raise ReferenceFileError(
                f"В файле больше {MAX_REFERENCE_ITEMS} позиций — "
                "эталонный прайс рассчитан на выборку, а не на выгрузку целиком."
            )

        prepared[(row_kind, normalize_name(name))] = {
            "kind": row_kind,
            "name": name,
            "unit": unit,
            "price": round(price / factor, 2),
        }

    return list(prepared.values()), skipped


# ---------------------------------------------------------------------------
# Дубли: то же самое под другим названием
# ---------------------------------------------------------------------------

def duplicate_threshold() -> float:
    """Порог показа кандидата. Читается на каждый вызов: порог подбора живёт в
    env и меняется без деплоя (`PRICE_SIMILARITY_THRESHOLD`)."""
    return price_service.SIMILARITY_THRESHOLD - DUPLICATE_MARGIN


# ---------------------------------------------------------------------------
# План вытеснения
# ---------------------------------------------------------------------------

def _removed_work_prices(prices: Optional[dict]) -> list[dict]:
    """Чужие цены работы, которые исчезнут. Цена «Из смет» чужой не считается:
    её перезапись — обычное обновление, а не потеря прайса подрядчика."""
    if not isinstance(prices, dict):
        return []
    removed = []
    for contractor, value in prices.items():
        if str(contractor) == ESTIMATE_CONTRACTOR:
            continue
        try:
            amount = float(value)
        except (TypeError, ValueError):
            continue
        if amount > 0:
            removed.append({"contractor": str(contractor), "price": amount})
    return removed


async def find_duplicates(items: list[dict]) -> dict:
    """Позиции прайса и кеша, названные иначе, но, похоже, про то же самое.

    Ничего не удаляет и не отмечает: решение за человеком. Позиция, которая и
    так будет переоценена (точное совпадение названия), дублем не считается —
    предложить её к удалению значило бы предложить стереть ту самую строку,
    куда мы записываем эталонную цену.
    """
    kinds = {item["kind"] for item in items} or {KIND_WORK, KIND_MATERIAL}
    vectors_ready = all(price_service.duplicate_vectors_ready(kind) for kind in kinds)
    threshold = duplicate_threshold()

    seen: set = set()
    candidates: list[dict] = []

    for item in items:
        own_key = normalize_name(item["name"])
        found = await price_service.find_duplicate_candidates(
            item["name"], item["kind"], n=DUPLICATE_TOP_N,
        )
        for candidate in found:
            score = float(candidate.get("score") or 0.0)
            if score < threshold:
                continue
            if normalize_name(str(candidate.get("name") or "")) == own_key:
                continue
            key = (candidate.get("source"), item["kind"], candidate.get("id"))
            if key in seen:
                continue
            seen.add(key)
            candidates.append({
                "source": candidate.get("source"),
                "kind": item["kind"],
                "id": candidate.get("id"),
                "name": candidate.get("name"),
                "unit": candidate.get("unit"),
                "price": candidate.get("price"),
                "score": round(score, 3),
                "for_name": item["name"],
            })

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return {"vectors_ready": vectors_ready, "candidates": candidates}


async def build_plan(db: AsyncSession, items: list[dict]) -> list[dict]:
    """Что произойдёт с прайсом. Ничего не пишет — только читает.

    У каждой позиции файла один из трёх исходов: `add` (в прайсе такой нет),
    `reprice` (есть, цена из файла вытеснит остальные) и `blocked` (единица
    несводима с той, за которую назначена цена в прайсе).
    """
    work_rows = (await db.execute(
        select(PriceWork.id, PriceWork.name, PriceWork.unit, PriceWork.prices)
    )).all()
    material_rows = (await db.execute(
        select(PriceMaterial.id, PriceMaterial.name, PriceMaterial.unit, PriceMaterial.price)
    )).all()

    works = {normalize_name(row.name): row for row in work_rows}
    materials = {normalize_name(row.name): row for row in material_rows}

    plan: list[dict] = []
    for item in items:
        kind = item["kind"]
        found = (works if kind == KIND_WORK else materials).get(normalize_name(item["name"]))

        entry = {
            "kind": kind,
            "name": item["name"],
            "unit": item["unit"],
            "price": item["price"],
            "action": ACTION_ADD,
            "match": None,
            "removed": [],
            "reason": None,
        }

        if found is not None:
            entry["match"] = {
                "id": found.id,
                "name": found.name,
                "unit": found.unit,
            }
            status, _ = compare_units(found.unit, item["unit"])
            if status == STATUS_INCOMPATIBLE:
                entry["action"] = ACTION_BLOCKED
                entry["reason"] = BLOCK_UNIT_MISMATCH
            else:
                entry["action"] = ACTION_REPRICE
                if kind == KIND_WORK:
                    entry["removed"] = _removed_work_prices(found.prices)
                else:
                    old = found.price
                    try:
                        old_amount = float(old) if old is not None else None
                    except (TypeError, ValueError):
                        old_amount = None
                    if old_amount is not None and old_amount > 0 \
                            and abs(old_amount - item["price"]) > MONEY_EPS:
                        entry["removed"] = [{"contractor": None, "price": old_amount}]

        plan.append(entry)

    return plan
