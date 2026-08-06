import React, {
  useCallback, useDeferredValue, useEffect, useMemo, useRef, useState,
} from 'react';
import { createPortal } from 'react-dom';
import DataGrid, {
  Column, RenderEditCellProps, RowsChangeData, SelectColumn,
} from 'react-data-grid';
import 'react-data-grid/lib/styles.css';
import { X } from 'lucide-react';
import {
  AnalogVariant, AnalogsState, DocumentKind, DocumentRef,
  cancelAnalogs, exportDocument, getAnalogsState, resolveSectionDivergence,
} from '../../api/documents';
import { rowsOfSheet, sheetsOf, useDocumentEditorStore } from '../../stores/documentEditor';
import { LumaSpin } from '../ui/LumaSpin';
import { EditorColumn, GridRow } from './adapters/types';
import { formatMoney } from '../../utils/formatNumber';
import { applyPaste, describePaste, extractRange, parseTsv, toTsv } from './clipboard';
import EditorToolbar from './EditorToolbar';
import EditorHistoryPanel from './EditorHistoryPanel';
import {
  ConflictBanner, PresenceBanner, ReadonlyBanner, SummaryDivergenceBanner,
} from './PresenceBanner';
import EditorVersionPanel, { EditorComparison } from './EditorVersionPanel';
import OptimizationPanel from './OptimizationPanel';
import PriceActions from './actions/PriceActions';
import AddToPriceList from './actions/AddToPriceList';
import AddFromPriceList from './actions/AddFromPriceList';
import { PricePosition, buildPriceRows, insertRowsAfter } from './actions/priceInsert';
import FindAnalogs from './actions/FindAnalogs';
import AnalogsPanel from './AnalogsPanel';
import { applyAnalogToRow } from './actions/analogsApply';
import { moveRow, removeRowsCascade } from './rowOps';
import CoefficientControl from './CoefficientControl';
import ExportBuilderModal from './ExportBuilderModal';
import { columnsFromEditor, rowsFromEditor } from './exportBuilder';
import './DocumentEditor.css';

const HEARTBEAT_MS = 20_000;
// Поиск аналогов идёт минутами — чаще спрашивать сервер незачем.
const ANALOGS_POLL_MS = 5_000;

interface Props {
  cardId: string;
  kind: DocumentKind;
  /** 'input' открывает исходный файл заказчика — только просмотр. */
  fileSlot?: string;
  fileIndex?: number;
  title?: string;
  /**
   * Открыт как окно поверх экрана (из карточки) или встроен в страницу.
   * В режиме окна «свернуть» означает «закрыть» — сворачивать некуда.
   */
  startFullscreen?: boolean;
  /** Версия и вкладка из ссылки: по ней коллега должен увидеть то же самое. */
  initialVersionId?: string;
  initialTab?: 'all' | 'works' | 'materials';
  /** Вкладка листа из ссылки. */
  initialSheet?: string;
  /** Открытая версия и вкладки — чтобы страница положила их в адрес. */
  onStateChange?: (state: { versionId: string | null; tab: string; sheet: string | null }) => void;
  onClose?: () => void;
  onApplied?: () => void;
}

// --- Редактор ячейки -------------------------------------------------------

function TextEditor({ row, column, onRowChange, onClose }: RenderEditCellProps<GridRow>) {
  const inputRef = useRef<HTMLInputElement>(null);
  const initial = row[column.key];
  const [value, setValue] = useState(initial === null || initial === undefined ? '' : String(initial));

  useEffect(() => { inputRef.current?.focus(); inputRef.current?.select(); }, []);

  const commit = (commitChange: boolean) => {
    if (commitChange) onRowChange({ ...row, [column.key]: value }, true);
    else onClose(false);
  };

  return (
    <input
      ref={inputRef}
      className="de-cell-input"
      value={value}
      onChange={(e) => setValue(e.target.value)}
      onBlur={() => commit(true)}
      onKeyDown={(e) => {
        if (e.key === 'Enter') { e.preventDefault(); commit(true); }
        if (e.key === 'Escape') { e.preventDefault(); commit(false); }
      }}
    />
  );
}

// Итоги — с копейками, как и колонки стоимостей: округление до рубля
// расходилось бы с суммой того, что видно в таблице.
const fmtRub = formatMoney;

// Название документа для шапки выгрузки, когда заголовка на экране нет.
const KIND_TITLES: Record<DocumentKind, string> = {
  list: 'Перечень работ',
  completeness: 'Проверка полноты',
  estimate: 'Смета',
  optimization: 'Смета (оптимизация)',
  'summary-section': 'Раздел сводной',
};

