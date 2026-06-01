import { create } from 'zustand';

export interface TaskMeta {
  projectName: string;
  taskName: string;
}

interface NotificationStore {
  trackedTasks: Map<string, TaskMeta>;
  addTask: (id: string, meta: TaskMeta) => void;
  removeTask: (id: string) => void;
}

export const useNotificationStore = create<NotificationStore>((set) => ({
  trackedTasks: new Map(),
  addTask: (id, meta) =>
    set((state) => {
      const next = new Map(state.trackedTasks);
      next.set(id, meta);
      return { trackedTasks: next };
    }),
  removeTask: (id) =>
    set((state) => {
      const next = new Map(state.trackedTasks);
      next.delete(id);
      return { trackedTasks: next };
    }),
}));
