/**
 * Compile-time exhaustiveness test for STATUS_COLORS-style objects.
 *
 * If any value of TaskStatus is added to the union but not present in the
 * object below, TypeScript will fail with TS2741 — the same error that was
 * seen in the build log when 'cancelled' was missing from Admin.tsx and
 * TaskStatus.tsx.
 *
 * This file is intentionally not a runtime test: `tsc` already runs during
 * `npm run build`, so a type error here will break the build automatically.
 *
 * How to use: add every new TaskStatus value to this object and to every
 * STATUS_COLORS constant across the app before merging.
 */
import type { TaskStatus } from '../types';

type StatusStyle = { bg: string; text: string; border: string };

// If a TaskStatus variant is missing here, tsc will fail with TS2741.
export const STATUS_COLORS_SHAPE: Record<TaskStatus, StatusStyle> = {
  pending:    { bg: '#fef9c3', text: '#854d0e', border: '#fde047' },
  processing: { bg: '#eff6ff', text: '#1d4ed8', border: '#93c5fd' },
  completed:  { bg: '#f0fdf4', text: '#15803d', border: '#86efac' },
  failed:     { bg: '#fef2f2', text: '#dc2626', border: '#fca5a5' },
  cancelled:  { bg: '#f8fafc', text: '#64748b', border: '#cbd5e1' },
  paused:     { bg: '#fffbeb', text: '#b45309', border: '#fcd34d' },
};
