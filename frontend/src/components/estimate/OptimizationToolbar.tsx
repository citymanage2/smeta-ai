import React, { useCallback, useEffect, useRef, useState } from 'react';
import { EstimateVersionSummary, OptimizationProposal, OptimizationStep } from '../../types';
import { runOptimization } from '../../api/estimateVersions';
import { getTaskStatus } from '../../api/tasks';
import { LumaSpin } from '../ui/LumaSpin';

interface StepConfig {
  step: OptimizationStep;
  label: string;
  requiredLabel: string | null;
  producedLabel: string;
}

const STEPS: StepConfig[] = [
  { step: 'completeness', label: 'V1 — Полнота', requiredLabel: null, producedLabel: 'completeness_checked' },
  { step: 'redundancy', label: 'V2 — Лишнее', requiredLabel: 'completeness_checked', producedLabel: 'no_redundant' },
  { step: 'technology', label: 'V3 — Технологии', requiredLabel: 'no_redundant', producedLabel: 'tech_optimized' },
  { step: 'materials', label: 'V4 — Материалы', requiredLabel: 'tech_optimized', producedLabel: 'material_optimized' },
  { step: 'fill_prices', label: 'V5 — Цены', requiredLabel: 'material_optimized', producedLabel: 'prices_filled' },
];

export interface AbcBreakdown {
  a_count: number;
  b_count: number;
  c_count: number;
  a_sum: number;
  b_sum: number;
  c_sum: number;
  total_sum: number;
}

interface Props {
  taskId: string;
  versions: EstimateVersionSummary[];
  onStepComplete: (
    newVersionId: string,
    proposals: OptimizationProposal[],
    step: OptimizationStep,
    abcBreakdown?: AbcBreakdown,
  ) => void;
  onViewStep?: (versionId: string, step: OptimizationStep) => void;
}

