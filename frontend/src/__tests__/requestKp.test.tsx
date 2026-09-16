/**
 * «Запросить КП» в редакторе и запросы КП в карточке сметы.
 *
 * План: plans/2026-09-14-zapros-kp.md, фаза 3.
 *
 * Главное, что здесь закреплено:
 * * кнопка есть на четырёх стадиях, неактивна без выделения и не видна отделу
 *   производства;
 * * выделение свёрнутой группы — это все её строки документа, а не одна;
 * * группу без активных сотрудников роли отправить нельзя, причина видна;
 * * позиция без типа не уходит, пока человек сам её не отнёс.
 */
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import { fireEvent } from '@testing-library/dom';

vi.mock('../api/documents', async () => {
  const actual = await vi.importActual<typeof import('../api/documents')>('../api/documents');
  return {
    ...actual,
    getDocumentMeta: vi.fn(),
    getDocumentRows: vi.fn(),
    saveDraft: vi.fn().mockResolvedValue(undefined),
    discardDraft: vi.fn().mockResolvedValue(undefined),
    applyDocument: vi.fn(),
    sendHeartbeat: vi.fn().mockResolvedValue(null),
    getDocumentHistory: vi.fn().mockResolvedValue([]),
    getAnalogsState: vi.fn().mockResolvedValue({
      run_id: null, status: null, processed: 0, total: 0,
      results: [], error: null, created_at: null,
    }),
  };
});

vi.mock('../api/kpRequests', async () => {
  const actual = await vi.importActual<typeof import('../api/kpRequests')>('../api/kpRequests');
  return {
    ...actual,
    previewKpRequest: vi.fn(),
    createKpRequests: vi.fn(),
    listCardKpRequests: vi.fn(),
    getKpRequest: vi.fn(),
    cancelKpRequest: vi.fn(),
    reopenKpRequest: vi.fn(),
    addKpRequestFiles: vi.fn(),
    deleteKpRequestFile: vi.fn(),
  };
});

import * as api from '../api/documents';
import * as kpApi from '../api/kpRequests';
import DocumentEditor from '../components/editor/DocumentEditor';
import RequestKpDialog from '../components/kp/RequestKpDialog';
import CardKpRequests from '../components/kp/CardKpRequests';
import { useDocumentEditorStore } from '../stores/documentEditor';
import { useAuthStore } from '../stores/auth';
import type { KpItem, KpPreview, KpRequestBrief } from '../types/kp';

function meta(overrides: Partial<api.DocumentMeta> = {}): api.DocumentMeta {
  return {
    card_id: 'card-1', kind: 'estimate', row_format: 'estimate', file_slot: 'estimate',
    task_id: 'task-1', task_type: 'ESTIMATE_FROM_LIST', task_status: 'completed',
    can_write: true, readonly_reason: null, rev: 0,
    active_version_id: 'v1',
    versions: [{
      id: 'v1', version_number: 0, version_label: 'original',
      version_display_name: 'V0 — Оригинал', is_rolled_back: false,
      created_at: '2026-08-01T10:00:00Z', overhead_pct: 3, transport_pct: 3,
      contingency_pct: 0, expenses_overridden: false,
    }],
    coefficient: null, has_draft: false, draft_updated_at: null, lock: null,
    project: { overhead_pct: 3, transport_pct: 3, name: 'ЖК Северный' },
    ...overrides,
  };
}

// Штукатурка дважды (регистр и пробел разные) — в свёрнутом виде одна строка.
const ROWS = [
  { id: 'r1', type: 'work', name: 'Штукатурка стен', unit: 'м2', qty: 80,
    price_work: 450, price_material: null, sheet: 'Раздел 1' },
  { id: 'r2', type: 'material', name: 'Кирпич', unit: 'шт', qty: 500,
    price_work: null, price_material: 25, sheet: 'Раздел 1' },
  { id: 'r3', type: 'work', name: 'штукатурка  стен', unit: 'м2', qty: 40.5,
    price_work: 450, price_material: null, sheet: 'Раздел 2' },
];

// react-data-grid в jsdom без размеров не рисует ячеек — тот же приём, что в
// editorCollapse.test.tsx.
let restoreWidth: PropertyDescriptor | undefined;
let originalRect: typeof HTMLElement.prototype.getBoundingClientRect;

