import { CollapseFields, GridRow, RowKind, toNumber } from './adapters/types';

/**
 * Свёртка одинаковых позиций в общий объём (план
 * `plans/2026-08-13-svertka-odinakovyh-pozicij.md`).
 *
 * Одна и та же работа встречается в чужой смете по пять раз — в разных
 * разделах и на разных листах. Проверить общий объём можно только сложив пять
 * чисел в уме, а цену приходится править пять раз: пропустил одну позицию — и
 * в смете живут две разные цены на одну работу, молча.
 *
 * Главное правило: **свёртка — уровень показа, а не изменение документа.**
 * Строки документа остаются как есть, поэтому «Применить», итоги, история,
 * откат и журнал корректировок работают ровно так же, как без свёртки. Правка
 * свёрнутой строки — это N обычных правок N строк, а не одна правка «группы».
 *
 * Функции здесь чистые: они работают со списком строк таблицы и ничего не
 * знают ни про React, ни про формат хранения документа.
 */

/**
 * Начало ключа свёрнутой строки. Служебный (`__`), поэтому в документ не
 * попадает: оба адаптера отбрасывают служебные ключи при сохранении.
 */
export const GROUP_PREFIX = '__grp:';

/** Сведения о группе — на самой свёрнутой строке. */
export const GROUP_KEY = '__group';
/** Поля, значения которых у позиций разошлись: показываются как «разные». */
export const MIXED_KEY = '__mixed';
/** Позиция внутри раскрытой группы — по этому признаку она сдвинута отступом. */
export const CHILD_KEY = '__child';

export interface GroupInfo {
  /** Ключ группы: тип + наименование + единица. */
  key: string;
  /** Ключи строк документа, вошедших в группу, в порядке документа. */
  memberKeys: string[];
  /** Группа раскрыта — под ней показаны её позиции. */
  expanded: boolean;
}

/**
 * Наименование и единица сравниваются без учёта регистра и лишних пробелов:
 * в чужих сметах одна и та же позиция пишется то «Штукатурка стен», то
 * «штукатурка  стен» (решение пользователя 13.08.2026).
 */
function norm(value: unknown): string {
  return String(value ?? '').trim().toLowerCase().replace(/\s+/g, ' ');
}

/**
 * Сложение объёмов и стоимостей даёт плавающий хвост (0,1 + 0,2 = 0,30000000000000004).
 * Шести знаков хватает и деньгам (две цифры после запятой), и объёмам.
 */
function roundSum(value: number): number {
  return Math.round(value * 1e6) / 1e6;
}

/** Одинаковы ли значения поля у двух позиций: число сравниваем числом. */
function sameValue(left: unknown, right: unknown): boolean {
  if (left === right) return true;
  const leftNumber = toNumber(left);
  const rightNumber = toNumber(right);
  if (leftNumber !== null && rightNumber !== null) return leftNumber === rightNumber;
  return String(left ?? '') === String(right ?? '');
}

/**
 * Ключ группы или `null`, если строка в свёртку не идёт.
 *
 * Не идут разделы (заголовок раздела — не позиция) и строки без наименования:
 * собрать все безымянные строки в одну кучу значило бы спрятать их друг за
 * друга. Единица — часть ключа: м2 и м3 складывать нельзя.
 */
export function collapseKey(
  row: GridRow, fields: CollapseFields, kind: RowKind,
): string | null {
  if (kind === 'section') return null;
  const name = norm(row[fields.nameKey]);
  if (name === '') return null;
  const unit = fields.unitKey ? norm(row[fields.unitKey]) : '';
  return `${kind ?? ''}|${name}|${unit}`;
}

/** Свёрнутая ли это строка. */
export function isGroupRow(row: GridRow): boolean {
  return typeof row.__key === 'string' && row.__key.startsWith(GROUP_PREFIX);
}

/** Сведения о группе свёрнутой строки; `null` — строка обычная. */
export function groupInfoOf(row: GridRow): GroupInfo | null {
  const info = row[GROUP_KEY];
  return info && typeof info === 'object' ? (info as GroupInfo) : null;
}

/** Разошлись ли значения этого поля внутри группы. */
export function isMixedField(row: GridRow, key: string): boolean {
  const mixed = row[MIXED_KEY];
  return Array.isArray(mixed) && mixed.includes(key);
}

/**
 * Свёрнутая строка группы.
 *
 * Поля из `sumKeys` складываются. Стоимость складывается именно по позициям, а
 * не считается как «общий объём × цена»: цены внутри группы могут отличаться, и
 * произведение разошлось бы с итогом документа.
 *
 * Остальные поля берутся у позиций, если совпали у всех; разошлись — поле
 * помечается как «разные» и остаётся пустым. Показать первое попавшееся число
 * нельзя: человек принял бы его за цену всей группы.
 */
