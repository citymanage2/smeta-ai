import React from 'react';
import { parseBatchProgress } from '../utils/batchProgress';

interface BatchProgressBarProps {
  message: string;
}

export function BatchProgressBar({ message }: BatchProgressBarProps): React.ReactElement | null {
  const progress = parseBatchProgress(message);
  if (!progress) return null;

  const { current, total } = progress;
  const pct = Math.round((current / total) * 100);

  return (
    <div style={{ margin: '8px 0' }}>
      <div
        role="progressbar"
        aria-valuenow={current}
        aria-valuemin={1}
        aria-valuemax={total}
        aria-label={`Батч ${current} из ${total}`}
        style={{
          background: '#e2e8f0',
          borderRadius: 4,
          height: 8,
          overflow: 'hidden',
        }}
      >
        <div
          data-testid="batch-progress-fill"
          style={{
            width: `${pct}%`,
            height: '100%',
            background: '#3b82f6',
            transition: 'width 0.3s ease',
          }}
        />
      </div>
      <div style={{ fontSize: 12, color: '#64748b', marginTop: 4 }}>
        Батч {current} из {total}
      </div>
    </div>
  );
}
