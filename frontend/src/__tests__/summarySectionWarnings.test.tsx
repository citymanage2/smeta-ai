/**
 * Смена состава разделов и объяснение нового поведения.
 *
 * План: `plans/2026-08-04-pravki-svodnoy-uhodyat-v-smetu.md`, фаза 4.
 *
 * Раздел сводной перестал быть отдельной копией: правка в нём меняет саму
 * смету. Об этом надо сказать прямо — иначе человек правит сводную «для
 * тендера», не подозревая, что меняет исходную смету.
 *
 * И второе: убранный из состава раздел исчезает из сводной. Раньше это
 * происходило молча и вместе с правками во всех остальных разделах.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';

import SectionSelector from '../components/summary/SectionSelector';
import { WorkflowCard } from '../types/workflow';

vi.mock('../api/estimateVersions', () => ({
  getVersions: vi.fn(),
  initEstimateVersionFromResult: vi.fn(),
}));

import * as versionsApi from '../api/estimateVersions';

const CARDS = [
  { id: 'card-1', name: 'АР', stage: 'estimate', estimate_task_id: 'task-1' },
  { id: 'card-2', name: 'ВК', stage: 'estimate', estimate_task_id: 'task-2' },
] as unknown as WorkflowCard[];

const VERSIONS = [
  { id: 'v1', version_number: 0, version_label: 'original',
    version_display_name: 'Исходная смета', is_rolled_back: false,
    file_slot: 'estimate', created_at: '2026-07-01T10:00:00Z' },
];

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(versionsApi.getVersions).mockResolvedValue(VERSIONS as never);
});

describe('смена состава разделов', () => {
  it('предупреждает, какие разделы уйдут из сводной', async () => {
    render(
      <SectionSelector
        cards={CARDS}
        currentCardIds={['card-1', 'card-2']}
        onConfirm={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    // Снимаем отметку с «ВК» — этот раздел исчезнет из сводной.
    const vk = await screen.findByText('ВК');
    fireEvent.click(vk);

    const warning = await screen.findByTestId('sections-removal-warning');
    expect(warning).toHaveTextContent(/ВК/);
  });

  it('без потерь состава предупреждения нет', async () => {
    render(
      <SectionSelector
        cards={CARDS}
        currentCardIds={['card-1']}
        onConfirm={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    await screen.findByText('АР');
    expect(screen.queryByTestId('sections-removal-warning')).not.toBeInTheDocument();
  });

  it('сводная без разделов вообще не жалуется на потери', async () => {
    render(
      <SectionSelector cards={CARDS} onConfirm={vi.fn()} onClose={vi.fn()} />,
    );

    await screen.findByText('АР');
    expect(screen.queryByTestId('sections-removal-warning')).not.toBeInTheDocument();
  });
});

// --- Объяснение нового поведения в самой сводной ---------------------------

vi.mock('../api/summaryEstimate', () => ({
  getSummary: vi.fn(),
  updateSummary: vi.fn(),
  exportSummary: vi.fn(),
  createSummary: vi.fn(),
  customExport: vi.fn(),
}));

vi.mock('../components/editor/DocumentEditor', () => ({
  __esModule: true,
  default: () => <div data-testid="document-editor" />,
}));

import * as summaryApi from '../api/summaryEstimate';
import { useSummaryEditorStore } from '../stores/summaryEditorStore';
import SummaryEditorTabs from '../components/summary/SummaryEditorTabs';
import { OVERRIDES, SECTIONS } from './summaryRegressFixture';

describe('правка раздела меняет смету — и об этом сказано', () => {
  beforeEach(async () => {
    useSummaryEditorStore.getState().reset();
    vi.mocked(summaryApi.getSummary).mockResolvedValue({
      id: 'sum-1', project_id: 'proj-1', sections: SECTIONS, overrides: OVERRIDES,
      total_for_customer: 222647.81997720266,
      created_at: '2026-08-02T10:00:00Z', updated_at: '2026-08-02T10:00:00Z',
    } as never);
    await useSummaryEditorStore.getState().loadSummary('proj-1');
  });

  it('в разделе сказано, что правки уходят в смету', async () => {
    render(<SummaryEditorTabs projectId="proj-1" />);

    await screen.findByTestId('document-editor');
    expect(screen.getByText(/правки.*уход.*в смету/i)).toBeInTheDocument();
  });

  it('на вкладке «Сводная» этой пометки нет — там бланк, а не строки', async () => {
    render(<SummaryEditorTabs projectId="proj-1" />);
    await screen.findByTestId('document-editor');

    fireEvent.click(screen.getByRole('button', { name: 'Сводная' }));

    await waitFor(() => {
      expect(screen.queryByTestId('document-editor')).not.toBeInTheDocument();
    });
    expect(screen.queryByText(/правки.*уход.*в смету/i)).not.toBeInTheDocument();
  });
});
