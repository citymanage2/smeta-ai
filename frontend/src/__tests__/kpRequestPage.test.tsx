/**
 * Рабочее место отдела производства работ: «Мои задачи КП», страница запроса,
 * загрузка КП и сравнительная таблица.
 *
 * План: plans/2026-09-14-zapros-kp.md, фаза 5 (критерии 13–15, 18–22, 28).
 *
 * Главное, что здесь закреплено:
 * * минимальная приведённая цена выделена, выбранное КП и черновики помечены;
 * * ставка НДС появляется только при «с НДС» и по умолчанию 22 %;
 * * «цена включает материалы» — только в запросе по работам;
 * * «Завершить» неактивна без отчёта и с неподтверждёнными ценами;
 * * продажам поля ввода недоступны — только просмотр, «Выбрать КП» и
 *   «Вернуть в работу».
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import type { ComponentProps } from 'react';

vi.mock('../components/ProjectsSidebar', () => ({ default: () => null }));
vi.mock('../hooks/useGlobalTaskPoller', () => ({ useGlobalTaskPoller: () => undefined }));
vi.mock('../hooks/useSystemNotifications', () => ({ useSystemNotifications: () => undefined }));

vi.mock('../api/kpRequests', async () => {
  const actual = await vi.importActual<typeof import('../api/kpRequests')>('../api/kpRequests');
  return {
    ...actual,
    getKpRequest: vi.fn(),
    getKpCounters: vi.fn(),
    listCardKpRequests: vi.fn(),
    listMyKpRequests: vi.fn(),
    takeKpRequest: vi.fn(),
    createKpOffer: vi.fn(),
    updateKpOffer: vi.fn(),
    deleteKpOffer: vi.fn(),
    setKpOfferPrice: vi.fn(),
    confirmKpOfferPrice: vi.fn(),
    deleteKpOfferPrice: vi.fn(),
    selectKpOffer: vi.fn(),
    completeKpRequest: vi.fn(),
    reopenKpRequest: vi.fn(),
    cancelKpRequest: vi.fn(),
    retryKpPricelist: vi.fn(),
    reparseKpOffer: vi.fn(),
  };
});

import * as kpApi from '../api/kpRequests';
import KpComparisonTable from '../components/kp/KpComparisonTable';
import OfferUpload from '../components/kp/OfferUpload';
import KpRequestPage from '../pages/KpRequestPage';
import KpInbox from '../pages/KpInbox';
import CardKpRequests from '../components/kp/CardKpRequests';
import Layout from '../components/Layout';
import { useAuthStore } from '../stores/auth';
import type {
  KpCell, KpItemDetail, KpOffer, KpPermissions, KpRequestBrief, KpRequestDetail,
} from '../types/kp';

function loginAs(role: string) {
  useAuthStore.getState().setAuth('token', role, 'user');
}

function offer(overrides: Partial<KpOffer>): KpOffer {
  return {
    id: 'o1', supplier_name: 'Поставщик', offer_date: '2026-09-10',
    vat_mode: 'with_vat', vat_rate: 22, includes_materials: false,
    file_name: 'kp.pdf', mime_type: 'application/pdf', size_bytes: 100, has_file: true,
    parse_status: null, parse_error: null, created_by: 7, created_by_name: 'Снабженец',
    created_at: '2026-09-10T10:00:00Z',
    ...overrides,
  };
}

function cell(overrides: Partial<KpCell>): KpCell {
  return {
    offer_id: 'o1', item_id: 'i1', price: null, unit: null, name_in_offer: null,
    source: null, confidence: null, confirmed: null, includes_materials: false,
    normalized_price: null, unit_status: null, reason: null,
    ...overrides,
  };
}

function detailItem(overrides: Partial<KpItemDetail>): KpItemDetail {
  return {
    id: 'i1', position: 0, item_type: 'material', name: 'Кирпич', unit: 'шт', qty: 500,
    sheet: null, source_no: '12', source_row_ids: ['r1'], selected_offer_id: null,
    cells: [], min_offer_id: null, best: null,
    ...overrides,
  };
}

const PRODUCTION_PERMS: KpPermissions = {
  can_work: true, can_manage: false, can_edit_files: false,
  can_edit_offers: true, can_complete: true, can_select_offer: true,
};

const SALES_PERMS: KpPermissions = {
  can_work: false, can_manage: true, can_edit_files: true,
  can_edit_offers: false, can_complete: false, can_select_offer: true,
};

// Две КП по кирпичу: у «Бетонстрой» дешевле (приведённая 20,00), у «Кирпичный
// двор» — 24,59. Минимум — «Бетонстрой».
function twoOffersRequest(overrides: Partial<KpRequestDetail> = {}): KpRequestDetail {
  const offers = [
    offer({ id: 'o1', supplier_name: 'Кирпичный двор' }),
    offer({ id: 'o2', supplier_name: 'Бетонстрой', vat_mode: 'without_vat', vat_rate: null }),
  ];
  return {
    id: 'req-1', project_id: 'p1', project_name: 'ЖК Северный', card_id: 'c1',
    card_name: 'Корпус 2', source_kind: 'estimate', category: 'material',
    target_role: 'supply_manager', status: 'in_progress',
    author_id: 3, author_name: 'Петров', author_comment: 'Нужны цены до пятницы',
    taken_by_id: 7, taken_by_name: 'Снабженец', taken_at: '2026-09-10T09:00:00Z',
    completed_by_id: null, completed_by_name: null, completed_at: null, applied_at: null,
    items_count: 2, files_count: 1, created_at: '2026-09-09T09:00:00Z', updated_at: null,
    source_task_id: null, source_version_id: null, report: null,
    pricelist_status: null, pricelist_summary: null, pricelist_error: null,
    pricelist_written_at: null, applied_version_id: null,
    items: [
      detailItem({
        id: 'i1', name: 'Кирпич', unit: 'шт',
        cells: [
          cell({ offer_id: 'o1', item_id: 'i1', price: 30, unit: 'шт', source: 'manual',
            confirmed: true, normalized_price: 24.59 }),
          cell({ offer_id: 'o2', item_id: 'i1', price: 20, unit: 'шт', source: 'manual',
            confirmed: true, normalized_price: 20 }),
        ],
        min_offer_id: 'o2',
        best: { offer_id: 'o2', supplier_name: 'Бетонстрой', offer_date: null, price: 20,
          includes_materials: false, selected: false, offers_count: 2 },
      }),
      detailItem({
        id: 'i2', name: 'Цемент', unit: 'кг', source_no: '13',
        cells: [
          cell({ offer_id: 'o1', item_id: 'i2', price: 500, unit: 'мешок', source: 'ai',
            confirmed: false, reason: 'Ед. изм. КП «мешок» не сводится с ед. изм. позиции «кг»' }),
          cell({ offer_id: 'o2', item_id: 'i2', price: 9, unit: 'кг', source: 'ai',
            confirmed: false, normalized_price: 9 }),
        ],
      }),
    ],
    files: [{ id: 'f1', file_name: 'ТЗ.pdf', mime_type: 'application/pdf', size_bytes: 10,
      uploaded_by: 3, uploaded_by_name: 'Петров', created_at: '2026-09-09T09:00:00Z' }],
    offers,
    permissions: PRODUCTION_PERMS,
    ...overrides,
  };
}

function noop() { return Promise.resolve(); }

function renderTable(request: KpRequestDetail, handlers: Partial<ComponentProps<typeof KpComparisonTable>> = {}) {
  return render(
    <KpComparisonTable
      request={request}
      onSetPrice={noop}
      onConfirm={noop}
      onConfirmAll={noop}
      onDeletePrice={noop}
      onSelect={noop}
      onEditOffer={() => undefined}
      onDeleteOffer={noop}
      {...handlers}
    />,
  );
}

function renderPage(requestId = 'req-1') {
  return render(
    <MemoryRouter initialEntries={[`/kp/${requestId}`]}>
      <Routes>
        <Route path="/kp/:requestId" element={<KpRequestPage />} />
        <Route path="/kp" element={<div>Входящие-экран</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(kpApi.getKpCounters).mockResolvedValue({ new: 0, done_not_applied: {} });
  loginAs('supply_manager');
});

describe('Сравнительная таблица', () => {
  it('минимальная приведённая цена выделена, другая — нет', () => {
    renderTable(twoOffersRequest());
    const min = screen.getByTestId('kp-cell-i1-o2');
    const other = screen.getByTestId('kp-cell-i1-o1');
    expect(min).toHaveAttribute('data-min', 'true');
    expect(within(min).getByText('Минимум')).toBeInTheDocument();
    expect(other).not.toHaveAttribute('data-min', 'true');
    expect(within(other).queryByText('Минимум')).not.toBeInTheDocument();
  });

  it('цена в единице КП и приведённая видны в ячейке', () => {
    renderTable(twoOffersRequest());
    const c = screen.getByTestId('kp-cell-i1-o1');
    expect(c).toHaveTextContent('30,00 ₽ / шт');
    expect(c).toHaveTextContent('24,59 ₽ / шт');
  });

  it('черновик ИИ подсвечен, несводимая единица — причина в ячейке', () => {
    renderTable(twoOffersRequest());
    const draft = screen.getByTestId('kp-cell-i2-o1');
    expect(draft).toHaveAttribute('data-draft', 'true');
    expect(draft).toHaveTextContent('не сводится');
    expect(screen.getByTestId('kp-cell-i1-o1')).not.toHaveAttribute('data-draft', 'true');
  });

  it('выбранное КП помечено, «Выбрать» отдаёт позицию и КП', async () => {
    const onSelect = vi.fn().mockResolvedValue(undefined);
    const request = twoOffersRequest();
    request.items[0].selected_offer_id = 'o1';
    renderTable(request, { onSelect });
    expect(within(screen.getByTestId('kp-cell-i1-o1')).getByText('Выбрано')).toBeInTheDocument();
    await userEvent.click(within(screen.getByTestId('kp-cell-i1-o1')).getByRole('button', { name: 'Снять выбор' }));
    expect(onSelect).toHaveBeenCalledWith('i1', null);
    await userEvent.click(within(screen.getByTestId('kp-cell-i1-o2')).getByRole('button', { name: 'Выбрать' }));
    expect(onSelect).toHaveBeenCalledWith('i1', 'o2');
  });

  it('без приведённой цены выбрать КП нельзя', () => {
    renderTable(twoOffersRequest());
    expect(within(screen.getByTestId('kp-cell-i2-o1')).queryByRole('button', { name: 'Выбрать' }))
      .not.toBeInTheDocument();
  });

  it('«Подтвердить все по КП» — у колонки с черновиками', async () => {
    const onConfirmAll = vi.fn().mockResolvedValue(undefined);
    renderTable(twoOffersRequest(), { onConfirmAll });
    const buttons = screen.getAllByRole('button', { name: /Подтвердить все/ });
    expect(buttons).toHaveLength(2);
    await userEvent.click(buttons[1]);
    expect(onConfirmAll).toHaveBeenCalledWith('o2');
  });

  it('«включает материалы» помечено в ячейке', () => {
    const request = twoOffersRequest({ category: 'work' });
    request.items[0].cells[1] = { ...request.items[0].cells[1], includes_materials: true };
    renderTable(request);
    expect(within(screen.getByTestId('kp-cell-i1-o2')).getByText('Включает материалы')).toBeInTheDocument();
    expect(within(screen.getByTestId('kp-cell-i1-o1')).queryByText('Включает материалы')).not.toBeInTheDocument();
  });

  it('ручная цена: цена, единица и «как у КП» уходят в обработчик', async () => {
    const onSetPrice = vi.fn().mockResolvedValue(undefined);
    renderTable(twoOffersRequest(), { onSetPrice });
    const c = screen.getByTestId('kp-cell-i1-o1');
    await userEvent.click(within(c).getByRole('button', { name: 'Изменить цену' }));
    const price = within(c).getByLabelText('Цена');
    await userEvent.clear(price);
    await userEvent.type(price, '1 250,5');
    await userEvent.click(within(c).getByRole('button', { name: 'Сохранить' }));
    expect(onSetPrice).toHaveBeenCalledWith('o1', 'i1', { price: 1250.5, unit: 'шт', includes_materials: null });
  });

  it('продажам в таблице нет ввода цен и подтверждения', () => {
    renderTable(twoOffersRequest({ permissions: SALES_PERMS }));
    expect(screen.queryByRole('button', { name: 'Изменить цену' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Подтвердить/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Удалить КП' })).not.toBeInTheDocument();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Выбрать' }).length).toBeGreaterThan(0);
  });
});

describe('ИИ-разбор КП', () => {
  it('состояние разбора видно в заголовке колонки', () => {
    const request = twoOffersRequest();
    request.offers = [
      offer({ id: 'o1', supplier_name: 'Кирпичный двор', parse_status: 'processing' }),
      offer({ id: 'o2', supplier_name: 'Бетонстрой', parse_status: 'parsed',
        parse_hints: { prices_found: 2, dropped_unknown: 0 } }),
    ];
    renderTable(request);
    expect(screen.getByTestId('kp-offer-o1')).toHaveTextContent('ИИ разбирает файл');
    expect(screen.getByTestId('kp-offer-o2')).toHaveTextContent('Разобрано ИИ: цен — 2');
  });

  it('ошибка разбора — текстом, ручной ввод и «Разобрать заново» доступны', async () => {
    const onReparse = vi.fn().mockResolvedValue(undefined);
    const request = twoOffersRequest();
    request.offers[0] = offer({ id: 'o1', supplier_name: 'Кирпичный двор', parse_status: 'failed',
      parse_error: 'Разбор не удался: ИИ не ответил. Введите цены вручную или запустите разбор заново.' });
    renderTable(request, { onReparse });
    const header = screen.getByTestId('kp-offer-o1');
    expect(within(header).getByRole('alert')).toHaveTextContent('ИИ не ответил');
    expect(within(screen.getByTestId('kp-cell-i1-o1')).getByRole('button', { name: 'Изменить цену' }))
      .toBeInTheDocument();
    await userEvent.click(within(header).getByRole('button', { name: 'Разобрать заново' }));
    expect(onReparse).toHaveBeenCalledWith(expect.objectContaining({ id: 'o1' }));
  });

  it('пока разбор идёт или файла нет — «Разобрать заново» нет', () => {
    const request = twoOffersRequest();
    request.offers = [
      offer({ id: 'o1', parse_status: 'queued' }),
      offer({ id: 'o2', has_file: false, file_name: null, parse_status: null }),
    ];
    renderTable(request, { onReparse: noop });
    expect(screen.getByTestId('kp-offer-o1')).toHaveTextContent('в очереди');
    expect(screen.queryByRole('button', { name: 'Разобрать заново' })).not.toBeInTheDocument();
  });

  it('продажам «Разобрать заново» не показывается', () => {
    const request = twoOffersRequest({ permissions: SALES_PERMS });
    request.offers[0] = offer({ id: 'o1', parse_status: 'failed', parse_error: 'Сбой' });
    renderTable(request, { onReparse: noop });
    expect(screen.queryByRole('button', { name: 'Разобрать заново' })).not.toBeInTheDocument();
  });

  it('догадка ИИ о НДС и материалах — подсказкой, если расходится с условиями', () => {
    const request = twoOffersRequest({ category: 'work' });
    request.offers = [
      offer({ id: 'o1', vat_mode: 'with_vat', vat_rate: 22, parse_status: 'parsed',
        parse_hints: { vat_mode: 'with_vat', vat_rate: 20, includes_materials: true } }),
      offer({ id: 'o2', vat_mode: 'without_vat', vat_rate: null, parse_status: 'parsed',
        parse_hints: { vat_mode: 'without_vat', includes_materials: false } }),
    ];
    renderTable(request);
    const first = screen.getByTestId('kp-offer-o1');
    expect(first).toHaveTextContent('По мнению ИИ, в КП цены с НДС 20 %');
    expect(first).toHaveTextContent('По мнению ИИ, цены включают материалы');
    const second = screen.getByTestId('kp-offer-o2');
    expect(second).not.toHaveTextContent('По мнению ИИ');
  });

  it('страница: «Разобрать заново» ставит разбор и перечитывает запрос', async () => {
    const request = twoOffersRequest();
    request.offers[0] = offer({ id: 'o1', supplier_name: 'Кирпичный двор', parse_status: 'failed',
      parse_error: 'Сбой' });
    vi.mocked(kpApi.getKpRequest).mockResolvedValue(request);
    vi.mocked(kpApi.reparseKpOffer).mockResolvedValue(offer({ id: 'o1', parse_status: 'queued' }));
    renderPage();
    const header = await screen.findByTestId('kp-offer-o1');
    const button = within(header).getByRole('button', { name: 'Разобрать заново' });
    await userEvent.click(button);
    expect(kpApi.reparseKpOffer).toHaveBeenCalledWith('o1');
    await waitFor(() => expect(kpApi.getKpRequest).toHaveBeenCalledTimes(2));
  });
});

describe('Загрузка КП', () => {
  it('поле ставки НДС появляется только при «с НДС», по умолчанию 22', async () => {
    render(<OfferUpload category="material" onSubmit={vi.fn()} />);
    expect(screen.queryByLabelText('Ставка НДС, %')).not.toBeInTheDocument();
    await userEvent.click(screen.getByLabelText('с НДС'));
    expect(screen.getByLabelText('Ставка НДС, %')).toHaveValue('22');
    await userEvent.click(screen.getByLabelText('без НДС'));
    expect(screen.queryByLabelText('Ставка НДС, %')).not.toBeInTheDocument();
  });

  it('без выбора режима НДС загрузить нельзя', async () => {
    const onSubmit = vi.fn();
    render(<OfferUpload category="material" onSubmit={onSubmit} />);
    await userEvent.type(screen.getByLabelText('Поставщик'), 'Кирпичный двор');
    expect(screen.getByRole('button', { name: 'Загрузить КП' })).toBeDisabled();
    await userEvent.click(screen.getByLabelText('без НДС'));
    expect(screen.getByRole('button', { name: 'Загрузить КП' })).toBeEnabled();
  });

  it('«цена включает материалы» — только в запросе по работам', () => {
    const { unmount } = render(<OfferUpload category="material" onSubmit={vi.fn()} />);
    expect(screen.queryByLabelText('Цена включает материалы')).not.toBeInTheDocument();
    unmount();
    render(<OfferUpload category="work" onSubmit={vi.fn()} />);
    expect(screen.getByLabelText('Цена включает материалы')).toBeInTheDocument();
  });

  it('условия и файл уходят в обработчик', async () => {
    const onSubmit = vi.fn().mockResolvedValue(true);
    render(<OfferUpload category="work" onSubmit={onSubmit} />);
    const file = new File(['%PDF'], 'kp.pdf', { type: 'application/pdf' });
    await userEvent.upload(screen.getByLabelText('Файл КП'), file);
    await userEvent.type(screen.getByLabelText('Поставщик'), 'СтройМонтаж');
    await userEvent.click(screen.getByLabelText('с НДС'));
    await userEvent.click(screen.getByLabelText('Цена включает материалы'));
    await userEvent.click(screen.getByRole('button', { name: 'Загрузить КП' }));
    expect(onSubmit).toHaveBeenCalledWith(
      { supplier_name: 'СтройМонтаж', offer_date: '', vat_mode: 'with_vat', vat_rate: '22', includes_materials: true },
      file,
    );
  });

  it('файл неподдерживаемого типа не принимается', async () => {
    render(<OfferUpload category="material" onSubmit={vi.fn()} />);
    const file = new File(['x'], 'kp.docx', { type: 'application/msword' });
    await userEvent.upload(screen.getByLabelText('Файл КП'), file, { applyAccept: false });
    expect(screen.getByText(/тип файла не поддерживается/)).toBeInTheDocument();
  });
});

describe('Страница запроса', () => {
  it('«Завершить» неактивна без отчёта и с черновиками, причины видны', async () => {
    const request = twoOffersRequest();
    vi.mocked(kpApi.getKpRequest).mockResolvedValue(request);
    renderPage();
    const button = await screen.findByRole('button', { name: 'Завершить' });
    expect(button).toBeDisabled();
    expect(screen.getByText(/Напишите отчёт/)).toBeInTheDocument();
    expect(screen.getByText(/Не подтверждены цены: 2/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('Отчёт'), 'Ответили двое, доставка 3 дня');
    expect(button).toBeDisabled();
  });

  it('с отчётом и без черновиков «Завершить» отправляет отчёт', async () => {
    const request = twoOffersRequest();
    request.items = [request.items[0]];
    vi.mocked(kpApi.getKpRequest).mockResolvedValue(request);
    vi.mocked(kpApi.completeKpRequest).mockResolvedValue({ ...request, status: 'done', report: 'Готово' });
    renderPage();
    const button = await screen.findByRole('button', { name: 'Завершить' });
    expect(button).toBeDisabled();
    await userEvent.type(screen.getByLabelText('Отчёт'), 'Готово');
    expect(button).toBeEnabled();
    await userEvent.click(button);
    await waitFor(() => expect(kpApi.completeKpRequest).toHaveBeenCalledWith('req-1', 'Готово'));
  });

  it('новый запрос: «Взять в работу»', async () => {
    const request = twoOffersRequest({
      status: 'new', taken_by_id: null, taken_by_name: null, offers: [],
      items: [detailItem({ id: 'i1' })],
    });
    vi.mocked(kpApi.getKpRequest).mockResolvedValue(request);
    vi.mocked(kpApi.takeKpRequest).mockResolvedValue({ ...request, status: 'in_progress' });
    renderPage();
    await userEvent.click(await screen.findByRole('button', { name: 'Взять в работу' }));
    await waitFor(() => expect(kpApi.takeKpRequest).toHaveBeenCalledWith('req-1'));
    expect(await screen.findByText('В работе')).toBeInTheDocument();
  });

  it('объект, автор, комментарий и вложения автора видны', async () => {
    vi.mocked(kpApi.getKpRequest).mockResolvedValue(twoOffersRequest());
    renderPage();
    expect(await screen.findByText(/ЖК Северный/)).toBeInTheDocument();
    expect(screen.getByText(/Петров/, { selector: '[data-testid="kp-request-author"]' })).toBeInTheDocument();
    expect(screen.getByText('Нужны цены до пятницы')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'ТЗ.pdf' })).toHaveAttribute(
      'href', expect.stringContaining('/kp-request-files/f1/download?token='),
    );
  });

  it('продажам поля ввода недоступны: нет загрузки КП, отчёта и цен', async () => {
    loginAs('project_manager');
    vi.mocked(kpApi.getKpRequest).mockResolvedValue(twoOffersRequest({ permissions: SALES_PERMS }));
    renderPage();
    await screen.findByText(/ЖК Северный/);
    expect(screen.queryByLabelText('Отчёт')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Файл КП')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Добавить КП/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Завершить' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Взять в работу' })).not.toBeInTheDocument();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Выбрать' }).length).toBeGreaterThan(0);
  });

  it('продажам у завершённого запроса — отчёт, «Вернуть в работу» и сводка прайса', async () => {
    loginAs('head_of_sales');
    const request = twoOffersRequest({
      status: 'done', report: 'Ответили двое', permissions: SALES_PERMS,
      pricelist_status: 'done',
      pricelist_summary: { added: 1, updated: 2, skipped: { 'цена включает материалы': 1 } },
    });
    vi.mocked(kpApi.getKpRequest).mockResolvedValue(request);
    vi.mocked(kpApi.reopenKpRequest).mockResolvedValue({ ...request, status: 'in_progress' });
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    renderPage();
    expect(await screen.findByText('Ответили двое')).toBeInTheDocument();
    const summary = screen.getByTestId('kp-pricelist-summary');
    expect(summary).toHaveTextContent('Добавлено: 1');
    expect(summary).toHaveTextContent('Обновлено: 2');
    expect(summary).toHaveTextContent('цена включает материалы — 1');
    await userEvent.click(screen.getByRole('button', { name: 'Вернуть в работу' }));
    await waitFor(() => expect(kpApi.reopenKpRequest).toHaveBeenCalledWith('req-1'));
  });

  it('сбой записи в прайс — ошибка и «Записать в прайс ещё раз»', async () => {
    const request = twoOffersRequest({
      status: 'done', report: 'Готово', pricelist_status: 'failed', pricelist_error: 'Нет связи',
      permissions: { ...PRODUCTION_PERMS, can_edit_offers: false, can_complete: false, can_select_offer: false },
    });
    vi.mocked(kpApi.getKpRequest).mockResolvedValue(request);
    vi.mocked(kpApi.retryKpPricelist).mockResolvedValue({ ...request, pricelist_status: 'done' });
    renderPage();
    expect(await screen.findByText(/Нет связи/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Записать в прайс ещё раз' }));
    await waitFor(() => expect(kpApi.retryKpPricelist).toHaveBeenCalledWith('req-1'));
  });

  it('запрос чужой роли — «не найден»', async () => {
    vi.mocked(kpApi.getKpRequest).mockRejectedValue({
      response: { status: 404, data: { detail: 'Запрос КП не найден' } },
    });
    renderPage();
    expect(await screen.findByText('Запрос КП не найден')).toBeInTheDocument();
  });
});

function brief(overrides: Partial<KpRequestBrief>): KpRequestBrief {
  return {
    id: 'b1', project_id: 'p1', project_name: 'ЖК Северный', card_id: 'c1', card_name: 'Корпус 2',
    source_kind: 'estimate', category: 'material', target_role: 'supply_manager', status: 'new',
    author_id: 3, author_name: 'Петров', author_comment: null, taken_by_id: null, taken_by_name: null,
    taken_at: null, completed_by_id: null, completed_by_name: null, completed_at: null, applied_at: null,
    items_count: 4, files_count: 0, created_at: '2026-09-09T09:00:00Z', updated_at: null,
    ...overrides,
  };
}

describe('Мои задачи КП', () => {
  it('вкладки по статусам, «кто взял» и число позиций', async () => {
    vi.mocked(kpApi.listMyKpRequests).mockImplementation(async (status) => {
      if (status === 'new') return [brief({ id: 'n1', items_count: 4 })];
      if (status === 'in_progress') {
        return [brief({ id: 'w1', status: 'in_progress', taken_by_id: 8, taken_by_name: 'Иванов', project_name: 'БЦ Орион' })];
      }
      if (status === 'done') return [brief({ id: 'd1', status: 'done', project_name: 'Школа' })];
      return [];
    });
    render(
      <MemoryRouter initialEntries={['/kp']}>
        <Routes>
          <Route path="/kp" element={<KpInbox />} />
          <Route path="/kp/:requestId" element={<div>Страница-запроса</div>} />
        </Routes>
      </MemoryRouter>,
    );
    const row = await screen.findByTestId('kp-inbox-row-n1');
    expect(row).toHaveTextContent('ЖК Северный');
    expect(row).toHaveTextContent('Петров');
    expect(row).toHaveTextContent('4');
    expect(screen.getByRole('tab', { name: /Новые\s*1/ })).toHaveAttribute('aria-selected', 'true');
    expect(screen.queryByText('БЦ Орион')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('tab', { name: /В работе/ }));
    expect(screen.getByTestId('kp-inbox-row-w1')).toHaveTextContent('Иванов');

    await userEvent.click(screen.getByRole('tab', { name: /Завершённые/ }));
    await userEvent.click(within(screen.getByTestId('kp-inbox-row-d1')).getByText('Школа'));
    expect(await screen.findByText('Страница-запроса')).toBeInTheDocument();
  });
});

describe('Счётчик новых в шапке', () => {
  it('производство видит число новых запросов у «Мои задачи КП»', async () => {
    vi.mocked(kpApi.getKpCounters).mockResolvedValue({ new: 3, done_not_applied: {} });
    render(<MemoryRouter><Layout><div /></Layout></MemoryRouter>);
    expect(await screen.findByTestId('kp-new-counter')).toHaveTextContent('3');
  });

  it('продажам счётчик не запрашивается', async () => {
    loginAs('project_manager');
    render(<MemoryRouter><Layout><div /></Layout></MemoryRouter>);
    await new Promise((r) => setTimeout(r, 0));
    expect(kpApi.getKpCounters).not.toHaveBeenCalled();
    expect(screen.queryByTestId('kp-new-counter')).not.toBeInTheDocument();
  });
});

describe('Карточка сметы → страница запроса', () => {
  it('у запроса в карточке есть переход на страницу с КП и ценами', async () => {
    loginAs('project_manager');
    vi.mocked(kpApi.listCardKpRequests).mockResolvedValue([brief({ id: 'req-9', status: 'done' })]);
    render(
      <MemoryRouter initialEntries={['/projects/p1/cards/c1']}>
        <Routes>
          <Route path="/projects/:projectId/cards/:cardId" element={<CardKpRequests cardId="c1" />} />
          <Route path="/kp/:requestId" element={<div>Страница-запроса</div>} />
        </Routes>
      </MemoryRouter>,
    );
    const link = await screen.findByRole('link', { name: 'КП и цены' });
    expect(link).toHaveAttribute('href', '/kp/req-9');
    await userEvent.click(link);
    expect(await screen.findByText('Страница-запроса')).toBeInTheDocument();
  });
});