beforeAll(() => {
  restoreWidth = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientWidth');
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
    configurable: true, value: 2000,
  });
  originalRect = HTMLElement.prototype.getBoundingClientRect;
  HTMLElement.prototype.getBoundingClientRect = function fake() {
    return { width: 2000, height: 600, top: 0, left: 0, right: 2000,
      bottom: 600, x: 0, y: 0, toJSON: () => ({}) } as DOMRect;
  };
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  Element.prototype.scrollIntoView = () => {};
});

afterAll(() => {
  if (restoreWidth) Object.defineProperty(HTMLElement.prototype, 'clientWidth', restoreWidth);
  HTMLElement.prototype.getBoundingClientRect = originalRect;
});

function item(overrides: Partial<KpItem>): KpItem {
  return {
    id: null, position: 0, item_type: null, name: 'Позиция', unit: 'шт', qty: 1,
    sheet: null, source_no: null, source_row_ids: [], selected_offer_id: null,
    ...overrides,
  };
}

function preview(overrides: {
  material?: KpItem[]; work?: KpItem[]; unknown?: KpItem[];
  supply?: number; contractors?: number; skipped?: number; missing?: string[];
} = {}): KpPreview {
  return {
    version_id: 'v1',
    groups: {
      material: {
        category: 'material', target_role: 'supply_manager',
        employees: overrides.supply ?? 2, items: overrides.material ?? [],
      },
      work: {
        category: 'work', target_role: 'contractor_manager',
        employees: overrides.contractors ?? 1, items: overrides.work ?? [],
      },
      unknown: { category: 'unknown', items: overrides.unknown ?? [] },
    },
    skipped: overrides.skipped ?? 0,
    missing_row_ids: overrides.missing ?? [],
  };
}

function brief(overrides: Partial<KpRequestBrief>): KpRequestBrief {
  return {
    id: 'kp-1', project_id: 'p-1', project_name: 'ЖК Северный', card_id: 'card-1',
    card_name: 'Корпус 1', source_kind: 'estimate', category: 'material',
    target_role: 'supply_manager', status: 'new', author_id: 7, author_name: 'Анна',
    author_comment: null, taken_by_id: null, taken_by_name: null, taken_at: null,
    completed_by_id: null, completed_by_name: null, completed_at: null,
    applied_at: null, items_count: 3, files_count: 1, confirmed_prices_count: 0,
    created_at: '2026-09-14T09:00:00Z', updated_at: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  useDocumentEditorStore.getState().reset();
  useAuthStore.getState().setAuth('token', 'project_manager', 'Анна');
  vi.mocked(api.getDocumentMeta).mockResolvedValue(meta());
  vi.mocked(api.getDocumentRows).mockResolvedValue({
    version_id: 'v1', rev: 0, rows: ROWS, draft_rows: null,
  });
  vi.mocked(kpApi.previewKpRequest).mockResolvedValue(preview());
  vi.mocked(kpApi.listCardKpRequests).mockResolvedValue([]);
});

const kpButton = () => screen.getByRole('button', { name: /Запросить КП/ });

// --- Кнопка в редакторе ------------------------------------------------------

