/**
 * Compile-time test: verifies that all functions used by TaskStatus.tsx
 * are actually exported from api/tasks.
 *
 * If any export is missing, tsc fails with TS2305 — the exact error seen in
 * the build log when cancelTask was absent from the committed api/tasks.ts.
 */
import {
  getTaskStatus,
  getTaskResults,
  sendMessage,
  cancelTask,
  downloadResult,
  type TaskStatusResponse,
  type ChatMessage,
} from '../api/tasks';

// Assign to exported const so tsc doesn't complain about unused symbols.
// These are never called at runtime — the file only needs to compile.
export const _exports = {
  getTaskStatus,
  getTaskResults,
  sendMessage,
  cancelTask,
  downloadResult,
} satisfies Record<string, (...args: never[]) => Promise<unknown>>;

export type { TaskStatusResponse, ChatMessage };
