/// <reference types="node" />
/**
 * TDD tests for three TypeScript compilation bugs.
 * These tests fail before the fixes are applied and pass after.
 *
 * Bug 1 (TS6133): ProjectsSidebar.tsx — unused import `fetchProjects`
 * Bug 2 (TS6133): EstimateView.tsx   — unused state `optimizationResults` / `setOptimizationResults`
 * Bug 3 (TS2552): TaskStatus.tsx     — undefined name `taskStatus` (should be `task`)
 */

import { describe, it, expect, beforeAll } from 'vitest';
import { execSync } from 'child_process';
import { fileURLToPath } from 'url';
import path from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const FRONTEND_ROOT = path.resolve(__dirname, '../..');

function runTsc(): string {
  try {
    execSync('./node_modules/.bin/tsc --noEmit', {
      cwd: FRONTEND_ROOT,
      encoding: 'utf-8',
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    return '';
  } catch (err: unknown) {
    const e = err as { stdout?: string; stderr?: string };
    return (e.stdout ?? '') + (e.stderr ?? '');
  }
}

describe('TypeScript compilation — no unused-variable errors', () => {
  let tscOutput: string;

  beforeAll(() => {
    tscOutput = runTsc();
  });

  it('Bug 1: ProjectsSidebar.tsx should not have TS6133 for fetchProjects', () => {
    expect(tscOutput).not.toContain("'fetchProjects' is declared but its value is never read");
  });

  it('Bug 2a: EstimateView.tsx should not have TS6133 for optimizationResults', () => {
    expect(tscOutput).not.toContain("'optimizationResults' is declared but its value is never read");
  });

  it('Bug 2b: EstimateView.tsx should not have TS6133 for setOptimizationResults', () => {
    expect(tscOutput).not.toContain("'setOptimizationResults' is declared but its value is never read");
  });

  it('Bug 3: TaskStatus.tsx should not have TS2552 for taskStatus', () => {
    expect(tscOutput).not.toContain("Cannot find name 'taskStatus'");
  });

  it('tsc --noEmit exits with code 0 (no errors at all)', () => {
    expect(tscOutput).toBe('');
  });
});