const OptimizationToolbar: React.FC<Props> = ({ taskId, versions, onStepComplete, onViewStep }) => {
  const [runningStep, setRunningStep] = useState<OptimizationStep | null>(null);
  const [errorMsg, setErrorMsg] = useState('');
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  const versionLabels = new Set(versions.map((v) => v.version_label));

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (pollRef.current) clearTimeout(pollRef.current);
    };
  }, []);

  const schedulePoll = useCallback(
    (step: OptimizationStep, delayMs = 3000) => {
      if (pollRef.current) clearTimeout(pollRef.current);
      pollRef.current = setTimeout(async () => {
        if (!mountedRef.current) return;
        try {
          const status = await getTaskStatus(taskId);
          const pd = status.progress_data as Record<string, unknown> | undefined;

          if (pd?.opt_step === step && pd?.status === 'done') {
            if (!mountedRef.current) return;
            setRunningStep(null);
            onStepComplete(
              pd.new_version_id as string,
              (pd.proposals as OptimizationProposal[]) || [],
              step,
              pd.abc_breakdown as AbcBreakdown | undefined,
            );
          } else if (pd?.opt_step === step && pd?.status === 'error') {
            if (!mountedRef.current) return;
            setRunningStep(null);
            setErrorMsg((pd.error as string) || 'Ошибка анализа');
          } else {
            schedulePoll(step, 3000);
          }
        } catch {
          schedulePoll(step, 6000);
        }
      }, delayMs);
    },
    [taskId, onStepComplete],
  );

  const handleClick = useCallback(
    async (step: OptimizationStep) => {
      const stepConfig = STEPS.find((s) => s.step === step)!;
      const isDone = versions.some((v) => v.version_label === stepConfig.producedLabel);

      if (isDone) {
        const resultVer = versions.find((v) => v.version_label === stepConfig.producedLabel);
        if (resultVer) onViewStep?.(resultVer.id, step);
        return;
      }

      if (runningStep) return;
      setErrorMsg('');
      setRunningStep(step);
      try {
        await runOptimization(taskId, step);
        schedulePoll(step, 2000);
      } catch {
        setRunningStep(null);
        setErrorMsg('Не удалось запустить анализ');
      }
    },
    [runningStep, taskId, schedulePoll, versions, onViewStep],
  );

  const latestVersion = [...versions].reverse().find((v) => !v.is_rolled_back);

  return (
    <div
      style={{
        background: '#fff',
        border: '1px solid #e2e8f0',
        borderRadius: '10px',
        padding: '14px 18px',
        marginBottom: '16px',
      }}
    >
      <div style={{ fontSize: '12px', fontWeight: 600, color: '#64748b', marginBottom: '10px', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
        Модуль оптимизации
      </div>

      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
        {STEPS.map(({ step, label, requiredLabel, producedLabel }, idx) => {
          const isDone = versionLabels.has(producedLabel);
          const isUnlocked = requiredLabel === null || versionLabels.has(requiredLabel);
          const isRunning = runningStep === step;
          const isBlocked = runningStep !== null && !isRunning;
          const disabled = !isUnlocked || (isBlocked && !isDone);

          let bg = '#fff';
          let border = '#e2e8f0';
          let color = '#1e293b';

          if (isDone) { bg = '#f0fdf4'; border = '#86efac'; color = '#166534'; }
          else if (isRunning) { bg = '#eff6ff'; border = '#93c5fd'; color = '#1d4ed8'; }
          else if (!isUnlocked) { bg = '#f8fafc'; border = '#e2e8f0'; color = '#94a3b8'; }

          return (
            <React.Fragment key={step}>
              {idx > 0 && (
                <span style={{ color: '#cbd5e1', fontSize: '16px', userSelect: 'none' }}>›</span>
              )}
              <button
                onClick={() => !disabled && handleClick(step)}
                disabled={disabled}
                title={!isUnlocked ? 'Завершите предыдущий шаг' : isDone ? 'Открыть результаты шага' : ''}
                style={{
                  padding: '8px 13px',
                  borderRadius: '7px',
                  border: `1px solid ${border}`,
                  background: bg,
                  color,
                  fontSize: '13px',
                  fontWeight: 500,
                  cursor: disabled ? 'not-allowed' : 'pointer',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '6px',
                  transition: 'all 0.15s',
                  opacity: !isUnlocked ? 0.6 : 1,
                }}
              >
                {isDone && !isRunning && <span>✓</span>}
                {isRunning && (
                  <LumaSpin size="sm" color="#2563eb" />
                )}
                {!isDone && !isRunning && (
                  <span
                    style={{
                      width: 18,
                      height: 18,
                      borderRadius: '50%',
                      border: `2px solid ${isUnlocked ? '#64748b' : '#cbd5e1'}`,
                      display: 'inline-flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: '10px',
                      color: isUnlocked ? '#64748b' : '#cbd5e1',
                      flexShrink: 0,
                    }}
                  >
                    {idx + 1}
                  </span>
                )}
                {label}
              </button>
            </React.Fragment>
          );
        })}
      </div>

      {latestVersion && (
        <div style={{ marginTop: '10px', fontSize: '12px', color: '#64748b' }}>
          Следующий шаг запустится на основе:{' '}
          <strong style={{ color: '#475569' }}>{latestVersion.version_display_name}</strong>
        </div>
      )}

      {runningStep && (
        <div
          style={{
            marginTop: '10px',
            padding: '8px 12px',
            background: '#eff6ff',
            borderRadius: '6px',
            fontSize: '12px',
            color: '#1d4ed8',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}
        >
          <LumaSpin size="sm" color="#2563eb" />
          Анализ выполняется в фоне — вы можете продолжать работу. Результаты сохранятся.
        </div>
      )}

      {errorMsg && (
        <div
          style={{
            marginTop: '10px',
            padding: '8px 12px',
            background: '#fef2f2',
            border: '1px solid #fecaca',
            borderRadius: '6px',
            fontSize: '12px',
            color: '#dc2626',
          }}
        >
          Ошибка: {errorMsg}
        </div>
      )}

    </div>
  );
};

export default OptimizationToolbar;
