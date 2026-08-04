import { create } from 'zustand';
import {
  CoefficientPayload,
  DocumentMeta,
  DocumentRef,
  LockInfo,
  applyDocument,
  discardDraft as apiDiscardDraft,
  getDocumentMeta,
  getDocumentRows,
  saveDraft,
  sendHeartbeat,
  setDocumentCoefficient,
} from '../api/documents';
import { estimateAdapter } from '../components/editor/adapters/estimateAdapter';
import { genericAdapter } from '../components/editor/adapters/genericAdapter';
import { EditorAdapter, EditorColumn, GridRow } from '../components/editor/adapters/types';

/** Строки одной вкладки. `null` — документ без вкладок, вкладка одна на всё. */
export function rowsOfSheet(
  adapter: EditorAdapter, rows: GridRow[], sheet: string | null,
): GridRow[] {
  if (sheet === null) return rows;
  return rows.filter((row) => adapter.sheetOf(row) === sheet);
}

/** Вкладки документа с числом строк, в порядке появления строк. */
export function sheetsOf(adapter: EditorAdapter, rows: GridRow[]): Array<{ name: string; count: number }> {
  const order: string[] = [];
  const counts = new Map<string, number>();
  for (const row of rows) {
    const name = adapter.sheetOf(row);
    if (name === null) continue;
    if (!counts.has(name)) order.push(name);
    counts.set(name, (counts.get(name) ?? 0) + 1);
  }
  return order.map((name) => ({ name, count: counts.get(name) ?? 0 }));
}

/**
 * Состояние открытого документа.
 *
 * Главное правило: правки живут в черновике и попадают в рабочие строки только
 * по «Применить». Черновик уходит на сервер сам, с паузой после ввода — чтобы
 * закрытая вкладка не стоила пользователю получаса работы, но и чтобы каждая
 * набранная цифра не улетала в файл сметы.
 */

const DRAFT_DEBOUNCE_MS = 800;
const MAX_HISTORY = 50;

export type DraftState = 'idle' | 'saving' | 'saved' | 'error';
export type EditorTab = 'all' | 'works' | 'materials';

interface DocumentEditorState {
  ref: DocumentRef | null;
  meta: DocumentMeta | null;
  /**
   * Версия, открытая прямо сейчас. Отличается от `meta.active_version_id`,
   * когда человек переключился на другую вкладку версии: черновик, «Применить»
   * и `rev` относятся к выбранной версии, а не к активной по умолчанию.
   */
  versionId: string | null;
  adapter: EditorAdapter;
  columns: EditorColumn[];
  rows: GridRow[];
  /** Последнее применённое состояние — основа для «есть несохранённые правки». */
  baseline: GridRow[];
  loading: boolean;
  error: string;
  /** Заполняется, когда документ изменили параллельно: нужен перезагруз. */
  conflict: string;
  applying: boolean;
  draftState: DraftState;
  isDirty: boolean;
  selectedKeys: Set<string>;
  tab: EditorTab;
  /**
   * Открытая вкладка листа. `null` — документ из одного листа.
   *
   * Вкладка — только фильтр показа: в `rows` всегда лежат строки **всех**
   * вкладок, поэтому «Применить» записывает документ целиком, а не ту вкладку,
   * которая была открыта в момент нажатия.
   */
  sheet: string | null;
  search: string;
  lock: LockInfo | null;
  undoStack: GridRow[][];
  redoStack: GridRow[][];

  load: (ref: DocumentRef) => Promise<void>;
  selectVersion: (versionId: string) => Promise<void>;
  /** Поставить коэффициент к ценам или снять его (null). */
  setCoefficient: (payload: CoefficientPayload | null) => Promise<void>;
  setRows: (rows: GridRow[], options?: { skipHistory?: boolean }) => void;
  applyChanges: () => Promise<boolean>;
  discardChanges: () => Promise<void>;
  undo: () => void;
  redo: () => void;
  setTab: (tab: EditorTab) => void;
  setSheet: (sheet: string | null) => void;
  setSearch: (search: string) => void;
  setSelected: (keys: Set<string>) => void;
  heartbeat: () => Promise<void>;
  reset: () => void;
}

