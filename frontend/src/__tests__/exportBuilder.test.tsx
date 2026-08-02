/**
 * Конструктор выгрузки-ведомости — общий для всех типов документов.
 *
 * Фаза 9 плана `plans/2026-08-02-edinyy-redaktor-tablic.md`.
 *
 * Раньше он был только у сводной и знал ровно её восемь колонок. Теперь
 * колонки приходят от документа: у перечня свои, у сметы свои. Цены приходят
 * уже с коэффициентом — их показывает редактор, и в файл должно уйти ровно то,
 * что человек видел.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import ExportBuilderModal from '../components/editor/ExportBuilderModal';
import { ExportColumn, ExportRow } from '../components/editor/exportBuilder';

const COLUMNS: ExportColumn[] = [
  { key: 'num', label: '№', numeric: true },
  { key: 'name', label: 'Наименование', numeric: false },
  { key: 'unit', label: 'Ед. изм.', numeric: false },
  { key: 'qty', label: 'Кол-во', numeric: true },
  { key: 'price_work', label: 'Цена работ', numeric: true },
  { key: 'cost_work', label: 'Стоим. работ', numeric: true },
  { key: 'price_material', label: 'Цена матер.', numeric: true },
  { key: 'cost_material', label: 'Стоим. матер.', numeric: true },
];

// Цены уже с коэффициентом ×1,05 — так их показывает редактор.
const ROWS: ExportRow[] = [
  { _id: 'r1', _kind: 'work', num: 1, name: 'Кладка стен', unit: 'м3', qty: 4,
    price_work: 1050, cost_work: 4200, price_material: null, cost_material: null },
  { _id: 'r2', _kind: 'material', num: 2, name: 'Кирпич', unit: 'шт', qty: 400,
    price_work: null, cost_work: null, price_material: 21, cost_material: 8400 },
  { _id: 'r3', _kind: 'work', num: 3, name: 'Штукатурка', unit: 'м2', qty: 10,
    price_work: 525, cost_work: 5250, price_material: null, cost_material: null },
];

const GENERIC_COLUMNS: ExportColumn[] = [
  { key: 'Обоснование', label: 'Обоснование', numeric: false },
  { key: 'Объём работ', label: 'Объём работ', numeric: true },
];

const GENERIC_ROWS: ExportRow[] = [
  { _id: 'g1', _kind: null, 'Обоснование': 'ГЭСН 8-1-1', 'Объём работ': 12 },
];

let onExport: ReturnType<typeof vi.fn>;

function renderModal(props: Partial<React.ComponentProps<typeof ExportBuilderModal>> = {}) {
  return render(
    <ExportBuilderModal
      documentTitle="Смета"
      projectName="ЖК Северный"
      columns={COLUMNS}
      rows={ROWS}
      onExport={onExport}
      onClose={() => {}}
      {...props}
    />,
  );
}

function goToPreview() {
  fireEvent.click(screen.getByRole('button', { name: /Далее/ }));
}

async function download() {
  fireEvent.click(screen.getByRole('button', { name: /Скачать/ }));
  await waitFor(() => expect(onExport).toHaveBeenCalled());
  return onExport.mock.calls[0][0];
}

beforeEach(() => {
  onExport = vi.fn().mockResolvedValue(undefined);
});

describe('пресеты', () => {
  it('«Ведомость работ» оставляет только работы', async () => {
    renderModal();
    fireEvent.click(screen.getByRole('button', { name: 'Ведомость работ' }));
    goToPreview();

    const payload = await download();
    expect(payload.rows.map((r: ExportRow) => r.name)).toEqual(['Кладка стен', 'Штукатурка']);
    // Колонки материалов в ведомости работ не нужны.
    expect(payload.columns.map((c: ExportColumn) => c.key)).not.toContain('price_material');
    expect(payload.header.title).toBe('Ведомость работ');
  });

  it('«Ведомость материалов» оставляет только материалы', async () => {
    renderModal();
    fireEvent.click(screen.getByRole('button', { name: 'Ведомость материалов' }));
    goToPreview();

    const payload = await download();
    expect(payload.rows.map((r: ExportRow) => r.name)).toEqual(['Кирпич']);
    expect(payload.columns.map((c: ExportColumn) => c.key)).not.toContain('price_work');
  });
});

describe('настройка выгрузки', () => {
  it('снятый столбец не попадает в файл', async () => {
    renderModal();
    fireEvent.click(screen.getByRole('button', { name: 'Ед. изм.' }));
    goToPreview();

    const payload = await download();
    expect(payload.columns.map((c: ExportColumn) => c.key)).not.toContain('unit');
    expect(payload.columns.map((c: ExportColumn) => c.key)).toContain('name');
  });

  it('отключённые элементы шапки не уходят на сервер', async () => {
    renderModal();
    fireEvent.click(screen.getByLabelText('Дата формирования'));
    fireEvent.click(screen.getByLabelText('Итоговая строка'));
    goToPreview();

    const payload = await download();
    expect(payload.header.show_date).toBe(false);
    expect(payload.header.show_total).toBe(false);
    // По умолчанию включено всё: объект и проект остались.
    expect(payload.header.project_name).toBe('ЖК Северный');
  });

  it('цены уходят с коэффициентом — ровно как на экране', async () => {
    renderModal();
    goToPreview();

    const payload = await download();
    expect(payload.rows[0].price_work).toBe(1050);
    expect(payload.rows[0].cost_work).toBe(4200);
  });

  it('строки, отмеченные галочками в таблице, подставляются сами', async () => {
    renderModal({ preselectedIds: new Set(['r3']) });

    // Выбор из таблицы — уже готовый фильтр: человек отметил и нажал выгрузку.
    expect(screen.getByText(/Только отмеченные строки \(1\)/)).toBeInTheDocument();
    goToPreview();

    const payload = await download();
    expect(payload.rows.map((r: ExportRow) => r.name)).toEqual(['Штукатурка']);
  });

  it('строку можно удалить в предпросмотре', async () => {
    renderModal();
    goToPreview();
    fireEvent.click(screen.getAllByTitle('Удалить строку')[0]);

    const payload = await download();
    expect(payload.rows).toHaveLength(2);
    expect(payload.rows.map((r: ExportRow) => r.name)).not.toContain('Кладка стен');
  });
});

describe('документ без сметных колонок', () => {
  it('для перечня подставляются его собственные колонки', async () => {
    renderModal({
      documentTitle: 'Перечень', columns: GENERIC_COLUMNS, rows: GENERIC_ROWS,
    });

    expect(screen.getByRole('button', { name: 'Обоснование' })).toBeInTheDocument();
    // Пресетов «работы / материалы» тут нет: типов строк у перечня нет.
    expect(screen.queryByRole('button', { name: 'Ведомость работ' })).not.toBeInTheDocument();

    goToPreview();
    const payload = await download();
    expect(payload.columns.map((c: ExportColumn) => c.key))
      .toEqual(['Обоснование', 'Объём работ']);
    expect(payload.rows[0]['Обоснование']).toBe('ГЭСН 8-1-1');
  });
});

describe('фильтр разделов', () => {
  it('показывается только там, где разделы есть', async () => {
    const { unmount } = renderModal();
    expect(screen.queryByText('Разделы')).not.toBeInTheDocument();
    unmount();

    renderModal({
      sections: [
        { id: 's1', name: 'АР' },
        { id: 's2', name: 'ОВ' },
      ],
      rows: [
        { ...ROWS[0], _section: 's1' },
        { ...ROWS[1], _section: 's2' },
      ],
    });
    expect(screen.getByText('Разделы')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'ОВ' }));
    goToPreview();
    const payload = await download();
    expect(payload.rows.map((r: ExportRow) => r.name)).toEqual(['Кирпич']);
  });
});
