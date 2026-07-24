import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ProgressCounter } from '../components/kanban/ProgressCounter';

describe('ProgressCounter', () => {
  it('renders nothing without data (fallback to spinner)', () => {
    const { container } = render(<ProgressCounter data={null} />);
    expect(container.firstChild).toBeNull();
  });

  it('renders nothing when there is no numeric progress', () => {
    const { container } = render(<ProgressCounter data={{ opt_step: 'abc' }} />);
    expect(container.firstChild).toBeNull();
  });

  it('shows "N из M частей" with a progressbar when chunks known', () => {
    render(<ProgressCounter data={{ chunks_done: 2, total_chunks: 5 }} />);
    expect(screen.getByRole('progressbar')).toBeInTheDocument();
    expect(screen.getByText(/2 из 5 частей/)).toBeInTheDocument();
  });

  it('fills bar proportionally (2 of 5 = 40%)', () => {
    render(<ProgressCounter data={{ chunks_done: 2, total_chunks: 5 }} />);
    const fill = document.querySelector('[data-testid="progress-counter-fill"]');
    expect(fill).toHaveStyle({ width: '40%' });
  });

  it('appends found positions count when available', () => {
    render(<ProgressCounter data={{ chunks_done: 1, total_chunks: 3, items_count: 40 }} />);
    expect(screen.getByText(/найдено 40 позиций/)).toBeInTheDocument();
  });

  it('normalizes optimization chunks_total to total_chunks', () => {
    render(<ProgressCounter data={{ chunks_done: 0, chunks_total: 4 }} />);
    expect(screen.getByText(/0 из 4 частей/)).toBeInTheDocument();
  });

  it('shows indeterminate positions count when no chunk bar', () => {
    const { container } = render(<ProgressCounter data={{ items_count: 12 }} />);
    expect(screen.getByText(/Найдено 12 позиций…/)).toBeInTheDocument();
    // no bounded progressbar in this mode
    expect(container.querySelector('[role="progressbar"]')).toBeNull();
  });

  it('clamps overflow (done > total) to 100%', () => {
    render(<ProgressCounter data={{ chunks_done: 9, total_chunks: 5 }} />);
    const fill = document.querySelector('[data-testid="progress-counter-fill"]');
    expect(fill).toHaveStyle({ width: '100%' });
    expect(screen.getByText(/5 из 5 частей/)).toBeInTheDocument();
  });
});
