import * as xlsx from 'xlsx';

// SheetJS cell type → Fortune-Sheet ct.t
function xlsxTypeToFortuneCt(t: string): string {
  switch (t) {
    case 'n': return 'n';
    case 'b': return 'b';
    case 'd': return 'd';
    case 'e': return 'e';
    default:  return 'g';
  }
}

// Fortune-Sheet border side object
function borderSide(style?: string, color?: string) {
  if (!style) return undefined;
  return { style: 1, color: color ?? '#000000' };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function xlsxCellToFortune(cell: xlsx.CellObject): Record<string, unknown> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const s = (cell as any).s ?? {};
  const font = s.font ?? {};
  const fill = s.fill ?? {};
  const alignment = s.alignment ?? {};
  const border = s.border ?? {};

  const result: Record<string, unknown> = {};

  // value
  if (cell.f) {
    // formula: store computed value only (no formula execution support)
    result.v = cell.v ?? null;
  } else {
    result.v = cell.v ?? null;
  }

  result.ct = { fa: 'General', t: xlsxTypeToFortuneCt(cell.t ?? 'g') };

  if (font.bold) result.bl = 1;
  if (font.italic) result.it = 1;
  if (font.underline) result.un = 1;
  if (font.sz) result.fs = font.sz;
  if (font.name) result.ff = font.name;
  if (font.color?.rgb) result.fc = `#${font.color.rgb.slice(-6)}`;

  // background
  const fgColor = fill.fgColor?.rgb ?? fill.fgColor?.theme;
  if (fgColor && fgColor !== 'FFFFFF00' && fgColor !== '00000000') {
    result.bg = `#${String(fgColor).slice(-6)}`;
  }

  // alignment
  if (alignment.horizontal) {
    const hMap: Record<string, number> = { left: 1, center: 0, right: 2 };
    result.ht = hMap[alignment.horizontal] ?? 0;
  }
  if (alignment.vertical) {
    const vMap: Record<string, number> = { top: 1, center: 0, bottom: 2 };
    result.vt = vMap[alignment.vertical] ?? 0;
  }
  if (alignment.wrapText) result.tb = 2;

  // borders
  const borderObj: Record<string, unknown> = {};
  const bl = borderSide(border.left?.style, border.left?.color?.rgb ? `#${border.left.color.rgb.slice(-6)}` : undefined);
  const br = borderSide(border.right?.style, border.right?.color?.rgb ? `#${border.right.color.rgb.slice(-6)}` : undefined);
  const bt = borderSide(border.top?.style, border.top?.color?.rgb ? `#${border.top.color.rgb.slice(-6)}` : undefined);
  const bb = borderSide(border.bottom?.style, border.bottom?.color?.rgb ? `#${border.bottom.color.rgb.slice(-6)}` : undefined);
  if (bl) borderObj.l = bl;
  if (br) borderObj.r = br;
  if (bt) borderObj.t = bt;
  if (bb) borderObj.b = bb;
  if (Object.keys(borderObj).length > 0) result.bd = borderObj;

  return result;
}

export function xlsxWorkbookToFortune(wb: xlsx.WorkBook): unknown[] {
  return wb.SheetNames.map((name, idx) => {
    const ws = wb.Sheets[name];
    const ref = ws['!ref'] ?? 'A1';
    const range = xlsx.utils.decode_range(ref);

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const celldata: Array<{ r: number; c: number; v: Record<string, unknown> }> = [];

    for (let r = range.s.r; r <= range.e.r; r++) {
      for (let c = range.s.c; c <= range.e.c; c++) {
        const cellRef = xlsx.utils.encode_cell({ r, c });
        const cell = ws[cellRef] as xlsx.CellObject | undefined;
        if (!cell) continue;
        celldata.push({ r, c, v: xlsxCellToFortune(cell) });
      }
    }

    // column widths
    const columnlen: Record<string, number> = {};
    if (ws['!cols']) {
      ws['!cols'].forEach((col, i) => {
        if (col?.wpx) columnlen[String(i)] = col.wpx;
        else if (col?.wch) columnlen[String(i)] = Math.round(col.wch * 7);
      });
    }

    // row heights
    const rowlen: Record<string, number> = {};
    if (ws['!rows']) {
      ws['!rows'].forEach((row, i) => {
        if (row?.hpx) rowlen[String(i)] = row.hpx;
      });
    }

    // merges
    const merge: Record<string, unknown> = {};
    if (ws['!merges']) {
      ws['!merges'].forEach((m) => {
        const key = `${m.s.r}_${m.s.c}`;
        merge[key] = {
          r: m.s.r, c: m.s.c,
          rs: m.e.r - m.s.r + 1,
          cs: m.e.c - m.s.c + 1,
        };
      });
    }

    const config: Record<string, unknown> = {};
    if (Object.keys(columnlen).length > 0) config.columnlen = columnlen;
    if (Object.keys(rowlen).length > 0) config.rowlen = rowlen;
    if (Object.keys(merge).length > 0) config.merge = merge;

    return {
      name,
      index: String(idx),
      order: idx,
      status: idx === 0 ? 1 : 0,
      celldata,
      row: Math.max(range.e.r + 1, 50),
      column: Math.max(range.e.c + 1, 26),
      config,
    };
  });
}

