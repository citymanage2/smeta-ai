import io

import openpyxl
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from app.models.summary_estimate import SummaryEstimate

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
        qty = _to_f(row.get("quantity") or row.get("qty"))
        wp = _to_f(row.get("work_price") or row.get("price_work"))
        mp = _to_f(row.get("material_price") or row.get("price_material"))
        work_cost = round(qty * wp, 2)
        mat_cost = round(qty * mp, 2)
        is_work = str(row.get("type", "")).strip() == "Работа"
        fill = _WORK_FILL if is_work else None
        r = idx + 1

        values = [idx, row.get("name", ""), row.get("unit", ""), qty or None,
                  wp or None, work_cost or None, mp or None, mat_cost or None]
        for col, val in enumerate(values, 1):
            cell = ws.cell(row=r, column=col, value=val)
            if fill:
                cell.fill = fill
            if col in (5, 6, 7, 8) and isinstance(val, (int, float)):
                cell.number_format = _NUM_FMT


def _write_summary_sheet(ws, sections: list, overrides: dict) -> None:
    def _ov(key: str, default: float = 0.0) -> float:
        return _to_f(overrides.get(key, default))

    # Агрегация
    total_works = 0.0
    total_materials = 0.0
    section_agg: list[tuple[str, float, float]] = []

    for sec in sections:
        sw, sm = 0.0, 0.0
        for row in (sec.get("rows") or []):
            qty = _to_f(row.get("quantity") or row.get("qty"))
            sw += qty * _to_f(row.get("work_price") or row.get("price_work"))
            sm += qty * _to_f(row.get("material_price") or row.get("price_material"))
        total_works += sw
        total_materials += sm
        section_agg.append((sec.get("card_name", ""), sw, sm))

    transport = total_materials * _pct(_ov("transport_pct", 1.0))
    cleanup = total_works * _pct(_ov("cleanup_pct", 1.5))
    overhead = total_works * _pct(_ov("overhead_pct", 2.0))
    daily_workers = _ov("daily_workers_cost")
    bank_guarantee = _ov("bank_guarantee_cost")
    cleaning = _ov("cleaning_cost")
    ppr = _ov("ppr_cost")
    commissioning = _ov("commissioning_cost")

    subtotal = (total_works + total_materials + transport + cleanup + overhead
                + daily_workers + bank_guarantee + cleaning + ppr + commissioning)

    contingency = subtotal * _pct(_ov("contingency_pct", 2.0))
    profit = subtotal * _pct(_ov("profit_pct", 16.0))
    full_cost = subtotal + contingency + profit

    vat_w_pct = _ov("vat_works_pct", 22.0)
    vat_m_pct = _ov("vat_materials_pct", 20.0)
    vat_works = total_works * _pct(vat_w_pct)
    vat_materials = total_materials * _pct(vat_m_pct)
    vat = vat_works + vat_materials
    tax = full_cost * _pct(_ov("tax_pct", 3.0))
    total_customer = full_cost + vat + tax

    # ── Левая таблица (колонки A-D) ────────────────────────────────────────
    for col, h in enumerate(["Статья затрат", "База", "Ставка", "Сумма (₽)"], 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = _BOLD_WHITE
        cell.fill = _HEADER_FILL

    left_rows = [
        ("Работы", "", "", total_works),
        ("Материалы", "", "", total_materials),
        ("Транспортные расходы", "Материалы", f"{_ov('transport_pct', 1.0)}%", transport),
        ("Уборка и вывоз мусора", "Работы", f"{_ov('cleanup_pct', 1.5)}%", cleanup),
        ("Накладные", "Работы", f"{_ov('overhead_pct', 2.0)}%", overhead),
        ("Разнорабочие ежедневно", "руч. ввод", "", daily_workers),
        ("Банковская гарантия", "руч. ввод", "", bank_guarantee),
        ("Клининг", "руч. ввод", "", cleaning),
        ("РД (ППР), исполнит.", "руч. ввод", "", ppr),
        ("Пусконаладочные", "руч. ввод", "", commissioning),
    ]
    for r_idx, (label, base, rate, amount) in enumerate(left_rows, 2):
        ws.cell(row=r_idx, column=1, value=label)
        ws.cell(row=r_idx, column=2, value=base)
        ws.cell(row=r_idx, column=3, value=rate)
        c = ws.cell(row=r_idx, column=4, value=round(amount, 2))
        c.number_format = _NUM_FMT

    subtotal_row = len(left_rows) + 2
    _bold_row(ws, subtotal_row, "ИТОГО Себестоимость", subtotal, _TOTAL_FILL)

    next_row = subtotal_row + 1
    for label, pct_key, default, val in [
        ("Непредвиденные расходы", "contingency_pct", 2.0, contingency),
        ("Плановая прибыль", "profit_pct", 16.0, profit),
    ]:
        ws.cell(row=next_row, column=1, value=f"{label} {_ov(pct_key, default)}%")
        c = ws.cell(row=next_row, column=4, value=round(val, 2))
        c.number_format = _NUM_FMT
        next_row += 1

    _bold_row(ws, next_row, "Полная себестоимость", full_cost, _TOTAL_FILL)
    next_row += 1

    for label, val in [
        (f"НДС на работы {vat_w_pct}%", vat_works),
        (f"НДС на материалы {vat_m_pct}%", vat_materials),
        (f"Другие налоги {_ov('tax_pct', 3.0)}%", tax),
    ]:
        ws.cell(row=next_row, column=1, value=label)
        c = ws.cell(row=next_row, column=4, value=round(val, 2))
        c.number_format = _NUM_FMT
        next_row += 1

    _bold_row(ws, next_row, "ИТОГО для Заказчика", total_customer, _GRAND_FILL)

    for i, w in enumerate([35, 15, 12, 18], 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # ── Правая таблица (колонки F-L, E — отступ) ──────────────────────────
    OFF = 6  # F
    right_headers = [
        "Раздел", "Работы (с/с)", f"НДС {vat_w_pct}%", "Стоимость с НДС",
        "Материалы (с/с)", f"НДС {vat_m_pct}%", "Стоимость с НДС",
    ]
    for col, h in enumerate(right_headers, OFF):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = _BOLD_WHITE
        cell.fill = _HEADER_FILL

    for i, w in enumerate([30, 18, 14, 18, 18, 14, 18], OFF):
        ws.column_dimensions[get_column_letter(i)].width = w

    totals_r = [0.0] * 6
    for r_idx, (sec_name, sw, sm) in enumerate(section_agg, 2):
        sw_vat = sw * _pct(vat_w_pct)
        sm_vat = sm * _pct(vat_m_pct)
        vals = [sec_name, sw, sw_vat, sw + sw_vat, sm, sm_vat, sm + sm_vat]
        for t_i, v in enumerate(vals[1:]):
            totals_r[t_i] += v
        for col, val in enumerate(vals, OFF):
            cell = ws.cell(row=r_idx, column=col, value=round(val, 2) if isinstance(val, float) else val)
            if isinstance(val, float):
                cell.number_format = _NUM_FMT

    total_r_row = len(section_agg) + 2
    total_vals = ["ИТОГО"] + [round(v, 2) for v in totals_r]
    for col, val in enumerate(total_vals, OFF):
        cell = ws.cell(row=total_r_row, column=col, value=val)
        cell.font = _BOLD
        cell.fill = _TOTAL_FILL
        if isinstance(val, float):
            cell.number_format = _NUM_FMT


_COLUMN_META: dict[str, tuple[str, int, bool]] = {
    # key: (заголовок, ширина, денежный)
    "num":            ("№",              5,  False),
    "name":           ("Наименование",  50,  False),
    "unit":           ("Ед. изм.",      10,  False),
    "qty":            ("Кол-во",        10,  False),
    "price_work":     ("Цена работ",    14,  True),
    "cost_work":      ("Стоим. работ",  16,  True),
    "price_material": ("Цена матер.",   14,  True),
    "cost_material":  ("Стоим. матер.", 16,  True),
    "section":        ("Раздел",        30,  False),
}


def generate_custom_export_xlsx(
    rows: list[dict],
    visible_columns: list[str],
    section_groups: list[tuple[str, list[dict]]],
) -> bytes:
    """
    Генерирует Excel для кастомной выгрузки.

    rows: уже отфильтрованные строки (с полем section_name).
    visible_columns: список ключей из _COLUMN_META.
    section_groups: [(section_name, [rows])] — для разбивки по листам.
    """
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    cols = [c for c in visible_columns if c in _COLUMN_META]

    if len(section_groups) > 1:
        for sec_name, sec_rows in section_groups:
            sheet_name = sec_name[:31] or "Раздел"
            ws = wb.create_sheet(title=sheet_name)
            _write_custom_sheet(ws, sec_rows, cols, show_section=False)
        ws_all = wb.create_sheet(title="Все разделы")
        _write_custom_sheet(ws_all, rows, cols, show_section=True)
    else:
        sec_name = section_groups[0][0] if section_groups else "Выгрузка"
        ws = wb.create_sheet(title=sec_name[:31] or "Выгрузка")
        _write_custom_sheet(ws, rows, cols, show_section=False)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _write_custom_sheet(ws, rows: list[dict], cols: list[str], show_section: bool) -> None:
    effective_cols = (["section"] + cols) if show_section and "section" not in cols else cols

    for col_idx, key in enumerate(effective_cols, 1):
        meta = _COLUMN_META.get(key)
        if not meta:
            continue
        header, width, _ = meta
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = _BOLD_WHITE
        cell.fill = _HEADER_FILL
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    for row_idx, row in enumerate(rows, 2):
        for col_idx, key in enumerate(effective_cols, 1):
            meta = _COLUMN_META.get(key)
            if not meta:
                continue
            _, _, is_money = meta
            val = row.get(key)
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            if is_money and isinstance(val, (int, float)):
                cell.number_format = _NUM_FMT


def _bold_row(ws, row: int, label: str, value: float, fill: PatternFill) -> None:
    for col in range(1, 5):
        ws.cell(row=row, column=col).fill = fill
    lc = ws.cell(row=row, column=1, value=label)
    lc.font = _BOLD
    vc = ws.cell(row=row, column=4, value=round(value, 2))
    vc.font = _BOLD
    vc.number_format = _NUM_FMT
