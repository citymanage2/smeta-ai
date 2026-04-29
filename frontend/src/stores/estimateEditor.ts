import { create } from 'zustand';
import {
  EstimateRow,
  EstimateVersionSummary,
  OptimizationProposal,
} from '../types';
import { getVersions, getVersion, saveRows as apiSaveRows } from '../api/estimateVersions';

const MAX_HISTORY = 50;

interface EstimateEditorState {
  taskId: string | null;
  versions: EstimateVersionSummary[];
  activeVersionId: string | null;
  activeRows: EstimateRow[];
  activeVersionMeta: EstimateVersionSummary | null;
  selectedRowIds: Set<string>;
  activeTab: 'all' | 'works' | 'materials';
  optimizationStatus: 'idle' | 'running';
  proposals: OptimizationProposal[];
  isDirty: boolean;
  undoStack: EstimateRow[][];
  redoStack: EstimateRow[][];

  loadVersions: (taskId: string) => Promise<void>;
  setActiveVersion: (versionId: string) => Promise<void>;
  updateRows: (rows: EstimateRow[]) => void;
  saveRows: () => Promise<void>;
  setSelectedRowIds: (ids: ReadonlySet<string>) => void;
  setActiveTab: (tab: 'all' | 'works' | 'materials') => void;
  setOptimizationStatus: (status: 'idle' | 'running') => void;
  setProposals: (proposals: OptimizationProposal[]) => void;
  addVersion: (version: EstimateVersionSummary) => void;
  undo: () => void;
  redo: () => void;
  deleteRows: (rowIds: string[]) => void;
  reset: () => void;
}

export const useEstimateEditorStore = create<EstimateEditorState>((set, get) => ({
  taskId: null,
  versions: [],
  activeVersionId: null,
  activeRows: [],
  activeVersionMeta: null,
  selectedRowIds: new Set(),
  activeTab: 'all',
  optimizationStatus: 'idle',
  proposals: [],
  isDirty: false,
  undoStack: [],
  redoStack: [],

  loadVersions: async (taskId: string) => {
    const versions = await getVersions(taskId);
    const active = versions.find((v) => !v.is_rolled_back) ?? versions[0] ?? null;
    set({ taskId, versions, activeVersionMeta: active ?? null, undoStack: [], redoStack: [] });

    if (active) {
      const full = await getVersion(taskId, active.id);
      set({ activeVersionId: active.id, activeRows: full.rows, isDirty: false });
    }
  },

  setActiveVersion: async (versionId: string) => {
    const { taskId } = get();
    if (!taskId) return;
    const full = await getVersion(taskId, versionId);
    const meta = get().versions.find((v) => v.id === versionId) ?? null;
    set({
      activeVersionId: versionId,
      activeRows: full.rows,
      activeVersionMeta: meta,
      isDirty: false,
      selectedRowIds: new Set(),
      undoStack: [],
      redoStack: [],
    });
  },

  updateRows: (rows: EstimateRow[]) => {
    const { activeRows, undoStack } = get();
    set({
      undoStack: [...undoStack.slice(-(MAX_HISTORY - 1)), activeRows],
      redoStack: [],
      activeRows: rows,
      isDirty: true,
    });
  },

  saveRows: async () => {
    const { taskId, activeVersionId, activeRows } = get();
    if (!taskId || !activeVersionId) return;
    await apiSaveRows(taskId, activeVersionId, activeRows);
    set({ isDirty: false });
    // Уведомляем родительское окно (если открыты в iframe из карточки проекта)
    try {
      window.parent.postMessage({ type: 'estimate-saved', taskId }, '*');
    } catch {
      // игнорируем, если нет родительского окна
    }
  },

  setSelectedRowIds: (ids: ReadonlySet<string>) => {
    set({ selectedRowIds: new Set(ids) });
  },

  setActiveTab: (tab) => set({ activeTab: tab }),

  setOptimizationStatus: (status) => set({ optimizationStatus: status }),

  setProposals: (proposals) => set({ proposals }),

  addVersion: (version) =>
    set((state) => ({ versions: [...state.versions, version] })),

  undo: () => {
    const { undoStack, redoStack, activeRows, taskId, activeVersionId } = get();
    if (undoStack.length === 0) return;
    const newUndoStack = [...undoStack];
    const previous = newUndoStack.pop()!;
    set({
      undoStack: newUndoStack,
      redoStack: [activeRows, ...redoStack.slice(0, MAX_HISTORY - 1)],
      activeRows: previous,
      isDirty: true,
    });
    if (taskId && activeVersionId) {
      apiSaveRows(taskId, activeVersionId, previous)
        .then(() => set({ isDirty: false }))
        .catch(() => {});
    }
  },

  redo: () => {
    const { undoStack, redoStack, activeRows, taskId, activeVersionId } = get();
    if (redoStack.length === 0) return;
    const newRedoStack = [...redoStack];
    const next = newRedoStack.shift()!;
    set({
      undoStack: [...undoStack.slice(-(MAX_HISTORY - 1)), activeRows],
      redoStack: newRedoStack,
      activeRows: next,
      isDirty: true,
    });
    if (taskId && activeVersionId) {
      apiSaveRows(taskId, activeVersionId, next)
        .then(() => set({ isDirty: false }))
        .catch(() => {});
    }
  },

  deleteRows: (rowIds: string[]) => {
    const { activeRows, undoStack } = get();
    const toDelete = new Set(rowIds);
    const newRows = activeRows.filter((r) => !toDelete.has(r.id));
    set({
      undoStack: [...undoStack.slice(-(MAX_HISTORY - 1)), activeRows],
      redoStack: [],
      activeRows: newRows,
      isDirty: true,
      selectedRowIds: new Set(),
    });
  },

  reset: () =>
    set({
      taskId: null,
      versions: [],
      activeVersionId: null,
      activeRows: [],
      activeVersionMeta: null,
      selectedRowIds: new Set(),
      activeTab: 'all',
      optimizationStatus: 'idle',
      proposals: [],
      isDirty: false,
      undoStack: [],
      redoStack: [],
    }),
}));
