/**
 * Цели оптимизации в бланке сводной.
 *
 * План: `plans/2026-09-01-celi-optimizacii.md`, Фаза 4.
 *
 * Проверяем именно то, ради чего функция делалась: цель вводится там же, где
 * видны суммы раздела, отклонение считается само, а пустая цель остаётся
 * пустой — «цели нет» и «цель ноль» на экране выглядят по-разному.
 */
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';

import SummarySheet from '../components/summary/SummarySheet';
import { calcSummary } from '../stores/summaryEditorStore';
import { SectionTab, SummaryOverrides } from '../types/summary';
import { OVERRIDES as BASE_OVERRIDES, SECTIONS as BASE_SECTIONS } from './summaryRegressFixture';

const SECTIONS: SectionTab[] = [
  { ...BASE_SECTIONS[0], target_works: 15000, target_materials: 20000 },
  { ...BASE_SECTIONS[1] },
];

const OVERRIDES: SummaryOverrides = {
  ...BASE_OVERRIDES,
  target_total_for_customer: 200000,
};

/** Текст ячеек приходит с неразрывными пробелами — сравниваем по-человечески. */
const text = (needle: string) => (content: string) =>
  content.replace(/\u00A0/g, ' ').includes(needle);

function renderSheet(
  sections = SECTIONS,
  overrides = OVERRIDES,
  handlers: Partial<{
    onUpdateOverride: ReturnType<typeof vi.fn>;
    onUpdateSectionTarget: ReturnType<typeof vi.fn>;
  }> = {},
) {
  const onUpdateOverride = handlers.onUpdateOverride ?? vi.fn();
  const onUpdateSectionTarget = handlers.onUpdateSectionTarget ?? vi.fn();
  render(
    <SummarySheet
      calc={calcSummary(sections, overrides)}
      overrides={overrides}
      onUpdateOverride={onUpdateOverride}
      onUpdateSectionTaxPct={vi.fn()}
      onUpdateSectionTarget={onUpdateSectionTarget}
    />,
  );
  return { onUpdateOverride, onUpdateSectionTarget };
}

describe('цели оптимизации в бланке', () => {
  it('показывает отклонение от цели раздела в рублях и процентах', () => {
    renderSheet();
    expect(screen.getAllByText(text('+2 933 ₽')).length).toBeGreaterThan(0);
    expect(screen.getAllByText(text('+19,6%')).length).toBeGreaterThan(0);
  });

  it('превышение цели красное, экономия зелёная', () => {
    renderSheet();
    const over = screen.getAllByText(text('+2 933 ₽'))[0];
    const under = screen.getAllByText(text('-1 079 ₽'))[0];
    expect(over).toHaveStyle({ color: 'rgb(220, 38, 38)' });
    expect(under).toHaveStyle({ color: 'rgb(5, 150, 105)' });
  });

  it('раздел без цели показывает прочерк вместо отклонения', () => {
    renderSheet();
    // У «ОВ» целей нет: обе ячейки цели пусты, отклонений в строке нет.
    const row = screen.getByText('ОВ').closest('tr')!;
    expect(within(row).getAllByTitle('Цель не задана — нажмите, чтобы задать')).toHaveLength(2);
    expect(row.textContent).not.toMatch(/[+-]\d[\d\u00A0 ]* ₽/);
  });

  it('введённая цель уходит в стор', () => {
    const { onUpdateSectionTarget } = renderSheet(
      [{ ...BASE_SECTIONS[0] }, { ...BASE_SECTIONS[1] }], OVERRIDES,
    );
    const row = screen.getByText('АР').closest('tr')!;
    fireEvent.click(within(row).getAllByTitle('Цель не задана — нажмите, чтобы задать')[0]);
    const input = within(row).getByPlaceholderText('нет цели');
    fireEvent.change(input, { target: { value: '15000' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    expect(onUpdateSectionTarget).toHaveBeenCalledWith(0, 'works', 15000);
  });

  it('пустая цель снимает её, а не превращает в ноль', () => {
    const { onUpdateSectionTarget } = renderSheet();
    const row = screen.getByText('АР').closest('tr')!;
    fireEvent.click(within(row).getAllByTitle('Нажмите, чтобы изменить цель')[0]);
    const input = within(row).getByDisplayValue('15000');
    fireEvent.change(input, { target: { value: '' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    expect(onUpdateSectionTarget).toHaveBeenCalledWith(0, 'works', null);
  });

  it('переключатель меняет базу целей на весь бланк', () => {
    const { onUpdateOverride } = renderSheet();
    fireEvent.click(screen.getByRole('button', { name: /с НДС/i }));
    expect(onUpdateOverride).toHaveBeenCalledWith('target_basis', 'with_vat');
  });

  it('цель по объекту сравнивается с итогом для заказчика', () => {
    renderSheet();
    expect(screen.getByText('Отклонение от цели по объекту')).toBeInTheDocument();
    expect(screen.getAllByText(text('+22 648 ₽')).length).toBeGreaterThan(0);
  });

  it('без цели по объекту строки отклонения нет', () => {
    renderSheet(SECTIONS, { ...OVERRIDES, target_total_for_customer: null });
    expect(screen.queryByText('Отклонение от цели по объекту')).toBeNull();
  });
});
