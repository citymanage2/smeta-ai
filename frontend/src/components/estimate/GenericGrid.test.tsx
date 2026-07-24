import { describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/react';
import GenericGrid from './GenericGrid';
import { GenericRow } from '../../types';

function makeRows(n: number): GenericRow[] {
  return Array.from({ length: n }, (_, i) => ({
    row_id: `r${i}`,
    cells: { Наименование: `Позиция ${i}`, Цена: i },
  }));
}

const noop = () => {};
const asyncNoop = async () => {};

describe('GenericGrid virtualization', () => {
  it('большой перечень (>120) рендерит только окно строк, а не все', () => {
    const { container } = render(
      <GenericGrid rows={makeRows(300)} onRowsChange={noop} onSave={asyncNoop} />,
    );
    const bodyRows = container.querySelectorAll('tbody tr');
    // Спейсеры + видимое окно — существенно меньше 300 строк данных.
    expect(bodyRows.length).toBeLessThan(80);
    expect(bodyRows.length).toBeGreaterThan(0);
  });

  it('короткий перечень (<120) рендерит все строки целиком', () => {
    const rows = makeRows(50);
    const { container } = render(
      <GenericGrid rows={rows} onRowsChange={noop} onSave={asyncNoop} />,
    );
    const bodyRows = container.querySelectorAll('tbody tr');
    // Нет спейсеров, все 50 строк в DOM (без изменений поведения для малых списков).
    expect(bodyRows.length).toBe(50);
  });

  it('не падает без ResizeObserver в окружении', () => {
    const original = globalThis.ResizeObserver;
    // @ts-expect-error — симулируем отсутствие API
    delete globalThis.ResizeObserver;
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(() =>
      render(<GenericGrid rows={makeRows(200)} onRowsChange={noop} onSave={asyncNoop} />),
    ).not.toThrow();
    spy.mockRestore();
    globalThis.ResizeObserver = original;
  });
});