describe('кнопка «Запросить КП» в редакторе', () => {
  it('неактивна без выделения и активна с ним', async () => {
    render(<DocumentEditor cardId="card-1" kind="estimate" />);
    await screen.findByTestId('document-editor-grid');

    expect(kpButton()).toBeDisabled();

    // Первый чекбокс — «отметить всё» в шапке, второй — первая строка.
    fireEvent.click(screen.getAllByRole('checkbox')[1]);
    await waitFor(() => expect(kpButton()).toBeEnabled());
    expect(kpButton()).toHaveTextContent('(1)');
  });

  it.each(['list', 'completeness', 'estimate', 'optimization'] as const)(
    'есть на стадии %s', async (kind) => {
      const generic = kind === 'list' || kind === 'completeness';
      vi.mocked(api.getDocumentMeta).mockResolvedValue(meta({
        kind, row_format: generic ? 'generic' : 'estimate',
      }));
      if (generic) {
        vi.mocked(api.getDocumentRows).mockResolvedValue({
          version_id: 'v1', rev: 0, draft_rows: null,
          rows: [{ row_id: 'g1', cells: { 'Тип': 'Работа', 'Наименование': 'Кладка', 'Кол-во': 1 } }],
        });
      }
      render(<DocumentEditor cardId="card-1" kind={kind} />);
      await screen.findByTestId('document-editor-grid');
      expect(kpButton()).toBeInTheDocument();
    },
  );

  it('нет в разделе сводной и в исходном файле заказчика', async () => {
    vi.mocked(api.getDocumentMeta).mockResolvedValue(meta({ kind: 'summary-section' }));
    const { unmount } = render(<DocumentEditor cardId="card-1" kind="summary-section" />);
    await screen.findByTestId('document-editor-grid');
    expect(screen.queryByRole('button', { name: /Запросить КП/ })).toBeNull();
    unmount();

    useDocumentEditorStore.getState().reset();
    vi.mocked(api.getDocumentMeta).mockResolvedValue(meta({
      can_write: false, readonly_reason: 'input_readonly', file_slot: 'input',
    }));
    render(<DocumentEditor cardId="card-1" kind="estimate" fileSlot="input" fileIndex={0} />);
    await screen.findByTestId('document-editor-grid');
    expect(screen.queryByRole('button', { name: /Запросить КП/ })).toBeNull();
  });

  it('скрыта отделу производства', async () => {
    useAuthStore.getState().setAuth('token', 'supply_manager', 'Олег');
    render(<DocumentEditor cardId="card-1" kind="estimate" />);
    await screen.findByTestId('document-editor-grid');
    expect(screen.queryByRole('button', { name: /Запросить КП/ })).toBeNull();
  });

  it('выделение свёрнутой группы отправляет все её строки', async () => {
    render(<DocumentEditor cardId="card-1" kind="estimate" />);
    await screen.findByTestId('document-editor-grid');
    fireEvent.click(screen.getByRole('button', { name: /Свернуть дубли/ }));
    await waitFor(() => expect(screen.getByTestId('document-editor-grid'))
      .toHaveAttribute('data-row-count', '2'));

    // Первая строка свёрнутой таблицы — группа из двух штукатурок.
    fireEvent.click(screen.getAllByRole('checkbox')[1]);
    await screen.findByText('Выбрано: 2');
    fireEvent.click(kpButton());

    await waitFor(() => expect(kpApi.previewKpRequest).toHaveBeenCalled());
    const body = vi.mocked(kpApi.previewKpRequest).mock.calls[0][0];
    expect([...body.row_ids].sort()).toEqual(['r1', 'r3']);
    expect(body).toMatchObject({ card_id: 'card-1', kind: 'estimate', version_id: 'v1' });
  });

  it('предупреждает о непринятых правках: в запрос уйдёт применённый документ', async () => {
    render(<DocumentEditor cardId="card-1" kind="estimate" />);
    await screen.findByTestId('document-editor-grid');

    const store = useDocumentEditorStore.getState();
    store.setRows(store.rows.map((r, i) => (i === 0 ? { ...r, qty: 99 } : r)));
    fireEvent.click(screen.getAllByRole('checkbox')[1]);
    fireEvent.click(kpButton());

    expect(await screen.findByText(/непринятые правки/i)).toBeInTheDocument();
  });
});

// --- Окно запроса ------------------------------------------------------------

function renderDialog(props: Partial<React.ComponentProps<typeof RequestKpDialog>> = {}) {
  const onCreated = vi.fn();
  const onClose = vi.fn();
  render(
    <RequestKpDialog
      cardId="card-1" kind="estimate" versionId="v1" rowIds={['r1', 'r2', 'r3']}
      isDirty={false} onClose={onClose} onCreated={onCreated} {...props}
    />,
  );
  return { onCreated, onClose };
}

const sendButton = () => screen.getByRole('button', { name: /^Отправить/ });

