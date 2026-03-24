/**
 * TDD tests for BatchProgressBar component.
 * These must fail before src/components/BatchProgressBar.tsx is created.
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { BatchProgressBar } from '../components/BatchProgressBar';

describe('BatchProgressBar', () => {
  it('renders nothing when message has no batch info', () => {
    const { container } = render(
      <BatchProgressBar message="Загрузка базы расценок..." />
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders a progress bar when message contains batch info', () => {
    render(<BatchProgressBar message="Обработка батча 2 из 5 (10 позиций)..." />);
    const bar = screen.getByRole('progressbar');
    expect(bar).toBeInTheDocument();
  });

  it('shows "N из M" text', () => {
    render(<BatchProgressBar message="Обработка батча 2 из 5 (10 позиций)..." />);
    expect(screen.getByText(/2 из 5/)).toBeInTheDocument();
  });

  it('sets aria-valuenow to current batch number', () => {
    render(<BatchProgressBar message="Обработка батча 3 из 4 (10 позиций)..." />);
    const bar = screen.getByRole('progressbar');
    expect(bar).toHaveAttribute('aria-valuenow', '3');
    expect(bar).toHaveAttribute('aria-valuemax', '4');
  });

  it('fills bar proportionally (3 of 3 = 100%)', () => {
    render(<BatchProgressBar message="Обработка батча 3 из 3 (5 позиций)..." />);
    // The inner fill div should have width: 100%
    const fill = document.querySelector('[data-testid="batch-progress-fill"]');
    expect(fill).toHaveStyle({ width: '100%' });
  });

  it('fills bar proportionally (1 of 4 = 25%)', () => {
    render(<BatchProgressBar message="Обработка батча 1 из 4 (10 позиций)..." />);
    const fill = document.querySelector('[data-testid="batch-progress-fill"]');
    expect(fill).toHaveStyle({ width: '25%' });
  });
});