let draftTimer: ReturnType<typeof setTimeout> | null = null;

function cancelDraftTimer(): void {
  if (draftTimer) {
    clearTimeout(draftTimer);
    draftTimer = null;
  }
}

function adapterFor(meta: DocumentMeta | null): EditorAdapter {
  return meta?.row_format === 'estimate' ? estimateAdapter : genericAdapter;
}

const EMPTY: Pick<
  DocumentEditorState,
  'ref' | 'meta' | 'versionId' | 'columns' | 'rows' | 'baseline' | 'loading' | 'error' | 'conflict'
  | 'applying' | 'draftState' | 'isDirty' | 'selectedKeys' | 'tab' | 'sheet' | 'search'
  | 'lock' | 'undoStack' | 'redoStack'
> = {
  ref: null,
  meta: null,
  versionId: null,
  columns: [],
  rows: [],
  baseline: [],
  loading: false,
  error: '',
  conflict: '',
  applying: false,
  draftState: 'idle',
  isDirty: false,
  selectedKeys: new Set<string>(),
  tab: 'all',
  sheet: null,
  search: '',
  lock: null,
  undoStack: [],
  redoStack: [],
};

export const useDocumentEditorStore = create<DocumentEditorState>((set, get) => ({
  ...EMPTY,
  adapter: genericAdapter,

  load: async (ref: DocumentRef) => {
    cancelDraftTimer();
    set({ ...EMPTY, adapter: genericAdapter, ref, loading: true });
    try {
      const meta = await getDocumentMeta(ref);
      const data = await getDocumentRows({ ...ref, versionId: ref.versionId ?? undefined });
      const adapter = adapterFor(meta);

      // Коэффициент — настройка документа: цены в таблице показываются уже с
      // ним, а в документ уходят исходные (решение пользователя, Фаза 8).
      const ctx = { coefficient: meta.coefficient };
      const applied = adapter.toGrid(data.rows, ctx);
      // Непринятые правки не теряются между сессиями: черновик показываем
      // сразу, но «как было» помним — иначе не отличить правку от исходника.
      const draft = data.draft_rows ? adapter.toGrid(data.draft_rows, ctx) : null;
      const rows = draft ?? applied;
      // Открываем первую вкладку. Колонки считаются по её строкам: у листов
      // исходного файла шапки разные, и общий набор дал бы каждой вкладке
      // пустые колонки соседа.
      const sheet = sheetsOf(adapter, rows)[0]?.name ?? null;

      set({
        meta: { ...meta, rev: data.rev },
        versionId: data.version_id,
        adapter,
        columns: adapter.columns(rowsOfSheet(adapter, rows, sheet)),
        rows,
        sheet,
        baseline: applied,
        isDirty: draft !== null,
        lock: meta.lock,
        loading: false,
      });
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      set({
        loading: false,
        error: status === 404
          ? 'Документ не найден или недоступен.'
          : 'Не удалось загрузить документ. Попробуйте открыть заново.',
      });
    }
  },

  setRows: (rows: GridRow[], options) => {
    const { rows: current, undoStack, ref, meta, adapter } = get();
    set({
      rows,
      isDirty: true,
      undoStack: options?.skipHistory
        ? undoStack
        : [...undoStack.slice(-(MAX_HISTORY - 1)), current],
      redoStack: options?.skipHistory ? get().redoStack : [],
    });

    const versionId = get().versionId;
    if (!ref || !versionId || !meta?.can_write) return;

    cancelDraftTimer();
    set({ draftState: 'saving' });
    draftTimer = setTimeout(() => {
      draftTimer = null;
      saveDraft(ref, versionId, adapter.fromGrid(get().rows, { coefficient: meta?.coefficient }))
        .then(() => set({ draftState: 'saved' }))
        .catch(() => set({ draftState: 'error' }));
    }, DRAFT_DEBOUNCE_MS);
  },

  applyChanges: async () => {
    const { ref, meta, rows, adapter, versionId } = get();
    if (!ref || !meta || !versionId) return false;
    cancelDraftTimer();
    set({ applying: true, conflict: '' });
    try {
      const result = await applyDocument(
        ref, versionId, meta.rev,
        adapter.fromGrid(rows, { coefficient: meta.coefficient }),
      );
      set({
        meta: { ...meta, rev: result.rev, has_draft: false },
        baseline: rows,
        isDirty: false,
        applying: false,
        draftState: 'idle',
        undoStack: [],
        redoStack: [],
      });
      return true;
    } catch (err: unknown) {
      const response = (err as { response?: { status?: number; data?: { detail?: string } } })?.response;
      if (response?.status === 409) {
        set({ applying: false, conflict: response.data?.detail ?? 'Документ изменился, пока вы работали.' });
      } else {
        set({ applying: false, error: 'Не удалось сохранить. Попробуйте ещё раз.' });
      }
      return false;
    }
  },

  discardChanges: async () => {
    const { ref, meta, baseline, versionId } = get();
    cancelDraftTimer();
    set({ rows: baseline, isDirty: false, draftState: 'idle', undoStack: [], redoStack: [] });
    if (ref && versionId && meta?.can_write) {
      try {
        await apiDiscardDraft(ref, versionId);
      } catch {
        // Черновик на сервере переживёт — на следующем «Применить» его заменит
        // актуальное состояние; молчим, чтобы не пугать пользователя.
      }
    }
  },

  undo: () => {
    const { undoStack, redoStack, rows } = get();
    if (undoStack.length === 0) return;
    const previous = undoStack[undoStack.length - 1];
    set({ undoStack: undoStack.slice(0, -1), redoStack: [...redoStack, rows] });
    get().setRows(previous, { skipHistory: true });
  },

  redo: () => {
    const { undoStack, redoStack, rows } = get();
    if (redoStack.length === 0) return;
    const next = redoStack[redoStack.length - 1];
    set({ redoStack: redoStack.slice(0, -1), undoStack: [...undoStack, rows] });
    get().setRows(next, { skipHistory: true });
  },

  selectVersion: async (versionId: string) => {
    const { ref } = get();
    if (!ref) return;
    await get().load({ ...ref, versionId });
  },

  setCoefficient: async (payload: CoefficientPayload | null) => {
    const { ref, versionId } = get();
    if (!ref) return;
    await setDocumentCoefficient(ref, payload);
    // Перечитываем документ целиком: цены в таблице показываются с
    // коэффициентом, значит их нужно пересчитать от исходных, а не подкрутить
    // на месте.
    await get().load({ ...ref, versionId: versionId ?? undefined });
  },

  setTab: (tab) => set({ tab }),

  setSheet: (sheet) => {
    const { adapter, rows } = get();
    set({
      sheet,
      // Колонки пересчитываются под вкладку: у разных листов исходного файла
      // свой набор столбцов.
      columns: adapter.columns(rowsOfSheet(adapter, rows, sheet)),
      // Отметки снимаем: они стоят на строках прежней вкладки, и «удалить
      // отмеченные» унесло бы строки, которых человек уже не видит.
      selectedKeys: new Set<string>(),
    });
  },
  setSearch: (search) => set({ search }),
  setSelected: (selectedKeys) => set({ selectedKeys }),

  heartbeat: async () => {
    const { ref } = get();
    if (!ref) return;
    try {
      set({ lock: await sendHeartbeat(ref) });
    } catch {
      // Присутствие — подсказка, а не функция: молчаливо переживаем сбой.
    }
  },

  reset: () => {
    cancelDraftTimer();
    set({ ...EMPTY, adapter: genericAdapter });
  },
}));
