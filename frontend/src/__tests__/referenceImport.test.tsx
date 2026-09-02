/**
 * Эталонный прайс: что уходит на сервер при «Применить».
 *
 * Фаза 4 плана `plans/2026-09-02-etalonnyy-prays-iz-smety.md`.
 *
 * Смысл экрана — подтверждение: система показывает догадку о дублях, а удаляет
 * человек. Поэтому проверяется ровно одно: без галочек на удаление не уходит
 * ничего, а с галочками — только отмеченное и в том виде, какой ждёт сервер
 * (источник, тип, id).
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('../api/catalog', () => ({
  referencePreview: vi.fn(),
  referenceApply: vi.fn(),
}));

import * as catalogApi from '../api/catalog';
import ReferenceImport from '../components/prices/ReferenceImport';

const preview = {
  items: [{ kind: 'work' as const, name: 'Кладка стен', unit: 'м3', price: 1000 }],
  plan: [
    {
      kind: 'work' as const,
      name: 'Кладка стен',
      unit: 'м3',
      price: 1000,
      action: 'reprice' as const,
      match: { id: 1, name: 'Кладка стен', unit: 'м3' },
      removed: [{ contractor: 'ООО Рога', price: 1200 }],
      reason: null,
    },
  ],
  skipped: {},
  summary: { add: 0, reprice: 1, blocked: 0, skipped: 0 },
  duplicates: {
    vectors_ready: true,
    candidates: [
      {
        source: 'price' as const, kind: 'work' as const, id: '7',
        name: 'Кладка стен кирпичных', unit: 'м3', price: 1300,
        score: 0.93, for_name: 'Кладка стен',
      },
      {
        source: 'cache' as const, kind: 'work' as const, id: 'c-1',
        name: 'Кладка кирпичных стен', unit: 'м3', price: 1500,
        score: 0.9, for_name: 'Кладка стен',
      },
    ],
  },
};

async function openPreview() {
  render(<ReferenceImport kind="work" onDone={() => {}} />);
  const input = screen.getByTestId('reference-file');
  const file = new File(['x'], 'смета.xlsx');
  fireEvent.change(input, { target: { files: [file] } });
  await screen.findByText('Эталонные цены из файла');
}

describe('ReferenceImport', () => {
  beforeEach(() => {
    // Вызовы копятся между тестами: без сброса `mock.calls[0]` — это вызов
    // соседнего теста, и проверка «что ушло на сервер» смотрит не туда.
    vi.clearAllMocks();
    vi.mocked(catalogApi.referencePreview).mockResolvedValue(preview);
    vi.mocked(catalogApi.referenceApply).mockResolvedValue({
      added: 0, updated: 1, blocked: 0, removed: 0, message: 'ок',
    });
  });

  it('показывает, какая цена исчезнет и чья она', async () => {
    await openPreview();
    expect(screen.getByText(/ООО Рога/)).toBeTruthy();
  });

  it('без галочек не удаляет ничего', async () => {
    await openPreview();
    fireEvent.click(screen.getByText('Применить'));

    await waitFor(() => expect(catalogApi.referenceApply).toHaveBeenCalled());
    const [items, remove] = vi.mocked(catalogApi.referenceApply).mock.calls[0];
    expect(items).toEqual(preview.items);
    expect(remove).toEqual([]);
  });

  it('удаляет только отмеченное', async () => {
    await openPreview();
    fireEvent.click(screen.getByLabelText('Удалить Кладка стен кирпичных'));
    fireEvent.click(screen.getByText('Применить и удалить 1'));

    await waitFor(() => expect(catalogApi.referenceApply).toHaveBeenCalled());
    const [, remove] = vi.mocked(catalogApi.referenceApply).mock.calls[0];
    expect(remove).toEqual([{ source: 'price', kind: 'work', id: '7' }]);
  });

  it('говорит, когда поиск по смыслу отключён', async () => {
    vi.mocked(catalogApi.referencePreview).mockResolvedValue({
      ...preview,
      duplicates: { vectors_ready: false, candidates: [] },
    });
    await openPreview();
    expect(screen.getByText(/нет векторов/)).toBeTruthy();
  });
});
