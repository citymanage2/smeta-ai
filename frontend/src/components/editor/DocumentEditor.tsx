import React, {
  useCallback, useDeferredValue, useEffect, useMemo, useRef, useState,
} from 'react';
import { createPortal } from 'react-dom';
import DataGrid, {
  Column, RenderEditCellProps, RowsChangeData, SelectColumn,
} from 'react-data-grid';
import 'react-data-grid/lib/styles.css';
import { X } from 'lucide-react';
import { DocumentKind, DocumentRef } from '../../api/documents';
import { useDocumentEditorStore } from '../../stores/documentEditor';
import { LumaSpin } from '../ui/LumaSpin';
import { EditorColumn, GridRow } from './adapters/types';
import { applyPaste, describePaste, extractRange, parseTsv, toTsv } from './clipboard';
import EditorToolbar from './EditorToolbar';
import EditorHistoryPanel from './EditorHistoryPanel';
import { ConflictBanner, PresenceBanner, ReadonlyBanner } from './PresenceBanner';
import PriceActions from './actions/PriceActions';
import './DocumentEditor.css';

const HEARTBEAT_MS = 20_000;

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

const fmtRub = (n: number) => Math.round(n).toLocaleString('ru-RU');

// --- Компонент -------------------------------------------------------------

export const DocumentEditor: React.FC<Props> = ({
  cardId, kind, fileSlot, fileIndex, title, startFullscreen = false, onClose, onApplied,
}) => {
  const {
    meta, adapter, columns, rows, loading, error, conflict, applying, draftState,
    isDirty, selectedKeys, tab, search, lock, undoStack, redoStack,
    load, setRows, applyChanges, discardChanges, undo, redo,
    setTab, setSearch, setSelected, heartbeat, reset,
  } = useDocumentEditorStore();

  const [fullscreen, setFullscreen] = useState(startFullscreen);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  // Якорь вставки держим ключом строки, а не её номером: номер «уезжает» при
  // смене вкладки, поиске или удалении строк, и вставка попала бы не туда.
  const anchorRef = useRef<{ rowKey: string; columnKey: string } | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const documentRef = useMemo<DocumentRef>(
    () => ({ cardId, kind, fileSlot, fileIndex }), [cardId, kind, fileSlot, fileIndex],
  );

  // Открыт как окно поверх экрана: сворачивать некуда, «свернуть» = «закрыть».
  const isOverlayMode = startFullscreen;

  useEffect(() => {
    load(documentRef);
    return () => reset();
  }, [documentRef, load, reset]);

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

  // --- Фильтрация -----------------------------------------------------------

  const deferredSearch = useDeferredValue(search);

  const showTabs = useMemo(
    () => rows.some((row) => adapter.rowKind(row) !== null),
    [rows, adapter],
  );

  const counts = useMemo(() => {
    let work = 0;
    let material = 0;
    for (const row of rows) {
      const rowKind = adapter.rowKind(row);
      if (rowKind === 'work') work += 1;
      if (rowKind === 'material') material += 1;
    }
    return { work, material };
  }, [rows, adapter]);

  const displayedRows = useMemo(() => {
    let result = rows;
    if (tab !== 'all') {
      const wanted = tab === 'works' ? 'work' : 'material';
      result = result.filter((row) => adapter.rowKind(row) === wanted);
    }
    const query = deferredSearch.trim().toLowerCase();
    if (query) {
      result = result.filter((row) => adapter.searchText(row).toLowerCase().includes(query));
    }
    return result;
  }, [rows, tab, deferredSearch, adapter]);

  const totals = useMemo(
    () => (meta ? adapter.totals(rows, meta.project) : null),
    [rows, adapter, meta],
  );

  // --- Колонки --------------------------------------------------------------

  const gridColumns = useMemo<Column<GridRow>[]>(() => {
    const editable = canWrite;
    const data: Column<GridRow>[] = columns.map((column: EditorColumn) => ({
      key: column.key,
      name: column.name,
      width: column.width,
      resizable: true,
      editable: editable && column.editable && !column.computed,
      cellClass: column.numeric ? 'de-cell-numeric' : undefined,
      renderEditCell: TextEditor,
    }));
    return [{ ...SelectColumn, frozen: true }, ...data];
  }, [columns, canWrite]);

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
    const fresh = adapter.emptyRow(columns, seed);
    // Новая строка встаёт после текущей — так же, как ожидается от вставки из прайса.
    const anchorKey = anchorRef.current?.rowKey;
    const anchorAt = anchorKey ? rows.findIndex((row) => row.__key === anchorKey) : -1;
    const at = anchorAt >= 0 ? anchorAt + 1 : rows.length;
    setRows([...rows.slice(0, at), fresh, ...rows.slice(at)]);
  }, [adapter, columns, rows, setRows]);

  const handleDeleteSelected = useCallback(() => {
    if (selectedKeys.size === 0) return;
    setRows(rows.filter((row) => !selectedKeys.has(row.__key)));
    setSelected(new Set());
  }, [rows, selectedKeys, setRows, setSelected]);

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

          <EditorToolbar
            rowCount={displayedRows.length}
            totalCount={rows.length}
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
          />

          {/* Цены ищет ИИ — действие есть только там, где у строки есть цена. */}
          {canWrite && meta.row_format === 'estimate' && meta.task_id && (
            <PriceActions
              taskId={meta.task_id}
              rows={rows}
              selectedKeys={selectedKeys}
              isDirty={isDirty}
              onReload={() => load(documentRef)}
              onNotice={setNotice}
              onStarted={onApplied}
            />
          )}

          {totals && (
            <div className="de-totals">
              <div className="de-totals-grid">
                <span>Сумма по работам:</span>
                <b>{fmtRub(totals.sumWork)} ₽</b>
                <span>Накладные расходы {meta.project.overhead_pct}%:</span>
                <b>{fmtRub(totals.overhead)} ₽</b>
                <span>Сумма по материалам:</span>
                <b>{fmtRub(totals.sumMat)} ₽</b>
                <span>Транспортные расходы {meta.project.transport_pct}%:</span>
                <b>{fmtRub(totals.transport)} ₽</b>
              </div>
              <div className="de-totals-grand">
                <span>ИТОГО:</span>
                <b>{fmtRub(totals.grand)} ₽</b>
              </div>
            </div>
          )}

          {notice && <div className="de-notice">{notice}</div>}

          <div className="de-content">
            <div
              className="de-grid-wrap"
              onCopy={handleCopy}
              onPaste={handlePaste}
              data-testid="document-editor-grid"
            >
              {rows.length === 0 ? (
                <div className="de-state">Нет данных для отображения</div>
              ) : (
                <DataGrid
                  columns={gridColumns}
                  rows={displayedRows}
                  rowKeyGetter={(row) => row.__key}
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