describe('окно «Запросить КП»', () => {
  it('разбивает позиции на материалы и работы с числом сотрудников роли', async () => {
    vi.mocked(kpApi.previewKpRequest).mockResolvedValue(preview({
      material: [item({ name: 'Кирпич', source_row_ids: ['r2'], item_type: 'material' })],
      work: [item({ name: 'Штукатурка стен', unit: 'м2', qty: 120.5, source_row_ids: ['r1', 'r3'], item_type: 'work' })],
      supply: 2, contractors: 1,
    }));
    renderDialog();

    const material = await screen.findByTestId('kp-group-material');
    expect(material).toHaveTextContent('Материалы');
    expect(material).toHaveTextContent('отдел снабжения');
    expect(material).toHaveTextContent('2 сотрудника');
    expect(material).toHaveTextContent('Кирпич');
    const work = screen.getByTestId('kp-group-work');
    expect(work).toHaveTextContent('подрядчики');
    expect(work).toHaveTextContent('1 сотрудник');
    expect(work).toHaveTextContent('120,5');
    expect(sendButton()).toBeEnabled();
  });

  it('группа без сотрудников роли заблокирована с причиной и не отправляется', async () => {
    vi.mocked(kpApi.previewKpRequest).mockResolvedValue(preview({
      material: [item({ name: 'Кирпич', source_row_ids: ['r2'], item_type: 'material' })],
      work: [item({ name: 'Штукатурка стен', source_row_ids: ['r1', 'r3'], item_type: 'work' })],
      supply: 0, contractors: 1,
    }));
    vi.mocked(kpApi.createKpRequests).mockResolvedValue({ requests: [brief({ category: 'work' })] });
    const { onCreated } = renderDialog();

    const material = await screen.findByTestId('kp-group-material');
    expect(material).toHaveTextContent(/Нет активных сотрудников/);
    expect(material).toHaveTextContent('Менеджер снабжения');

    fireEvent.click(sendButton());
    await waitFor(() => expect(kpApi.createKpRequests).toHaveBeenCalled());
    const [payload] = vi.mocked(kpApi.createKpRequests).mock.calls[0];
    expect(payload.groups).toEqual([{ category: 'work', row_ids: ['r1', 'r3'] }]);
    await waitFor(() => expect(onCreated).toHaveBeenCalled());
  });

  it('если отправлять некому, кнопка неактивна и причина видна', async () => {
    vi.mocked(kpApi.previewKpRequest).mockResolvedValue(preview({
      material: [item({ name: 'Кирпич', source_row_ids: ['r2'], item_type: 'material' })],
      supply: 0,
    }));
    renderDialog();

    await screen.findByTestId('kp-group-material');
    expect(sendButton()).toBeDisabled();
    expect(screen.getByTestId('kp-send-blocked')).toHaveTextContent(/некому/i);
  });

  it('позиции без типа обязательно распределить', async () => {
    vi.mocked(kpApi.previewKpRequest).mockResolvedValue(preview({
      work: [item({ name: 'Штукатурка стен', source_row_ids: ['r1'], item_type: 'work' })],
      unknown: [item({ name: 'Гидроизоляция', source_row_ids: ['u1', 'u2'] })],
    }));
    vi.mocked(kpApi.createKpRequests).mockResolvedValue({ requests: [] });
    renderDialog({ rowIds: ['r1', 'u1', 'u2'] });

    const unknown = await screen.findByTestId('kp-group-unknown');
    expect(sendButton()).toBeDisabled();
    expect(screen.getByTestId('kp-send-blocked')).toHaveTextContent(/без типа/i);

    fireEvent.click(within(unknown).getByRole('radio', { name: 'Материал' }));
    await waitFor(() => expect(sendButton()).toBeEnabled());

    // Отнесённая позиция появляется в своей группе.
    expect(screen.getByTestId('kp-group-material')).toHaveTextContent('Гидроизоляция');

    fireEvent.click(sendButton());
    await waitFor(() => expect(kpApi.createKpRequests).toHaveBeenCalled());
    const [payload] = vi.mocked(kpApi.createKpRequests).mock.calls[0];
    expect(payload.groups).toEqual([
      { category: 'material', row_ids: ['u1', 'u2'] },
      { category: 'work', row_ids: ['r1'] },
    ]);
  });

  it('позицию без типа нельзя отнести к роли без сотрудников, но можно не запрашивать', async () => {
    vi.mocked(kpApi.previewKpRequest).mockResolvedValue(preview({
      work: [item({ name: 'Штукатурка стен', source_row_ids: ['r1'], item_type: 'work' })],
      unknown: [item({ name: 'Гидроизоляция', source_row_ids: ['u1'] })],
      supply: 0,
    }));
    vi.mocked(kpApi.createKpRequests).mockResolvedValue({ requests: [] });
    renderDialog({ rowIds: ['r1', 'u1'] });

    const unknown = await screen.findByTestId('kp-group-unknown');
    expect(within(unknown).getByRole('radio', { name: 'Материал' })).toBeDisabled();
    fireEvent.click(within(unknown).getByRole('radio', { name: 'Не запрашивать' }));
    await waitFor(() => expect(sendButton()).toBeEnabled());

    fireEvent.click(sendButton());
    await waitFor(() => expect(kpApi.createKpRequests).toHaveBeenCalled());
    expect(vi.mocked(kpApi.createKpRequests).mock.calls[0][0].groups)
      .toEqual([{ category: 'work', row_ids: ['r1'] }]);
  });

  it('отправляет комментарий, версию из предпросмотра и файлы', async () => {
    vi.mocked(kpApi.previewKpRequest).mockResolvedValue({
      ...preview({ material: [item({ name: 'Кирпич', source_row_ids: ['r2'] })] }),
      version_id: 'v7',
    });
    vi.mocked(kpApi.createKpRequests).mockResolvedValue({ requests: [] });
    renderDialog({ versionId: null });

    await screen.findByTestId('kp-group-material');
    fireEvent.change(screen.getByLabelText('Комментарий к запросу'), {
      target: { value: 'Нужна доставка на объект' },
    });
    const spec = new File(['%PDF'], 'ТЗ.pdf', { type: 'application/pdf' });
    fireEvent.change(screen.getByLabelText('Приложить файлы'), { target: { files: [spec] } });
    expect(await screen.findByText('ТЗ.pdf')).toBeInTheDocument();

    fireEvent.click(sendButton());
    await waitFor(() => expect(kpApi.createKpRequests).toHaveBeenCalled());
    const [payload, files] = vi.mocked(kpApi.createKpRequests).mock.calls[0];
    expect(payload).toMatchObject({
      card_id: 'card-1', kind: 'estimate', version_id: 'v7',
      author_comment: 'Нужна доставка на объект',
    });
    expect(files).toHaveLength(1);
    expect(files[0].name).toBe('ТЗ.pdf');
  });

  it('файл неподдерживаемого типа не прикладывается, причина видна', async () => {
    vi.mocked(kpApi.previewKpRequest).mockResolvedValue(preview({
      material: [item({ name: 'Кирпич', source_row_ids: ['r2'] })],
    }));
    renderDialog();
    await screen.findByTestId('kp-group-material');

    const bad = new File(['MZ'], 'setup.exe', { type: 'application/octet-stream' });
    fireEvent.change(screen.getByLabelText('Приложить файлы'), { target: { files: [bad] } });

    expect(await screen.findByText(/setup\.exe/)).toHaveTextContent(/не поддерживается/);
    expect(screen.queryByRole('button', { name: /Убрать файл setup\.exe/ })).toBeNull();
  });

  it('говорит, сколько строк не попадёт в запрос и почему', async () => {
    vi.mocked(kpApi.previewKpRequest).mockResolvedValue(preview({
      material: [item({ name: 'Кирпич', source_row_ids: ['r2'] })],
      skipped: 1, missing: ['new-1'],
    }));
    renderDialog();
    await screen.findByTestId('kp-group-material');
    expect(screen.getByText(/Разделы и строки без наименования/)).toHaveTextContent('1');
    expect(screen.getByText(/нет в применённом документе/)).toHaveTextContent('1');
  });

  it('ошибку сервера показывает текстом и окно не закрывает', async () => {
    vi.mocked(kpApi.previewKpRequest).mockResolvedValue(preview({
      material: [item({ name: 'Кирпич', source_row_ids: ['r2'] })],
    }));
    vi.mocked(kpApi.createKpRequests).mockRejectedValue({
      response: { status: 422, data: { detail: 'Нет ни одного активного сотрудника с ролью «Менеджер снабжения»' } },
    });
    const { onCreated, onClose } = renderDialog();
    await screen.findByTestId('kp-group-material');

    fireEvent.click(sendButton());
    expect(await screen.findByRole('alert')).toHaveTextContent('Нет ни одного активного сотрудника');
    expect(onCreated).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });
});