function buildGroupRow(
  key: string, members: GridRow[], fields: CollapseFields, expanded: boolean,
): GridRow {
  const [first] = members;
  const summed = new Set(fields.sumKeys);
  // Наименование и единица — сам ключ группы: они совпали с точностью до
  // регистра и пробелов, иначе позиции в одну группу не попали бы. Сравнивать
  // их посимвольно значило бы объявить «разными» ровно то, по чему собрали.
  const keyed = new Set([fields.nameKey, ...(fields.unitKey ? [fields.unitKey] : [])]);
  const group: GridRow = { __key: GROUP_PREFIX + key };
  const mixed: string[] = [];

  for (const field of Object.keys(first)) {
    // Служебные ключи позиции (лист, исходная цена) свёрнутой строке не
    // принадлежат: она не строка документа и в документ не сохраняется.
    if (field === '__key' || field.startsWith('__') || summed.has(field)) continue;
    const value = first[field];
    if (keyed.has(field) || members.every((member) => sameValue(member[field], value))) {
      group[field] = value;
    } else {
      group[field] = null;
      mixed.push(field);
    }
  }

  for (const field of fields.sumKeys) {
    let total = 0;
    let seen = false;
    for (const member of members) {
      const value = toNumber(member[field]);
      if (value === null) continue;
      seen = true;
      total += value;
    }
    group[field] = seen ? roundSum(total) : null;
  }

  group[GROUP_KEY] = { key, memberKeys: members.map((member) => member.__key), expanded };
  group[MIXED_KEY] = mixed;
  return group;
}

/**
 * Строки для показа в свёрнутом режиме.
 *
 * Группа встаёт на место своей первой позиции — порядок документа сохраняется.
 * Раскрытая группа показывает свои позиции сразу под собой; они остаются
 * настоящими строками документа и правятся как обычно.
 *
 * Группа из одной позиции строкой-группой не становится: сворачивать нечего, а
 * лишняя обёртка отняла бы у строки правку объёма.
 */
export function buildCollapsedRows(
  rows: GridRow[],
  fields: CollapseFields,
  kindOf: (row: GridRow) => RowKind,
  expanded: ReadonlySet<string>,
): GridRow[] {
  const groups = new Map<string, GridRow[]>();
  const keys = rows.map((row) => collapseKey(row, fields, kindOf(row)));

  rows.forEach((row, index) => {
    const key = keys[index];
    if (key === null) return;
    const members = groups.get(key);
    if (members) members.push(row);
    else groups.set(key, [row]);
  });

  const done = new Set<string>();
  const result: GridRow[] = [];

  rows.forEach((row, index) => {
    const key = keys[index];
    if (key === null) {
      result.push(row);
      return;
    }
    if (done.has(key)) return;
    done.add(key);

    const members = groups.get(key)!;
    if (members.length === 1) {
      result.push(row);
      return;
    }

    const isExpanded = expanded.has(key);
    result.push(buildGroupRow(key, members, fields, isExpanded));
    if (isExpanded) {
      for (const member of members) result.push({ ...member, [CHILD_KEY]: true });
    }
  });

  return result;
}

/**
 * Правка свёрнутой строки → правки всех позиций группы.
 *
 * Меняются только совместные поля: цена, наименование, единица. Объём в
 * свёрнутой строке не правится вовсе, поэтому разносить его нечем — правится он
 * позиционно, в раскрытой группе.
 *
 * Каждая позиция пересчитывается своим `recalc`: стоимость считается по её
 * собственному объёму, а не по общему.
 */
export function spreadEdit(
  groupRow: GridRow,
  changedKey: string,
  rows: GridRow[],
  fields: CollapseFields,
  recalc: (row: GridRow, changedKey: string) => GridRow,
): Map<string, GridRow> {
  const changes = new Map<string, GridRow>();
  const info = groupInfoOf(groupRow);
  if (!info || !fields.sharedKeys.includes(changedKey)) return changes;

  const members = new Set(info.memberKeys);
  const value = groupRow[changedKey];
  for (const row of rows) {
    if (!members.has(row.__key)) continue;
    changes.set(row.__key, recalc({ ...row, [changedKey]: value }, changedKey));
  }
  return changes;
}

/**
 * Отметку в таблице → отметку строк документа.
 *
 * Отметив свёрнутую строку галочкой, человек отмечает все её позиции: дальше
 * ключи уходят в удаление, коэффициент и работу с прайсом, а ключа группы в
 * документе нет — он бы там ничего не нашёл.
 *
 * Считается разница «что было отмечено в таблице» и «что стало», а не новый
 * список целиком: свёрнутая группа скрывает свои позиции, и снятая с неё
 * галочка иначе не сняла бы отметку ни с одной из них — выделение нельзя было
 * бы сбросить вовсе.
 */
export function applySelectionChange(
  current: ReadonlySet<string>,
  previousGrid: ReadonlySet<string>,
  nextGrid: ReadonlySet<string>,
  displayed: GridRow[],
): Set<string> {
  const result = new Set(current);
  const expand = (key: string): string[] => {
    const row = displayed.find((item) => item.__key === key);
    const info = row ? groupInfoOf(row) : null;
    return info ? info.memberKeys : [key];
  };

  for (const key of previousGrid) {
    if (nextGrid.has(key)) continue;
    for (const member of expand(key)) result.delete(member);
  }
  for (const key of nextGrid) {
    if (previousGrid.has(key)) continue;
    for (const member of expand(key)) result.add(member);
  }
  return result;
}

/**
 * Ключи настоящих строк → ключи для галочек таблицы: группа отмечена, когда
 * отмечены все её позиции. Обратная сторона `resolveSelection`, без неё
 * галочка гасла бы сразу после нажатия.
 */
export function selectionForGrid(
  selected: ReadonlySet<string>, displayed: GridRow[],
): Set<string> {
  const result = new Set<string>(selected);
  for (const row of displayed) {
    const info = groupInfoOf(row);
    if (!info || info.memberKeys.length === 0) continue;
    if (info.memberKeys.every((key) => selected.has(key))) result.add(row.__key);
  }
  return result;
}
