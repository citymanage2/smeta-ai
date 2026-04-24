import { create } from 'zustand';

interface TaskSyncState {
  version: number;
  bump: () => void;
}

export const useTaskSync = create<TaskSyncState>((set) => ({
  version: 0,
  bump: () => set((s) => ({ version: s.version + 1 })),
}));