// --- Компонент -------------------------------------------------------------

export const DocumentEditor: React.FC<Props> = ({
  cardId, kind, fileSlot, fileIndex, title, startFullscreen = false,
  initialVersionId, initialTab, initialSheet, onStateChange, onClose, onApplied,
}) => {
  const {
    meta, versionId, adapter, columns, rows, loading, error, conflict, applying, draftState,
    isDirty, selectedKeys, tab, sheet, search, lock, undoStack, redoStack,
    load, setRows, applyChanges, discardChanges, undo, redo, selectVersion,
    setTab, setSheet, setSearch, setSelected, heartbeat, reset, setCoefficient,
  } = useDocumentEditorStore();

  const [fullscreen, setFullscreen] = useState(startFullscreen);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [analogs, setAnalogs] = useState<AnalogsState | null>(null);
  const [analogsOpen, setAnalogsOpen] = useState(false);
  // Сравнение версий занимает место таблицы: это другой взгляд на тот же
  // документ, а не отдельная страница.
  const [comparing, setComparing] = useState(false);
  // Якорь вставки держим ключом строки, а не её номером: номер «уезжает» при
  // смене вкладки, поиске или удалении строк, и вставка попала бы не туда.
  const anchorRef = useRef<{ rowKey: string; columnKey: string } | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const documentRef = useMemo<DocumentRef>(
    () => ({ cardId, kind, fileSlot, fileIndex }), [cardId, kind, fileSlot, fileIndex],
  );

  // Версия из ссылки применяется только при первом открытии: дальше версию
  // выбирает человек вкладками, и адрес идёт за ним, а не наоборот.
  const initialRef = useMemo<DocumentRef>(
    () => (initialVersionId ? { ...documentRef, versionId: initialVersionId } : documentRef),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [documentRef],
  );

  // Открыт как окно поверх экрана: сворачивать некуда, «свернуть» = «закрыть».
  const isOverlayMode = startFullscreen;
  // Раздел сводной: тот же формат строк, что смета, но доп. расходы и итог
  // считает бланк «Сводная» по своим ставкам.
  const isSummarySection = kind === 'summary-section';

  useEffect(() => {
    load(initialRef);
    if (initialTab) setTab(initialTab);
    return () => reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialRef, load, reset]);

  // Открытая версия и вкладки — наружу, чтобы страница положила их в адрес и
  // ссылка открывала ровно то состояние, из которого её скопировали.
  useEffect(() => {
    onStateChange?.({ versionId, tab, sheet });
  }, [versionId, tab, sheet, onStateChange]);

  // Присутствие: раз в 20 секунд отмечаемся и узнаём, не открыл ли документ кто-то ещё.
  useEffect(() => {
    if (!meta?.can_write) return;
    heartbeat();
    const timer = setInterval(heartbeat, HEARTBEAT_MS);
    return () => clearInterval(timer);
  }, [meta?.can_write, heartbeat]);

  // Предупреждение при закрытии вкладки с непринятыми правками.
  useEffect(() => {
    if (!isDirty) return;
    const handler = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ''; };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [isDirty]);

  const canWrite = !!meta?.can_write;

  // --- Вкладки листов -------------------------------------------------------
  //
  // Исходный файл бывает разбит по листам — по листу на раздел или корпус.
  // Вкладка это только фильтр показа: в `rows` лежат строки всех вкладок,
  // поэтому «Применить» записывает документ целиком.

  const sheets = useMemo(() => sheetsOf(adapter, rows), [adapter, rows]);
  const showSheetTabs = sheets.length > 1;

  // Вкладка из ссылки применяется, когда документ уже загружен: до этого
  // списка листов ещё нет, и проверить имя не по чему.
  const sheetFromLinkRef = useRef(initialSheet);
  useEffect(() => {
    const wanted = sheetFromLinkRef.current;
    // Пока строк нет, списка листов тоже нет — ждём загрузку, а не забываем
    // имя из ссылки на первом же прогоне.
    if (!wanted || sheets.length === 0) return;
    sheetFromLinkRef.current = undefined;
    if (sheets.some((item) => item.name === wanted)) setSheet(wanted);
  }, [sheets, setSheet]);

  // Строки открытой вкладки — основа и для показа, и для колонок, и для итога.
  const sheetRows = useMemo(
    () => rowsOfSheet(adapter, rows, sheet), [adapter, rows, sheet],
  );

  // --- Фильтрация -----------------------------------------------------------

  const deferredSearch = useDeferredValue(search);

  const showTabs = useMemo(
    () => sheetRows.some((row) => adapter.rowKind(row) !== null),
    [sheetRows, adapter],
  );

  const counts = useMemo(() => {
    let work = 0;
    let material = 0;
    for (const row of sheetRows) {
      const rowKind = adapter.rowKind(row);
      if (rowKind === 'work') work += 1;
      if (rowKind === 'material') material += 1;
    }
    return { work, material };
  }, [sheetRows, adapter]);

  const displayedRows = useMemo(() => {
    let result = sheetRows;
    if (tab !== 'all') {
      const wanted = tab === 'works' ? 'work' : 'material';
      result = result.filter((row) => adapter.rowKind(row) === wanted);
    }
    const query = deferredSearch.trim().toLowerCase();
    if (query) {
      result = result.filter((row) => adapter.searchText(row).toLowerCase().includes(query));
    }
    return result;
  }, [sheetRows, tab, deferredSearch, adapter]);

  // Ставки доп. расходов: у проекта — общие, у версии могут быть свои. Порядок
  // тот же, что на сервере, иначе итог на экране не сошёлся бы с файлом.
  const expenseRates = useMemo(() => {
    const open = meta?.versions.find((v) => v.id === versionId);
    if (open?.expenses_overridden) {
      return { overhead_pct: open.overhead_pct, transport_pct: open.transport_pct };
    }
    return meta?.project ?? { overhead_pct: 0, transport_pct: 0 };
  }, [meta, versionId]);

  // Итог открытой вкладки и итог всего документа — оба сразу: человек правит
  // раздел, но отвечает за сумму контракта.
  const totals = useMemo(
    () => (meta ? adapter.totals(sheetRows, expenseRates) : null),
    [sheetRows, adapter, meta, expenseRates],
  );

  const documentTotals = useMemo(
    () => (meta && showSheetTabs ? adapter.totals(rows, expenseRates) : null),
    [rows, adapter, meta, expenseRates, showSheetTabs],
  );

  // --- Перетаскивание строк -------------------------------------------------
  //
  // Порядок строк — это порядок в документе и в скачиваемом файле, поэтому
  // строку можно перенести мышкой за ручку в начале строки.

  const dragKeyRef = useRef<string | null>(null);

  const handleRowDrop = useCallback((targetKey: string, above: boolean) => {
    const key = dragKeyRef.current;
    dragKeyRef.current = null;
    if (!key || key === targetKey) return;
    setRows(moveRow(rows, key, targetKey, above));
  }, [rows, setRows]);

  // --- Колонки --------------------------------------------------------------

  const gridColumns = useMemo<Column<GridRow>[]>(() => {
    const editable = canWrite;
    // Колонка-ручка: за неё строку тянут мышкой. Показываем только при праве на
    // запись — в режиме просмотра порядок менять нельзя.
    const dragColumn: Column<GridRow> = {
      key: '__drag',
      name: '',
      width: 28,
      minWidth: 28,
      frozen: true,
      resizable: false,
      renderCell: ({ row }) => (
        <div
          className="de-drag-handle"
          draggable
          onDragStart={() => { dragKeyRef.current = row.__key; }}
          onDragEnd={() => { dragKeyRef.current = null; }}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            const box = (e.currentTarget as HTMLElement).getBoundingClientRect();
            handleRowDrop(row.__key, e.clientY < box.top + box.height / 2);
          }}
          title="Перетащите, чтобы изменить порядок"
        >
          ⋮⋮
        </div>
      ),
    };
    const data: Column<GridRow>[] = columns.map((column: EditorColumn) => ({
      key: column.key,
      name: column.name,
      width: column.width,
      resizable: true,
      editable: editable && column.editable && !column.computed,
      cellClass: column.numeric ? 'de-cell-numeric' : undefined,
      // Формат — только на показе: в строке остаётся число, поэтому в выгрузку и
      // в файл уходит число, а не текст с пробелами.
      renderCell: ({ row }) => {
        const shown = adapter.displayValue?.(row, column.key);
        if (shown !== null && shown !== undefined) return shown;
        const raw = row[column.key];
        return raw === null || raw === undefined ? '' : String(raw);
      },
      renderEditCell: TextEditor,
    }));
    return editable
      ? [{ ...SelectColumn, frozen: true }, dragColumn, ...data]
      : [{ ...SelectColumn, frozen: true }, ...data];
  }, [columns, canWrite, handleRowDrop, adapter]);

  // Работа, материал и раздел различаются цветом: в смете на тысячу строк тип,
  // написанный словом в первой колонке, глазом не выделяется.
  const rowClass = useCallback((row: GridRow) => {
    const kind = adapter.rowKind(row);
    const byKind = kind ? `de-row-${kind}` : '';
    const byState = adapter.rowClass?.(row);
    return [byKind, byState].filter(Boolean).join(' ') || undefined;
  }, [adapter]);

  // --- Правка ячейки --------------------------------------------------------

  const mergeIntoRows = useCallback(
    (changed: Map<string, GridRow>) =>
      rows.map((row) => changed.get(row.__key) ?? row),
    [rows],
  );

  const handleGridRowsChange = useCallback(
    (updated: GridRow[], data: RowsChangeData<GridRow>) => {
      const columnKey = data.column.key;
      const changed = new Map<string, GridRow>();
      for (const index of data.indexes) {
        const row = adapter.recalc(updated[index], columnKey, columns);
        changed.set(row.__key, row);
      }
      setRows(mergeIntoRows(changed));
    },
    [adapter, columns, mergeIntoRows, setRows],
  );

  // --- Буфер обмена ---------------------------------------------------------

  const handleCopy = useCallback(
    (event: React.ClipboardEvent) => {
      if (displayedRows.length === 0) return;
      const target = event.target as HTMLElement;
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') return;

      let matrix: unknown[][];
      if (selectedKeys.size > 0) {
        const picked = displayedRows.filter((row) => selectedKeys.has(row.__key));
        matrix = picked.map((row) => columns.map((column) => row[column.key] ?? ''));
      } else if (anchorRef.current) {
        const { rowKey, columnKey } = anchorRef.current;
        const rowIdx = displayedRows.findIndex((row) => row.__key === rowKey);
        const columnIdx = columns.findIndex((c) => c.key === columnKey);
        if (rowIdx < 0 || columnIdx < 0) return;
        matrix = extractRange(displayedRows, columns, {
          top: rowIdx, bottom: rowIdx, left: columnIdx, right: columnIdx,
        });
      } else {
        return;
      }

      event.clipboardData.setData('text/plain', toTsv(matrix));
      event.preventDefault();
      setNotice(`Скопировано строк: ${matrix.length}`);
    },
    [displayedRows, selectedKeys, columns],
  );

  const handlePaste = useCallback(
    (event: React.ClipboardEvent) => {
      if (!canWrite) return;
      const target = event.target as HTMLElement;
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') return;

      const anchor = anchorRef.current;
      if (!anchor) return;

      const text = event.clipboardData.getData('text/plain');
      const matrix = parseTsv(text);
      if (matrix.length === 0) return;
      event.preventDefault();

      // Ключ → текущая позиция: если строка отфильтрована, вставлять некуда.
      const anchorRow = displayedRows.findIndex((row) => row.__key === anchor.rowKey);
      const columnIdx = columns.findIndex((c) => c.key === anchor.columnKey);
      if (anchorRow < 0 || columnIdx < 0) return;

      const outcome = applyPaste({
        rows: displayedRows,
        columns,
        anchorRow,
        anchorColumn: columnIdx,
        matrix,
        recalc: adapter.recalc,
      });

      if (outcome.applied > 0) {
        const changed = new Map<string, GridRow>();
        outcome.rows.forEach((row, index) => {
          if (row !== displayedRows[index]) changed.set(row.__key, row);
        });
        setRows(mergeIntoRows(changed));
      }
      setNotice(describePaste(outcome));
    },
    [canWrite, displayedRows, columns, adapter, mergeIntoRows, setRows],
  );

  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(null), 4000);
    return () => clearTimeout(timer);
  }, [notice]);

  // --- Строки ---------------------------------------------------------------

  const handleAddRow = useCallback(() => {
    const seed = `new-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    // Новая строка принадлежит открытой вкладке: иначе она пропала бы с экрана
    // сразу после появления.
    const fresh = adapter.withSheet(adapter.emptyRow(columns, seed), sheet);
    // Новая строка встаёт после текущей — так же, как ожидается от вставки из прайса.
    const anchorKey = anchorRef.current?.rowKey;
    const anchorAt = anchorKey ? rows.findIndex((row) => row.__key === anchorKey) : -1;
    // Без курсора — в конец своей вкладки, а не в конец документа.
    const lastOfSheet = rows.map((row) => adapter.sheetOf(row)).lastIndexOf(sheet);
    const fallback = lastOfSheet >= 0 ? lastOfSheet + 1 : rows.length;
    const at = anchorAt >= 0 ? anchorAt + 1 : fallback;
    setRows([...rows.slice(0, at), fresh, ...rows.slice(at)]);
  }, [adapter, columns, rows, setRows, sheet]);

  // --- Поиск аналогов -------------------------------------------------------
  //
  // Работа фоновая: результат появляется через минуты. Пока прогон идёт,
  // спрашиваем сервер о его состоянии; когда закончился — перестаём.

  const supportsAnalogs = kind === 'estimate' || kind === 'optimization';
  const analogsRunning = analogs?.status === 'running' || analogs?.status === 'queued';

  // Ответ приходит асинхронно: если к этому моменту редактор закрыли, состояние
  // трогать нельзя — обновлять уже нечего.
  const aliveRef = useRef(true);
  useEffect(() => {
    aliveRef.current = true;
    return () => { aliveRef.current = false; };
  }, []);

  const refreshAnalogs = useCallback(async () => {
    if (!supportsAnalogs) return;
    try {
      const state = await getAnalogsState(documentRef);
      if (!aliveRef.current) return;
      // Панель раскрываем сами только при первом появлении прогона: если её
      // закрыли руками, опрос не должен открывать её обратно.
      setAnalogs((previous) => {
        if (state.status && previous === null) setAnalogsOpen(true);
        return state;
      });
    } catch {
      // Молча: состояние поиска — не повод ломать работу с таблицей.
    }
  }, [supportsAnalogs, documentRef]);

  useEffect(() => { refreshAnalogs(); }, [refreshAnalogs]);

  useEffect(() => {
    if (!analogsRunning) return;
    const timer = setInterval(refreshAnalogs, ANALOGS_POLL_MS);
    return () => clearInterval(timer);
  }, [analogsRunning, refreshAnalogs]);

  // Раздел сводной разошёлся со сметой: человек выбирает сторону, после чего
  // документ перечитывается — расхождения больше нет ни в одном из хранилищ.
  const handleResolveDivergence = useCallback(async (prefer: 'section' | 'estimate') => {
    try {
      await resolveSectionDivergence(documentRef.cardId, prefer);
      setNotice(prefer === 'section'
        ? 'Правки раздела перенесены в смету'
        : 'Раздел приведён к смете');
      await load(documentRef);
    } catch {
      setNotice('Не удалось свести раздел и смету');
    }
  }, [documentRef, load]);

  const handleCancelAnalogs = useCallback(async () => {
    try {
      setAnalogs(await cancelAnalogs(documentRef));
      setNotice('Поиск аналогов остановлен');
    } catch {
      setNotice('Не удалось остановить поиск');
    }
  }, [documentRef]);

  // Замена идёт в строку таблицы, то есть в черновик: она откатывается Ctrl+Z
  // и не попадает в документ, пока человек не нажал «Применить».
  const handleReplaceWithAnalog = useCallback((rowId: string, variant: AnalogVariant) => {
    const index = rows.findIndex((row) => row.__key === rowId);
    if (index < 0) {
      setNotice('Эта позиция уже не в документе — заменить нечего');
      return;
    }
    const next = [...rows];
    next[index] = applyAnalogToRow(rows[index], variant, meta?.coefficient);
    setRows(next);
    setNotice(`Позиция заменена на «${variant.name}» — можно отменить через Ctrl+Z`);
  }, [rows, setRows, meta?.coefficient]);

  // С чего начинать поиск по прайсу: наименование единственной отмеченной
  // строки. Отмечено несколько или ни одной — человек вводит запрос сам.
  const priceSearchSeed = useMemo(() => {
    if (selectedKeys.size !== 1) return '';
    const row = rows.find((item) => selectedKeys.has(item.__key));
    return row ? String(row.name ?? '') : '';
  }, [rows, selectedKeys]);

  // Позиции из прайса встают сразу после текущей строки — как ожидается от
  // вставки (решение пользователя 7.1).
  const handleInsertFromPriceList = useCallback((positions: PricePosition[]) => {
    const seed = `price-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const fresh = buildPriceRows(positions, adapter, columns, seed, meta?.coefficient)
      .map((row) => adapter.withSheet(row, sheet));
    setRows(insertRowsAfter(rows, anchorRef.current?.rowKey ?? null, fresh));
    setNotice(`Вставлено позиций из прайса: ${fresh.length}`);
  }, [adapter, columns, rows, setRows, meta?.coefficient, sheet]);

  const handleDeleteSelected = useCallback(() => {
    if (selectedKeys.size === 0) return;
    // В смете удаление работы уносит её материалы: материал без своей работы —
    // мусор, который потом ищут руками.
    const next = removeRowsCascade(rows, selectedKeys, adapter);
    const removedExtra = rows.length - next.length - selectedKeys.size;
    setRows(next);
    setSelected(new Set());
    if (removedExtra > 0) {
      setNotice(`Удалено строк: ${rows.length - next.length} (вместе с материалами)`);
    }
  }, [rows, selectedKeys, adapter, setRows, setSelected]);


  // --- Клавиатура -----------------------------------------------------------

  useEffect(() => {
    if (!canWrite) return;
    const handler = (e: KeyboardEvent) => {
      const mod = e.ctrlKey || e.metaKey;
      if (!mod) return;
      if (e.key === 'z' && !e.shiftKey) { e.preventDefault(); undo(); }
      if (e.key === 'y' || (e.key === 'z' && e.shiftKey)) { e.preventDefault(); redo(); }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [canWrite, undo, redo]);

  // --- Применение -----------------------------------------------------------

  const handleApply = useCallback(async () => {
    const ok = await applyChanges();
    if (ok) {
      onApplied?.();
      setNotice('Правки записаны в документ');
    }
  }, [applyChanges, onApplied]);

  const handleClose = useCallback(() => {
    if (isDirty && !window.confirm(
      'Есть непринятые правки. Они сохранены как черновик и не попали в документ. Закрыть?',
    )) return;
    onClose?.();
  }, [isDirty, onClose]);

  // --- Разметка -------------------------------------------------------------

  const body = (
    <div className={`de-root${fullscreen ? ' de-root-fullscreen' : ''}`} ref={containerRef}>
      {(title || fullscreen) && (
        <div className="de-head">
          <span className="de-title">{title ?? 'Документ'}</span>
          {(onClose || fullscreen) && (
            <button
              className="de-icon-btn"
              onClick={fullscreen && !isOverlayMode ? () => setFullscreen(false) : handleClose}
              title={fullscreen && !isOverlayMode ? 'Свернуть' : 'Закрыть'}
            >
              <X size={16} />
            </button>
          )}
        </div>
      )}

      {loading && (
        <div className="de-state"><LumaSpin size="sm" color="#3b82f6" /> Загрузка документа…</div>
      )}
      {error && <div className="de-banner de-banner-error">{error}</div>}

      {!loading && !error && meta && (
        <>
          {conflict && (
            <ConflictBanner message={conflict} onReload={() => load(documentRef)} />
          )}
          {meta.readonly_reason && <ReadonlyBanner reason={meta.readonly_reason} />}
          {lock && <PresenceBanner lock={lock} />}

          {/* Раздел сводной, собранный до перехода на общие строки, может
              годами жить со своими числами. Ни одну сторону нельзя затирать
              молча: в разделе — работа человека, в смете — результат расчёта. */}
          {meta.divergence && canWrite && (
            <SummaryDivergenceBanner
              divergence={meta.divergence}
              onResolve={handleResolveDivergence}
            />
          )}

          {/* Шаги оптимизации и предложения ИИ — рядом с таблицей, а не на
              отдельной странице. */}
          {kind === 'optimization' && canWrite && (
            <OptimizationPanel
              meta={meta}
              onVersionCreated={(id) => {
                setComparing(false);
                load({ ...documentRef, versionId: id });
              }}
            />
          )}

          {/* Вкладки версий — при любом способе открытия: встроенном и на весь
              экран. Раньше во встроенном виде они прятались, и человек правил
              не ту версию, не зная, что версий несколько. */}
          <EditorVersionPanel
            meta={meta}
            versionId={versionId}
            comparing={comparing}
            isDirty={isDirty}
            onSelectVersion={selectVersion}
            onToggleComparison={setComparing}
            onVersionsChange={() => load({ ...documentRef, versionId: versionId ?? undefined })}
          />

          {/* Вкладки листов исходного файла. Один лист — полосы нет: у
              документа, пришедшего из однолистового файла, выбирать нечего. */}
          {showSheetTabs && (
            <div className="de-sheets" role="tablist" aria-label="Листы документа">
              {sheets.map((item) => (
                <button
                  key={item.name}
                  role="tab"
                  aria-selected={item.name === sheet}
                  className={`de-sheet${item.name === sheet ? ' de-sheet-active' : ''}`}
                  onClick={() => setSheet(item.name)}
                  title={item.name}
                >
                  {item.name}
                  <span className="de-sheet-count">{item.count}</span>
                </button>
              ))}
            </div>
          )}

          <EditorToolbar
            totalCount={sheetRows.length}
            workCount={counts.work}
            materialCount={counts.material}
            showTabs={showTabs}
            tab={tab}
            search={search}
            selectedCount={selectedKeys.size}
            canWrite={canWrite}
            isDirty={isDirty}
            applying={applying}
            draftState={draftState}
            canUndo={undoStack.length > 0}
            canRedo={redoStack.length > 0}
            fullscreen={fullscreen}
            historyOpen={historyOpen}
            onTabChange={setTab}
            onSearchChange={setSearch}
            onUndo={undo}
            onRedo={redo}
            onApply={handleApply}
            onDiscard={discardChanges}
            onAddRow={handleAddRow}
            onDeleteSelected={handleDeleteSelected}
            onToggleFullscreen={() => (isOverlayMode ? handleClose() : setFullscreen((v) => !v))}
            onToggleHistory={() => setHistoryOpen((v) => !v)}
            onExport={() => setExportOpen(true)}
          />

          {/* Выгрузка-ведомость: колонки и строки берутся у документа, поэтому
              окно одно на все типы. Цены в строках уже с коэффициентом. */}
          {exportOpen && (
            <ExportBuilderModal
              documentTitle={title ?? KIND_TITLES[kind] ?? 'Выгрузка'}
              projectName={meta.project.name}
              columns={columnsFromEditor(columns)}
              rows={rowsFromEditor(rows, columnsFromEditor(columns), adapter.rowKind, adapter.sheetOf)}
              preselectedIds={selectedKeys}
              onExport={(payload) => exportDocument(
                documentRef, payload, payload.file_name ?? 'export.xlsx',
              )}
              onClose={() => setExportOpen(false)}
            />
          )}

          {/* Коэффициент к ценам — обратимая настройка документа. В разделе
              сводной его нет: у сводной свой коэффициент в бланке, и второй,
              на уровне раздела, дал бы в редакторе одно число, а в бланке
              другое. */}
          {canWrite && !isSummarySection && meta.row_format === 'estimate' && (
            <CoefficientControl
              coefficient={meta.coefficient}
              selectedKeys={selectedKeys}
              onApply={async (payload) => {
                await setCoefficient(payload);
                setNotice(payload ? 'Коэффициент применён' : 'Коэффициент снят');
                onApplied?.();
              }}
            />
          )}

          {/* Цены ищет ИИ — действие есть только в смете и оптимизации. Раздел
              сводной формально того же формата, но он снимок: оба действия
              пишут смету задачи и правку раздела бы не увидели, зато молча
              изменили бы исходную смету. */}
          {canWrite && (kind === 'estimate' || kind === 'optimization') && meta.task_id && (
            <PriceActions
              taskId={meta.task_id}
              documentRef={documentRef}
              versionId={versionId}
              rev={meta.rev}
              rows={rows}
              selectedKeys={selectedKeys}
              isDirty={isDirty}
              onReload={() => load(documentRef)}
              onNotice={setNotice}
              onStarted={onApplied}
            />
          )}

          {/* Работа с общим прайсом. Есть везде, где у строк есть цены и типы:
              смета, оптимизация и разделы сводной. В перечне и полноте цен нет,
              отправлять туда нечего. */}
          {canWrite && meta.row_format === 'estimate' && (
            <div className="de-price-actions">
              <AddToPriceList
                documentRef={documentRef}
                rows={rows}
                selectedKeys={selectedKeys}
                rowKind={adapter.rowKind}
                onNotice={setNotice}
              />
              <AddFromPriceList
                currentRowName={priceSearchSeed}
                onInsert={handleInsertFromPriceList}
              />
              {/* Аналоги ищет ИИ в интернете — действие есть только там, где
                  правка меняет саму смету. Раздел сводной — снимок: замена в
                  нём исходную смету не изменит, и предложение вводило бы в
                  заблуждение. */}
              {supportsAnalogs && meta.task_id && (
                <FindAnalogs
                  documentRef={documentRef}
                  rows={rows}
                  selectedKeys={selectedKeys}
                  rowKind={adapter.rowKind}
                  busy={analogsRunning}
                  versionId={versionId ?? undefined}
                  onStarted={() => { setAnalogsOpen(true); refreshAnalogs(); }}
                  onNotice={setNotice}
                />
              )}
              {/* Панель закрыли, а результаты остались — без этой кнопки
                  вернуться к ним можно было бы только перезагрузкой страницы. */}
              {supportsAnalogs && !analogsOpen && analogs?.status && (
                <button className="de-btn" onClick={() => setAnalogsOpen(true)}>
                  Показать найденные аналоги
                </button>
              )}
            </div>
          )}

          {/* Найденные аналоги: предложения, а не правки. В документ попадает
              только то, что человек принял кнопкой «Заменить». */}
          {analogsOpen && analogs?.status && (
            <AnalogsPanel
              state={analogs}
              onReplace={handleReplaceWithAnalog}
              onCancel={handleCancelAnalogs}
              onClose={() => setAnalogsOpen(false)}
            />
          )}

          {totals && (
            <div className="de-totals">
              {/* У раздела сводной доп. расходы считает бланк «Сводная» — по
                  своим ставкам, а не по процентам проекта. Показать их здесь
                  значило бы поставить рядом два разных числа за одно и то же. */}
              {isSummarySection ? (
                <div className="de-totals-grid">
                  <span>Сумма по работам:</span>
                  <b>{fmtRub(totals.sumWork)} ₽</b>
                  <span>Сумма по материалам:</span>
                  <b>{fmtRub(totals.sumMat)} ₽</b>
                </div>
              ) : (
                <div className="de-totals-grid">
                  <span>Сумма по работам:</span>
                  <b>{fmtRub(totals.sumWork)} ₽</b>
                  <span>Накладные расходы {expenseRates.overhead_pct}%:</span>
                  <b>{fmtRub(totals.overhead)} ₽</b>
                  <span>Сумма по материалам:</span>
                  <b>{fmtRub(totals.sumMat)} ₽</b>
                  <span>Транспортные расходы {expenseRates.transport_pct}%:</span>
                  <b>{fmtRub(totals.transport)} ₽</b>
                </div>
              )}
              <div className="de-totals-grand">
                <span>
                  {isSummarySection
                    ? 'ИТОГО по разделу:'
                    : showSheetTabs ? `ИТОГО по листу «${sheet}»:` : 'ИТОГО:'}
                </span>
                <b>{fmtRub(isSummarySection ? totals.sumWork + totals.sumMat : totals.grand)} ₽</b>
              </div>
              {/* Сумма контракта — по всему документу, а не по открытой
                  вкладке: иначе её пришлось бы складывать в уме. */}
              {documentTotals && (
                <div className="de-totals-grand de-totals-document">
                  <span>ВСЕГО по документу:</span>
                  <b>{fmtRub(documentTotals.grand)} ₽</b>
                </div>
              )}
            </div>
          )}

          {notice && <div className="de-notice">{notice}</div>}

          {comparing && <EditorComparison meta={meta} />}

          <div className="de-content" hidden={comparing}>
            {/* data-row-count — сколько строк видно после вкладки и поиска.
                На экране это число не нужно (счётчики стоят во вкладках), но по
                нему проверяют фильтрацию тесты: строки таблицы виртуализованы и
                посчитать их в DOM нельзя. */}
            <div
              className="de-grid-wrap"
              onCopy={handleCopy}
              onPaste={handlePaste}
              data-testid="document-editor-grid"
              data-row-count={displayedRows.length}
            >
              {rows.length === 0 ? (
                <div className="de-state">Нет данных для отображения</div>
              ) : (
                <DataGrid
                  columns={gridColumns}
                  rows={displayedRows}
                  rowKeyGetter={(row) => row.__key}
                  rowClass={rowClass}
                  onRowsChange={handleGridRowsChange}
                  selectedRows={selectedKeys}
                  onSelectedRowsChange={(keys) => setSelected(new Set(keys as Set<string>))}
                  onSelectedCellChange={(args) => {
                    anchorRef.current = args.row
                      ? { rowKey: args.row.__key, columnKey: args.column.key }
                      : null;
                  }}
                  className="de-grid"
                  style={{ blockSize: fullscreen ? 'calc(100vh - 320px)' : 560 }}
                  enableVirtualization
                />
              )}
            </div>

            {historyOpen && (
              <EditorHistoryPanel
                documentRef={documentRef}
                canWrite={canWrite}
                onClose={() => setHistoryOpen(false)}
                onReverted={() => load(documentRef)}
              />
            )}
          </div>
        </>
      )}
    </div>
  );

  if (!fullscreen) return body;
  return createPortal(
    <div className="de-overlay" role="dialog" aria-modal="true">{body}</div>,
    document.body,
  );
};

export default DocumentEditor;
