import React, { useState } from 'react';
import { getOptimizationPlan, executeOptimization, OptimizeOptions, OptimizePlanResult } from '../api/projects';

interface Props {
  taskId: string;
  open: boolean;
  onClose: () => void;
  onOptimized?: () => void;
}

type Step = 'checklist' | 'loading_plan' | 'plan' | 'running';

const OptimizationChecklist: React.FC<Props> = ({ taskId, open, onClose, onOptimized }) => {
  const [step, setStep] = useState<Step>('checklist');
  const [options, setOptions] = useState<OptimizeOptions>({
    optimize_materials: true,
    optimize_works: true,
    optimize_other: false,
    custom_prompt: undefined,
  });
  const [plan, setPlan] = useState<OptimizePlanResult | null>(null);
  const [editingPrompt, setEditingPrompt] = useState(false);
  const [customPromptText, setCustomPromptText] = useState('');
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  const handleGetPlan = async () => {
    setStep('loading_plan');
    setError(null);
    try {
      const result = await getOptimizationPlan(taskId, {
        ...options,
        custom_prompt: customPromptText || undefined,
      });
      setPlan(result);
      setStep('plan');
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Ошибка');
      setStep('checklist');
    }
  };

  const handleExecute = async () => {
    setStep('running');
    setError(null);
    try {
      await executeOptimization(taskId, {
        ...options,
        custom_prompt: customPromptText || undefined,
      });
      onOptimized?.();
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Ошибка');
      setStep('plan');
    }
  };

  const handleClose = () => {
    setStep('checklist');
    setPlan(null);
    setError(null);
    onClose();
  };

  return (
    <>
      <div
        onClick={handleClose}
        style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', zIndex: 200 }}
      />
      <div style={{
        position: 'fixed', top: '50%', left: '50%',
        transform: 'translate(-50%, -50%)',
        background: '#fff', borderRadius: 14, boxShadow: '0 8px 40px rgba(0,0,0,0.16)',
        zIndex: 201, width: 500, maxWidth: '95vw', overflow: 'hidden',
      }}>
        {/* Header */}
        <div style={{
          padding: '18px 24px', borderBottom: '1px solid #e5e7eb',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <span style={{ fontWeight: 700, fontSize: 16 }}>
            {step === 'checklist' ? 'Оптимизация сметы' :
             step === 'loading_plan' ? 'Анализ сметы...' :
             step === 'plan' ? 'План оптимизации' : 'Оптимизация запущена'}
          </span>
          <button onClick={handleClose} style={{ border: 'none', background: 'none', cursor: 'pointer', fontSize: 20, color: '#9ca3af' }}>×</button>
        </div>

        {/* Body */}
        <div style={{ padding: '20px 24px' }}>

          {/* STEP: Checklist */}
          {step === 'checklist' && (
            <>
              <p style={{ fontSize: 14, color: '#4b5563', marginBottom: 16 }}>
                Выберите, что оптимизировать:
              </p>
              {([
                ['optimize_materials', 'Материалы (найти аналоги, актуализировать цены)'],
                ['optimize_works',     'Работы (проверить нормативы, найти экономичнее)'],
                ['optimize_other',     'Прочие расходы (накладные, коэффициенты)'],
              ] as [keyof OptimizeOptions, string][]).map(([key, label]) => (
                <label
                  key={key}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 10,
                    padding: '10px 12px', borderRadius: 8, marginBottom: 6,
                    background: options[key] ? '#eff6ff' : '#f9fafb',
                    cursor: 'pointer', fontSize: 14, color: '#1f2937',
                    border: `1px solid ${options[key] ? '#93c5fd' : '#e5e7eb'}`,
                    transition: 'all 0.15s',
                  }}
                >
                  <input
                    type="checkbox"
                    checked={!!options[key]}
                    onChange={e => setOptions(prev => ({ ...prev, [key]: e.target.checked }))}
                    style={{ width: 16, height: 16, accentColor: '#2563eb' }}
                  />
                  {label}
                </label>
              ))}

              {/* Custom prompt */}
              <div style={{ marginTop: 12 }}>
                <button
                  onClick={() => setEditingPrompt(v => !v)}
                  style={{
                    border: 'none', background: 'none', cursor: 'pointer',
                    fontSize: 13, color: '#2563eb', padding: 0,
                  }}
                >
                  {editingPrompt ? '▾' : '▸'} Дополнительные требования
                </button>
                {editingPrompt && (
                  <textarea
                    value={customPromptText}
                    onChange={e => setCustomPromptText(e.target.value)}
                    placeholder="Например: избегать материалов без ГОСТ, учитывать только поставщиков из Екатеринбурга..."
                    rows={3}
                    style={{
                      display: 'block', width: '100%', marginTop: 8,
                      borderRadius: 8, border: '1px solid #d1d5db',
                      padding: '8px 12px', fontSize: 13, resize: 'vertical',
                      boxSizing: 'border-box',
                    }}
                  />
                )}
              </div>

              {error && <p style={{ color: '#dc2626', fontSize: 13, marginTop: 10 }}>{error}</p>}
            </>
          )}

          {/* STEP: Loading plan */}
          {step === 'loading_plan' && (
            <div style={{ textAlign: 'center', padding: '24px 0', color: '#6b7280' }}>
              <div style={{ fontSize: 32, marginBottom: 12 }}>⏳</div>
              <p style={{ fontSize: 14 }}>Анализ позиций сметы, формирование плана...</p>
            </div>
          )}

          {/* STEP: Plan preview */}
          {step === 'plan' && plan && (
            <>
              <div style={{
                background: '#f0fdf4', border: '1px solid #86efac',
                borderRadius: 10, padding: '12px 16px', marginBottom: 16,
              }}>
                <div style={{ fontSize: 14, color: '#166534', fontWeight: 600, marginBottom: 4 }}>
                  Потенциальная экономия: ~{plan.potential_savings_pct}%
                </div>
                <pre style={{
                  fontSize: 13, color: '#374151', whiteSpace: 'pre-wrap',
                  margin: 0, fontFamily: 'inherit',
                }}>
                  {plan.plan}
                </pre>
              </div>

              {plan.top_cost_items.length > 0 && (
                <div style={{ marginBottom: 16 }}>
                  <div style={{ fontWeight: 600, fontSize: 13, color: '#374151', marginBottom: 8 }}>
                    Топ затрат:
                  </div>
                  {plan.top_cost_items.slice(0, 5).map((item, i) => (
                    <div key={item.id} style={{
                      display: 'flex', justifyContent: 'space-between',
                      fontSize: 13, color: '#4b5563', padding: '3px 0',
                    }}>
                      <span>{i + 1}. {item.name}</span>
                      <span style={{ fontWeight: 600, color: '#111827' }}>
                        {item.cost.toLocaleString('ru-RU', { maximumFractionDigits: 0 })} ₽
                        <span style={{ color: '#9ca3af', fontWeight: 400 }}> ({item.pct}%)</span>
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {/* Edit custom prompt */}
              <div style={{ marginBottom: 4 }}>
                <button
                  onClick={() => setEditingPrompt(v => !v)}
                  style={{ border: 'none', background: 'none', cursor: 'pointer', fontSize: 13, color: '#2563eb', padding: 0 }}
                >
                  ✎ Скорректировать требования
                </button>
                {editingPrompt && (
                  <>
                    <textarea
                      value={customPromptText}
                      onChange={e => setCustomPromptText(e.target.value)}
                      rows={3}
                      style={{
                        display: 'block', width: '100%', marginTop: 6,
                        borderRadius: 8, border: '1px solid #d1d5db',
                        padding: '8px 12px', fontSize: 13, resize: 'vertical',
                        boxSizing: 'border-box',
                      }}
                    />
                    <button
                      onClick={handleGetPlan}
                      style={{
                        marginTop: 6, border: '1px solid #d1d5db', background: '#f9fafb',
                        borderRadius: 7, padding: '5px 14px', cursor: 'pointer',
                        fontSize: 13, color: '#374151',
                      }}
                    >
                      Пересчитать план
                    </button>
                  </>
                )}
              </div>

              {error && <p style={{ color: '#dc2626', fontSize: 13 }}>{error}</p>}
            </>
          )}

          {/* STEP: Running */}
          {step === 'running' && (
            <div style={{ textAlign: 'center', padding: '24px 0', color: '#6b7280' }}>
              <div style={{ fontSize: 32, marginBottom: 12 }}>🚀</div>
              <p style={{ fontSize: 14 }}>Оптимизация запущена в фоне. Это займёт несколько минут.</p>
              <p style={{ fontSize: 13, color: '#9ca3af' }}>Окно можно закрыть — статус обновится автоматически.</p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div style={{
          padding: '14px 24px', borderTop: '1px solid #e5e7eb',
          display: 'flex', gap: 10, justifyContent: 'flex-end',
        }}>
          {step === 'checklist' && (
            <>
              <button onClick={handleClose} style={secondaryBtn}>Отмена</button>
              <button
                onClick={handleGetPlan}
                disabled={!options.optimize_materials && !options.optimize_works && !options.optimize_other}
                style={primaryBtn}
              >
                Продолжить →
              </button>
            </>
          )}
          {step === 'plan' && (
            <>
              <button onClick={() => setStep('checklist')} style={secondaryBtn}>← Назад</button>
              <button onClick={handleExecute} style={{ ...primaryBtn, background: '#059669' }}>
                ✓ Запустить оптимизацию
              </button>
            </>
          )}
          {step === 'running' && (
            <button onClick={handleClose} style={primaryBtn}>Закрыть</button>
          )}
        </div>
      </div>
    </>
  );
};

const primaryBtn: React.CSSProperties = {
  border: 'none', background: '#2563eb', color: '#fff',
  borderRadius: 8, padding: '8px 20px', cursor: 'pointer',
  fontSize: 14, fontWeight: 600,
};
const secondaryBtn: React.CSSProperties = {
  border: '1px solid #d1d5db', background: '#fff', color: '#374151',
  borderRadius: 8, padding: '8px 20px', cursor: 'pointer', fontSize: 14,
};

export default OptimizationChecklist;
