/**
 * TDD tests for batch progress parsing utility.
 * These must fail before src/utils/batchProgress.ts is created.
 */
import { describe, it, expect } from 'vitest';
import { parseBatchProgress } from '../utils/batchProgress';

describe('parseBatchProgress', () => {
  it('returns null for non-batch messages', () => {
    expect(parseBatchProgress('Загрузка базы расценок...')).toBeNull();
    expect(parseBatchProgress('')).toBeNull();
    expect(parseBatchProgress('Составление сметы...')).toBeNull();
  });

  it('parses "Обработка батча N из M" message', () => {
    const result = parseBatchProgress('Обработка батча 2 из 5 (10 позиций)...');
    expect(result).not.toBeNull();
    expect(result!.current).toBe(2);
    expect(result!.total).toBe(5);
  });

  it('parses the first batch', () => {
    const result = parseBatchProgress('Обработка батча 1 из 3 (10 позиций)...');
    expect(result!.current).toBe(1);
    expect(result!.total).toBe(3);
  });

  it('parses the last batch', () => {
    const result = parseBatchProgress('Обработка батча 3 из 3 (5 позиций)...');
    expect(result!.current).toBe(3);
    expect(result!.total).toBe(3);
  });

  it('returns null for unrelated numeric strings', () => {
    expect(parseBatchProgress('Этап 1 из 3')).toBeNull();
  });
});
