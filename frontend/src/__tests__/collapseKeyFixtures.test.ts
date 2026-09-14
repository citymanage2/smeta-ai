import { describe, expect, it } from 'vitest';

import { collapseKey } from '../components/editor/collapse';
import type { RowKind } from '../components/editor/adapters/types';
import fixtures from '../utils/collapseKey.fixtures.json';

/**
 * Ключ свёртки — общий с сервером (запрос КП группирует выделение там же, где
 * редактор сворачивает строки на экране). Сервер гоняет тот же файл примеров:
 * backend/tests/test_kp_requests_create.py.
 */
describe('collapseKey: общие примеры с сервером', () => {
  for (const sample of fixtures.cases) {
    it(`${JSON.stringify(sample.name)} / ${JSON.stringify(sample.unit)} / ${sample.kind}`, () => {
      const row = { __key: 'r', name: sample.name, unit: sample.unit };
      const key = collapseKey(
        row, { nameKey: 'name', unitKey: 'unit', sharedKeys: [], sumKeys: [] },
        sample.kind as RowKind,
      );
      expect(key).toBe(sample.key);
    });
  }
});