// --- Запросы в карточке ------------------------------------------------------

// Токен с id сотрудника: «Отменить» показывается автору запроса.
function loginWithId(role: string, id: number) {
  const payload = btoa(JSON.stringify({ sub: String(id), role }));
  useAuthStore.getState().setAuth(`h.${payload}.s`, role, 'Анна');
}

describe('запросы КП в карточке сметы', () => {
  beforeEach(() => loginWithId('project_manager', 7));

  it('без запросов блока нет', async () => {
    const { container } = render(<CardKpRequests cardId="card-1" />);
    await waitFor(() => expect(kpApi.listCardKpRequests).toHaveBeenCalledWith('card-1'));
    expect(container).toBeEmptyDOMElement();
  });

  it('показывает категорию, статус, кто взял, позиции, вложения и бейдж полученных КП', async () => {
    vi.mocked(kpApi.listCardKpRequests).mockResolvedValue([
      brief({ id: 'a', category: 'material', status: 'in_progress', taken_by_name: 'Олег' }),
      brief({ id: 'b', category: 'work', status: 'done', items_count: 5, files_count: 0 }),
      brief({ id: 'c', category: 'work', status: 'done', applied_at: '2026-09-14T12:00:00Z' }),
    ]);
    render(<CardKpRequests cardId="card-1" />);

    const rowA = await screen.findByTestId('kp-request-a');
    expect(rowA).toHaveTextContent('Материалы');
    expect(rowA).toHaveTextContent('В работе');
    expect(rowA).toHaveTextContent('Олег');
    expect(rowA).toHaveTextContent('3');
    expect(screen.getByTestId('kp-request-b')).toHaveTextContent('Завершён');
    // Завершён, но не применён — один из двух завершённых.
    expect(screen.getByText('КП получены: 1')).toBeInTheDocument();
  });

  it('«Отменить» — у нового и взятого в работу запроса, у завершённого нет', async () => {
    vi.mocked(kpApi.listCardKpRequests).mockResolvedValue([
      brief({ id: 'a', status: 'new' }),
      brief({ id: 'b', status: 'done' }),
    ]);
    vi.mocked(kpApi.cancelKpRequest).mockResolvedValue({} as never);
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<CardKpRequests cardId="card-1" />);

    const rowA = await screen.findByTestId('kp-request-a');
    expect(within(screen.getByTestId('kp-request-b')).queryByRole('button', { name: 'Отменить' })).toBeNull();

    fireEvent.click(within(rowA).getByRole('button', { name: 'Отменить' }));
    await waitFor(() => expect(kpApi.cancelKpRequest).toHaveBeenCalledWith('a'));
    await waitFor(() => expect(kpApi.listCardKpRequests).toHaveBeenCalledTimes(2));
  });

  it('чужой запрос проектный менеджер не отменяет, руководитель продаж — отменяет', async () => {
    vi.mocked(kpApi.listCardKpRequests).mockResolvedValue([brief({ id: 'a', status: 'new', author_id: 99 })]);
    const { unmount } = render(<CardKpRequests cardId="card-1" />);
    const rowA = await screen.findByTestId('kp-request-a');
    expect(within(rowA).queryByRole('button', { name: 'Отменить' })).toBeNull();
    unmount();

    loginWithId('head_of_sales', 5);
    render(<CardKpRequests cardId="card-1" />);
    const again = await screen.findByTestId('kp-request-a');
    expect(within(again).getByRole('button', { name: 'Отменить' })).toBeInTheDocument();
  });

  it('«Открыть» показывает позиции и вложения автора со ссылкой на скачивание', async () => {
    vi.mocked(kpApi.listCardKpRequests).mockResolvedValue([brief({ id: 'a' })]);
    vi.mocked(kpApi.getKpRequest).mockResolvedValue({
      ...brief({ id: 'a', author_comment: 'Срочно' }),
      source_task_id: 't', source_version_id: 'v1', report: null,
      pricelist_status: null, pricelist_summary: null, pricelist_error: null,
      pricelist_written_at: null, applied_version_id: null,
      items: [item({ id: 'i1', name: 'Кирпич', unit: 'шт', qty: 500 })],
      files: [{
        id: 'f1', file_name: 'ТЗ.pdf', mime_type: 'application/pdf', size_bytes: 2048,
        uploaded_by: 7, uploaded_by_name: 'Анна', created_at: '2026-09-14T09:00:00Z',
      }],
      permissions: { can_work: false, can_manage: true, can_edit_files: true },
    });
    render(<CardKpRequests cardId="card-1" />);

    fireEvent.click(await screen.findByRole('button', { name: 'Открыть' }));
    const details = await screen.findByTestId('kp-request-details-a');
    expect(details).toHaveTextContent('Кирпич');
    expect(details).toHaveTextContent('Срочно');
    const link = within(details).getByRole('link', { name: /ТЗ\.pdf/ });
    expect(link.getAttribute('href')).toContain('/kp-request-files/f1/download?token=');
  });
});
