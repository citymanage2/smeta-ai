/**
 * Сводная: разделы на едином редакторе.
 *
 * Фаза 7 плана `plans/2026-08-02-edinyy-redaktor-tablic.md`.
 *
 * Главное требование пользователя: бланк «Сводная» не трогаем, и цифры в нём
 * после переезда разделов не меняются ни на копейку. Поэтому первый блок —
 * регресс `calcSummary` на опорном наборе данных с точными числами.
 *
 * Остальное — про то, что раздел теперь редактируется тем же компонентом, что
 * смета: правки уходят через документный API, а страница сводной после
 * «Применить» перечитывает разделы, иначе бланк считал бы по старым строкам.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

import { calcSummary } from '../stores/summaryEditorStore';
import { OVERRIDES, SECTIONS } from './summaryRegressFixture';

// --- Регресс бланка «Сводная» ---------------------------------------------

describe('итоги сводной не изменились', () => {
  const calc = calcSummary(SECTIONS, OVERRIDES);

  it('итог для заказчика совпадает до копейки', () => {
    expect(calc.total_for_customer).toBeCloseTo(222647.81997720266, 6);
  });

  it('себестоимость, непредвиденные, прибыль, НДС и налог не сдвинулись', () => {
    expect(calc.subtotal_with_vat).toBeCloseTo(171809.196946355, 6);
    expect(calc.subtotal_without_vat).toBeCloseTo(140827.21061176638, 6);
    expect(calc.contingency_with_vat).toBeCloseTo(3436.1839389271, 6);
    expect(calc.profit).toBeCloseTo(35910.93870600043, 6);
    expect(calc.full_cost_without_vat).toBeCloseTo(179554.69353000214, 6);
    expect(calc.vat).toBeCloseTo(39502.03257660047, 6);
    expect(calc.other_tax).toBeCloseTo(3591.093870600043, 6);
  });

  it('строки работ, материалов и доп. расходов считаются как раньше', () => {
    expect(calc.works_with_vat).toBeCloseTo(26202.6093465, 6);
    expect(calc.materials_with_vat).toBeCloseTo(71090.09808, 6);
    expect(calc.transport_with_vat).toBeCloseTo(2918.781222795, 6);
    expect(calc.overhead_with_vat).toBeCloseTo(3891.70829706, 6);
    expect(calc.daily_workers_with_vat).toBeCloseTo(10000, 6);
    expect(calc.bank_guarantee_with_vat).toBeCloseTo(14640, 6);
  });

  it('разделы считаются по своим налогам, вычет стоимости не даёт', () => {
    const [ar, ov] = calc.section_totals;
    expect(ar.works_raw).toBeCloseTo(17932.53125, 6);      // вычет −3 × 1000 не вычтен
    expect(ar.works_with_vat).toBeCloseTo(20981.0615625, 6);
    expect(ar.materials_with_vat).toBeCloseTo(22137.59808, 6);
    expect(ov.works_with_vat).toBeCloseTo(5221.547784000001, 6);
    expect(ov.materials_with_vat).toBeCloseTo(48952.5, 6);
  });

  it('скрытые строки бланка в себестоимость не входят', () => {
    // 'cleanup' и 'ppr' скрыты пользователем: значения считаются и показываются,
    // но в «ИТОГО себестоимость» не попадают.
    expect(calc.cleanup_with_vat).toBeGreaterThan(0);
    expect(calc.ppr_with_vat).toBeGreaterThan(0);
    const withThem = calc.subtotal_with_vat + calc.cleanup_with_vat + calc.ppr_with_vat;
    expect(withThem).toBeGreaterThan(calc.subtotal_with_vat);
  });
});

// --- Разделы в едином редакторе -------------------------------------------

vi.mock('../api/summaryEstimate', () => ({
  getSummary: vi.fn(),
  updateSummary: vi.fn(),
  exportSummary: vi.fn(),
  createSummary: vi.fn(),
  customExportSummary: vi.fn(),
}));

// Ядро редактора подменяем: здесь проверяется проводка (какой документ открыт и
// что происходит после «Применить»), а само ядро покрыто своими тестами.
vi.mock('../components/editor/DocumentEditor', () => ({
  __esModule: true,
  default: ({ cardId, kind, onApplied }: {
    cardId: string; kind: string; onApplied?: () => void;
  }) => (
    <div data-testid="document-editor" data-card-id={cardId} data-kind={kind}>
      <button onClick={() => onApplied?.()}>применить-в-тесте</button>
    </div>
  ),
}));

import * as summaryApi from '../api/summaryEstimate';
import { useSummaryEditorStore } from '../stores/summaryEditorStore';
import SummaryEditorTabs from '../components/summary/SummaryEditorTabs';

function summaryResponse(sections = SECTIONS) {
  return {
    id: 'sum-1',
    project_id: 'proj-1',
    sections,
    overrides: OVERRIDES,
    total_for_customer: 222647.81997720266,
    created_at: '2026-08-02T10:00:00Z',
    updated_at: '2026-08-02T10:00:00Z',
  };
}

beforeEach(async () => {
  vi.clearAllMocks();
  useSummaryEditorStore.getState().reset();
  vi.mocked(summaryApi.getSummary).mockResolvedValue(summaryResponse());
  vi.mocked(summaryApi.updateSummary).mockImplementation(
    async () => summaryResponse() as never,
  );
  await useSummaryEditorStore.getState().loadSummary('proj-1');
});

describe('вкладки разделов', () => {
  it('раздел открывается единым редактором, а не своей таблицей', async () => {
    render(<SummaryEditorTabs projectId="proj-1" />);

    const editor = await screen.findByTestId('document-editor');
    expect(editor.getAttribute('data-card-id')).toBe('card-1');
    expect(editor.getAttribute('data-kind')).toBe('summary-section');
  });

  it('вкладка «Сводная» показывает прежний бланк', async () => {
    render(<SummaryEditorTabs projectId="proj-1" />);

    screen.getByRole('button', { name: 'Сводная' }).click();
    await waitFor(() => {
      expect(screen.queryByTestId('document-editor')).not.toBeInTheDocument();
    });
    expect(screen.getByText(/ИТОГО по смете для Заказчика/i)).toBeInTheDocument();
  });

  it('после «Применить» разделы перечитываются, иначе бланк считал бы по старым строкам', async () => {
    render(<SummaryEditorTabs projectId="proj-1" />);
    await screen.findByTestId('document-editor');

    const updated = SECTIONS.map((section, index) =>
      (index === 0
        ? { ...section, rows: section.rows.map((r) => ({ ...r, price_work: 1 })) }
        : section),
    );
    vi.mocked(summaryApi.getSummary).mockResolvedValue(summaryResponse(updated));

    screen.getByText('применить-в-тесте').click();

    await waitFor(() => {
      expect(useSummaryEditorStore.getState().sections[0].rows[1].price_work).toBe(1);
    });
  });

  it('перечитывание разделов не стирает несохранённый налог раздела', async () => {
    // Налог раздела правится в бланке и живёт в тех же данных, что строки.
    // Если бы перечитывание брало раздел с сервера целиком, правка исчезла бы
    // прямо во время работы — человек бы даже не понял, куда.
    render(<SummaryEditorTabs projectId="proj-1" />);
    await screen.findByTestId('document-editor');

    useSummaryEditorStore.getState().updateSectionTaxPct(0, 11);
    screen.getByText('применить-в-тесте').click();

    await waitFor(() => {
      expect(useSummaryEditorStore.getState().sections[0].tax_pct).toBe(11);
    });
    // Итог с несохранённым бланком не сохраняем: сохранит кнопка «Сохранить».
    expect(summaryApi.updateSummary).not.toHaveBeenCalled();
  });

  it('пересчитанный итог сохраняется, чтобы карточка проекта не показывала старую сумму', async () => {
    render(<SummaryEditorTabs projectId="proj-1" />);
    await screen.findByTestId('document-editor');
    vi.mocked(summaryApi.updateSummary).mockClear();

    screen.getByText('применить-в-тесте').click();

    await waitFor(() => {
      expect(summaryApi.updateSummary).toHaveBeenCalled();
    });
    const [, body] = vi.mocked(summaryApi.updateSummary).mock.calls[0];
    expect(body.total_for_customer).toBeCloseTo(222647.81997720266, 6);
  });
});

describe('хранилище строк', () => {
  it('страница сводной больше не правит строки разделов сама', () => {
    // Строки раздела пишет только документный API. Метода, которым страница
    // меняла строки, в сторе быть не должно — иначе у строк снова два писателя.
    expect('updateSectionRows' in useSummaryEditorStore.getState()).toBe(false);
  });
});
