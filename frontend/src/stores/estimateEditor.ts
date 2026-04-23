import { create } from 'zustand';
import {
  EstimateRow,
  EstimateVersionSummary,
  OptimizationProposal,
} from '../types';
import { getVersions, getVersion, saveRows as apiSaveRows } from '../api/estimateVersions';

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

  loadVersions: (taskId: string) => Promise<void>;
  setActiveVersion: (versionId: string) => Promise<void>;
  updateRows: (rows: EstimateRow[]) => void;
  saveRows: () => Promise<void>;
  setSelectedRowIds: (ids: ReadonlySet<string>) => void;
  setActiveTab: (tab: 'all' | 'works' | 'materials') => void;
  setOptimizationStatus: (status: 'idle' | 'running') => void;
  setProposals: (proposals: OptimizationProposal[]) => void;
  addVersion: (version: EstimateVersionSummary) => void;
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

  loadVersions: async (taskId: string) => {
    const versions = await getVersions(taskId);
    const active = versions.find((v) => !v.is_rolled_back) ?? versions[0] ?? null;
    set({ taskId, versions, activeVersionMeta: active ?? null });

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
    });
  },

  updateRows: (rows: EstimateRow[]) => {
    set({ activeRows: rows, isDirty: true });
  },

  saveRows: async () => {
    const { taskId, activeVersionId, activeRows } = get();
    if (!taskId || !activeVersionId) return;
    await apiSaveRows(taskId, activeVersionId, activeRows);
    set({ isDirty: false });
  },

  setSelectedRowIds: (ids: ReadonlySet<string>) => {
    set({ selectedRowIds: new Set(ids) });
  },

  setActiveTab: (tab) => set({ activeTab: tab }),

  setOptimizationStatus: (status) => set({ optimizationStatus: status }),

  setProposals: (proposals) => set({ proposals }),

  addVersion: (version) =>
    set((state) => ({ versions: [...state.versions, version] })),

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
    }),
}));
