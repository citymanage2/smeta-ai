import io

import openpyxl
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from app.models.summary_estimate import SummaryEstimate
from app.utils.price_coercion import coerce_qty, coerce_qty_signed
from app.utils.summary_calc import FIXED_ROW_KEYS, FIXED_ROW_LABELS, calc_summary

_HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
_TOTAL_FILL = PatternFill(start_color="BDD7EE", end_color="BDD7EE", fill_type="solid")
_GRAND_FILL = PatternFill(start_color="70AD47", end_color="70AD47", fill_type="solid")
_WORK_FILL = PatternFill(start_color="EBF3FB", end_color="EBF3FB", fill_type="solid")
_BOLD_WHITE = Font(bold=True, color="FFFFFF")
_BOLD = Font(bold=True)
_NUM_FMT = "#,##0.00"


def _to_f(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _pct(v) -> float:
    return _to_f(v) / 100.0


def _billable_qty(row: dict) -> float:
    """Объём для умножения на цену: вычет (< 0) даёт 0.

    Строка с отрицательным объёмом корректирует объём соседней позиции, а не
    является работой: `qty × цена` по ней дала бы отрицательную сумму и занизила
    сводную. Правило то же, что в `price_coercion.coerce_qty`.
    """
    return coerce_qty(row.get("quantity") or row.get("qty"))


def generate_summary_xlsx(summary: SummaryEstimate) -> bytes:
    """Многолистовой xlsx: лист на каждый раздел + лист «Сводная»."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    sections = summary.sections or []
    overrides = summary.overrides or {}

    for sec in sections:
        raw_name = sec.get("card_name") or "Раздел"
        sheet_name = raw_name[:31]
        ws = wb.create_sheet(title=sheet_name)
        _write_section_sheet(ws, sec)

    ws_sum = wb.create_sheet(title="Сводная")
    _write_summary_sheet(ws_sum, sections, overrides)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _write_section_sheet(ws, section: dict) -> None:
    headers = [
        "№", "Наименование", "Ед. изм.", "Кол-во",
        "Цена работ", "Стоимость работ", "Цена матер.", "Стоимость матер.",
    ]
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = _BOLD_WHITE
        cell.fill = _HEADER_FILL

    for i, w in enumerate([5, 50, 10, 10, 14, 18, 14, 18], 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    for idx, row in enumerate(section.get("rows") or [], 1):
        qty = _billable_qty(row)
        # В колонке «Кол-во» — исходное число со знаком: вычет должен остаться
        # видимым, стоимости по нему просто нет.
        qty_shown = coerce_qty_signed(row.get("quantity") or row.get("qty"))
        wp = _to_f(row.get("work_price") or row.get("price_work"))
        mp = _to_f(row.get("material_price") or row.get("price_material"))
        work_cost = round(qty * wp, 2)
        mat_cost = round(qty * mp, 2)
        is_work = str(row.get("type", "")).strip() == "Работа"
        fill = _WORK_FILL if is_work else None
        r = idx + 1

        values = [idx, row.get("name", ""), row.get("unit", ""), qty_shown or None,
                  wp or None, work_cost or None, mp or None, mat_cost or None]
        for col, val in enumerate(values, 1):
            cell = ws.cell(row=r, column=col, value=val)
            if fill:
                cell.fill = fill
            if col in (5, 6, 7, 8) and isinstance(val, (int, float)):
                cell.number_format = _NUM_FMT


def _write_summary_sheet(ws, sections: list, overrides: dict) -> None:
    """Лист «Сводная» — ровно то, что человек видит в бланке на экране.

    Числа считает `utils/summary_calc` — построчный повтор клиентской
    `calcSummary`. Раньше здесь была своя, более старая формула: без
    коэффициента, без налогов разделов, без восьми строк расходов, с другой
    прибылью и НДС. Файл расходился с экраном на десятки процентов.
    """
    calc = calc_summary(sections, overrides)
    hidden = calc["hidden_fixed_rows"]

    # ── Левая таблица: строки бланка (колонки A-D) ────────────────────────
    for col, h in enumerate(["Статья затрат", "Без НДС (₽)", "С НДС (₽)", "Сумма (₽)"], 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = _BOLD_WHITE
        cell.fill = _HEADER_FILL

    row_idx = 2
    for key in FIXED_ROW_KEYS:
        if key in hidden:
            continue
        ws.cell(row=row_idx, column=1, value=FIXED_ROW_LABELS[key])
        for col, value in (
            (2, calc[f"{key}_without_vat"]), (3, calc[f"{key}_with_vat"]),
        ):
            cell = ws.cell(row=row_idx, column=col, value=round(value, 2))
            cell.number_format = _NUM_FMT
        row_idx += 1

    for custom in calc["custom_rows_before"]:
        ws.cell(row=row_idx, column=1, value=str(custom.get("label") or ""))
        without_vat = _to_f(custom.get("without_vat"))
        for col, value in ((2, without_vat), (3, without_vat * 1.22)):
            cell = ws.cell(row=row_idx, column=col, value=round(value, 2))
            cell.number_format = _NUM_FMT
        row_idx += 1

    _bold_row(ws, row_idx, "ИТОГО себестоимость объекта", calc["subtotal_with_vat"], _TOTAL_FILL)
    ws.cell(row=row_idx, column=2, value=round(calc["subtotal_without_vat"], 2)).number_format = _NUM_FMT
    ws.cell(row=row_idx, column=3, value=round(calc["subtotal_with_vat"], 2)).number_format = _NUM_FMT
    row_idx += 1

    for label, value in (
        (f"Непредвиденные расходы {calc['contingency_pct']:g}%", calc["contingency_with_vat"]),
        (f"Плановая прибыль {calc['profit_pct']:g}%", calc["profit"]),
    ):
        ws.cell(row=row_idx, column=1, value=label)
        cell = ws.cell(row=row_idx, column=4, value=round(value, 2))
        cell.number_format = _NUM_FMT
        row_idx += 1

    _bold_row(ws, row_idx, "Полная себестоимость без НДС", calc["full_cost_without_vat"], _TOTAL_FILL)
    row_idx += 1

    for label, value in (
        (f"НДС {calc['vat_pct']:g}%", calc["vat"]),
        (f"Другие налоги {calc['other_tax_pct']:g}%", calc["other_tax"]),
    ):
        ws.cell(row=row_idx, column=1, value=label)
        cell = ws.cell(row=row_idx, column=4, value=round(value, 2))
        cell.number_format = _NUM_FMT
        row_idx += 1

    _bold_row(ws, row_idx, "ИТОГО по смете для Заказчика с учётом налогов",
              calc["total_for_customer"], _GRAND_FILL)
    row_idx += 1

    for custom in calc["custom_rows_after"]:
        ws.cell(row=row_idx, column=1, value=str(custom.get("label") or ""))
        cell = ws.cell(row=row_idx, column=4,
                       value=round(_to_f(custom.get("without_vat")) * 1.22, 2))
        cell.number_format = _NUM_FMT
        row_idx += 1

    for i, w in enumerate([42, 18, 18, 20], 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # ── Правая таблица: разделы со своими налогами (колонки F-K) ──────────
    OFF = 6
    right_headers = [
        "Раздел", "Налог, %", "Работы (с/с)", "Работы с НДС",
        "Материалы (с/с)", "Материалы с НДС",
    ]
    for col, h in enumerate(right_headers, OFF):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = _BOLD_WHITE
        cell.fill = _HEADER_FILL

    for i, w in enumerate([30, 12, 18, 18, 18, 18], OFF):
        ws.column_dimensions[get_column_letter(i)].width = w

    totals_right = [0.0] * 4
    for r_idx, section in enumerate(calc["section_totals"], 2):
        values = [
            section["card_name"], section["tax_pct"],
            section["works_raw"], section["works_with_vat"],
            section["materials_raw"], section["materials_with_vat"],
        ]
        for i, value in enumerate(values[2:]):
            totals_right[i] += value
        for col, value in enumerate(values, OFF):
            cell = ws.cell(
                row=r_idx, column=col,
                value=round(value, 2) if isinstance(value, float) else value,
            )
            if isinstance(value, float):
                cell.number_format = _NUM_FMT

    total_row = len(calc["section_totals"]) + 2
    for col, value in enumerate(["ИТОГО", None] + [round(v, 2) for v in totals_right], OFF):
        cell = ws.cell(row=total_row, column=col, value=value)
        cell.font = _BOLD
        cell.fill = _TOTAL_FILL
        if isinstance(value, float):
            cell.number_format = _NUM_FMT


def _bold_row(ws, row: int, label: str, value: float, fill: PatternFill) -> None:
    for col in range(1, 5):
        ws.cell(row=row, column=col).fill = fill
    lc = ws.cell(row=row, column=1, value=label)
    lc.font = _BOLD
    vc = ws.cell(row=row, column=4, value=round(value, 2))
    vc.font = _BOLD
    vc.number_format = _NUM_FMT