export function fortuneToXlsxWorkbook(sheets: unknown[]): xlsx.WorkBook {
  const wb = xlsx.utils.book_new();

  for (const sheet of sheets as Array<Record<string, unknown>>) {
    const ws: xlsx.WorkSheet = {};
    const celldata = (sheet.celldata ?? []) as Array<{ r: number; c: number; v: Record<string, unknown> }>;

    let maxR = 0;
    let maxC = 0;

    for (const { r, c, v } of celldata) {
      if (!v || v.v === null || v.v === undefined) continue;
      const cellRef = xlsx.utils.encode_cell({ r, c });

      const xCell: xlsx.CellObject = { v: v.v as xlsx.CellObject['v'], t: 's' };

      // type detection
      const ctT = (v.ct as Record<string, unknown>)?.t;
      if (ctT === 'n' || typeof v.v === 'number') xCell.t = 'n';
      else if (ctT === 'b' || typeof v.v === 'boolean') xCell.t = 'b';
      else xCell.t = 's';

      // styles
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const s: Record<string, unknown> = {};
      const font: Record<string, unknown> = {};
      if (v.bl) font.bold = true;
      if (v.it) font.italic = true;
      if (v.un) font.underline = true;
      if (v.fs) font.sz = v.fs;
      if (v.ff) font.name = v.ff;
      if (v.fc && typeof v.fc === 'string') font.color = { rgb: v.fc.replace('#', '').padStart(8, 'FF') };
      if (Object.keys(font).length > 0) s.font = font;

      if (v.bg && typeof v.bg === 'string') {
        s.fill = { patternType: 'solid', fgColor: { rgb: v.bg.replace('#', '').padStart(8, 'FF') } };
      }

      const htMap: Record<number, string> = { 1: 'left', 0: 'center', 2: 'right' };
      const vtMap: Record<number, string> = { 1: 'top', 0: 'center', 2: 'bottom' };
      const align: Record<string, unknown> = {};
      if (v.ht !== undefined) align.horizontal = htMap[v.ht as number] ?? 'general';
      if (v.vt !== undefined) align.vertical = vtMap[v.vt as number] ?? 'bottom';
      if (v.tb === 2) align.wrapText = true;
      if (Object.keys(align).length > 0) s.alignment = align;

      if (v.bd) {
        const bd = v.bd as Record<string, Record<string, unknown>>;
        const border: Record<string, unknown> = {};
        const toBorderColor = (rgb?: string) => rgb ? { rgb: rgb.replace('#', '').padStart(8, 'FF') } : { rgb: 'FF000000' };
        if (bd.l) border.left = { style: 'thin', color: toBorderColor(bd.l.color as string) };
        if (bd.r) border.right = { style: 'thin', color: toBorderColor(bd.r.color as string) };
        if (bd.t) border.top = { style: 'thin', color: toBorderColor(bd.t.color as string) };
        if (bd.b) border.bottom = { style: 'thin', color: toBorderColor(bd.b.color as string) };
        s.border = border;
      }

      if (Object.keys(s).length > 0) (xCell as unknown as Record<string, unknown>).s = s;

      ws[cellRef] = xCell;
      if (r > maxR) maxR = r;
      if (c > maxC) maxC = c;
    }

    ws['!ref'] = xlsx.utils.encode_range({ s: { r: 0, c: 0 }, e: { r: maxR, c: maxC } });

    // merges
    const config = (sheet.config ?? {}) as Record<string, unknown>;
    if (config.merge) {
      const merges = Object.values(config.merge as Record<string, { r: number; c: number; rs: number; cs: number }>);
      ws['!merges'] = merges.map((m) => ({
        s: { r: m.r, c: m.c },
        e: { r: m.r + m.rs - 1, c: m.c + m.cs - 1 },
      }));
    }

    // column widths
    if (config.columnlen) {
      const columnlen = config.columnlen as Record<string, number>;
      const cols: xlsx.ColInfo[] = [];
      Object.entries(columnlen).forEach(([i, px]) => {
        cols[Number(i)] = { wpx: px };
      });
      ws['!cols'] = cols;
    }

    // row heights
    if (config.rowlen) {
      const rowlen = config.rowlen as Record<string, number>;
      const rows: xlsx.RowInfo[] = [];
      Object.entries(rowlen).forEach(([i, px]) => {
        rows[Number(i)] = { hpx: px };
      });
      ws['!rows'] = rows;
    }

    xlsx.utils.book_append_sheet(wb, ws, String(sheet.name ?? 'Лист'));
  }

  return wb;
}

export function workbookHasFormulas(wb: xlsx.WorkBook): boolean {
  for (const name of wb.SheetNames) {
    const ws = wb.Sheets[name];
    for (const key of Object.keys(ws)) {
      if (key.startsWith('!')) continue;
      if ((ws[key] as xlsx.CellObject).f) return true;
    }
  }
  return false;
}
