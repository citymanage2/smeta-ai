import React, { useState, useEffect, useRef } from 'react';
import { analyzeOptimize, runOptimize, getTaskStatus, OptimizeItem } from '../api/tasks';
import apiClient from '../api/client';

interface OptimizeModalProps {
  taskId: string;
  onClose: () => void;
}

type Step = 1 | 2 | 3 | 4;

const CATEGORIES = [
  { value: 'work', label: 'Работы' },
  { value: 'material', label: 'Материалы' },
  { value: 'extra', label: 'Дополнительные расходы' },
];

const DEFAULT_PROMPT =
  'Ищи аналоги с более низкой ценой. Предпочитай проверенных поставщиков. Указывай источник (URL или название поставщика).';

function formatCurrency(value: number): string {
  return new Intl.NumberFormat('ru-RU', {
    style: 'currency',
    currency: 'RUB',
    maximumFractionDigits: 0,
  }).format(value);
}

const OptimizeModal: React.FC<OptimizeModalProps> = ({ taskId, onClose }) => {
  const [step, setStep] = useState<Step>(1);
  const [categories, setCategories] = useState<string[]>(['work', 'material']);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState('');
  const [items, setItems] = useState<OptimizeItem[]>([]);
  const [totalAnalyzed, setTotalAnalyzed] = useState(0);
  const [coveragePct, setCoveragePct] = useState(0);
  const [prompt, setPrompt] = useState(DEFAULT_PROMPT);
  const [progressMessage, setProgressMessage] = useState('Начинаем оптимизацию...');
  const [runError, setRunError] = useState('');
  const [timedOut, setTimedOut] = useState(false);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startTimeRef = useRef<number>(0);
  const TIMEOUT_MS = 5 * 60 * 1000;

  useEffect(() => {
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, []);

  function toggleCategory(value: string) {
    setCategories((prev) =>
      prev.includes(value) ? prev.filter((c) => c !== value) : [...prev, value]
    );
  }

  function toggleItem(rowIndex: number) {
    setItems((prev) =>
      prev.map((it) =>
        it.row_index === rowIndex ? { ...it, selected: !it.selected } : it
      )
    );
  }

  async function handleAnalyze() {
    if (categories.length === 0) return;
    setAnalyzing(true);
    setAnalyzeError('');
    try {
      const data = await analyzeOptimize(taskId, categories);
      setItems(data.items);
      setTotalAnalyzed(data.total_analyzed);
      setCoveragePct(data.coverage_pct);
      setStep(2);
    } catch (e: any) {
      setAnalyzeError(e?.response?.data?.detail ?? 'Ошибка анализа');
    } finally {
      setAnalyzing(false);
    }
  }

  async function handleRunOptimize() {
    const selectedItems = items.filter((it) => it.selected !== false);
    if (selectedItems.length === 0) return;
    setRunError('');
    try {
      await runOptimize(taskId, selectedItems, prompt, categories);
      setStep(3);
      startTimeRef.current = Date.now();
      pollingRef.current = setInterval(async () => {
        if (Date.now() - startTimeRef.current > TIMEOUT_MS) {
          clearInterval(pollingRef.current!);
          setTimedOut(true);
          return;
        }
        try {
          const status = await getTaskStatus(taskId);
          if (status.progress_message) {
            setProgressMessage(status.progress_message);
          }
          if (status.estimation_status === 'optimized' || status.status === 'completed') {
            clearInterval(pollingRef.current!);
            setStep(4);
          } else if (status.status === 'failed') {
            clearInterval(pollingRef.current!);
            setRunError(status.error_message ?? 'Ошибка оптимизации');
          }
        } catch {
          // keep polling
        }
      }, 2000);
    } catch (e: any) {
      setRunError(e?.response?.data?.detail ?? 'Ошибка запуска оптимизации');
    }
  }

  async function handleDownload() {
    try {
      const response = await apiClient.get(`/tasks/${taskId}/files/optimized/download`, {
        responseType: 'blob',
      });
      const url = URL.createObjectURL(response.data);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'optimized.xlsx';
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      // silently ignore download errors
    }
  }

  const selectedItems = items.filter((it) => it.selected !== false);

  return (
    <div
      style={{
        position: 'fixed', inset: 0, backgroundColor: 'rgba(0,0,0,0.5)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div style={{
        backgroundColor: '#fff', borderRadius: '16px', padding: '32px',
        width: '700px', maxWidth: '95vw', maxHeight: '85vh',
        overflowY: 'auto', position: 'relative',
      }}>
        <button
          onClick={onClose}
          style={{ position: 'absolute', top: '16px', right: '16px', background: 'none', border: 'none', fontSize: '20px', cursor: 'pointer', color: '#94a3b8' }}
        >
          ×
        </button>

        {/* Step indicator */}
        <div style={{ display: 'flex', gap: '8px', marginBottom: '24px', alignItems: 'center' }}>
          {([1, 2, 3, 4] as Step[]).map((s) => (
            <div
              key={s}
              style={{
                width: '28px', height: '28px', borderRadius: '50%',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: '12px', fontWeight: 600,
                backgroundColor: s === step ? '#2563eb' : s < step ? '#bbf7d0' : '#f1f5f9',
                color: s === step ? '#fff' : s < step ? '#15803d' : '#94a3b8',
              }}
            >
              {s}
            </div>
          ))}
          <span style={{ marginLeft: '8px', fontSize: '14px', color: '#64748b' }}>
            {step === 1 && 'Выбор категорий'}
            {step === 2 && 'Предварительный анализ'}
            {step === 3 && 'Поиск аналогов...'}
            {step === 4 && 'Результат'}
          </span>
        </div>

        {/* Step 1 */}
        {step === 1 && (
          <div>
            <h3 style={{ margin: '0 0 16px', fontSize: '18px', fontWeight: 700 }}>
              Оптимизация сметы
            </h3>
            <p style={{ color: '#64748b', fontSize: '14px', marginBottom: '20px' }}>
              Выберите категории позиций для поиска аналогов по более низкой цене.
            </p>
            {CATEGORIES.map((cat) => (
              <label
                key={cat.value}
                style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px', cursor: 'pointer', fontSize: '15px' }}
              >
                <input
                  type="checkbox"
                  checked={categories.includes(cat.value)}
                  onChange={() => toggleCategory(cat.value)}
                  style={{ width: '16px', height: '16px', cursor: 'pointer' }}
                />
                {cat.label}
              </label>
            ))}
            {analyzeError && (
              <p style={{ color: '#dc2626', fontSize: '13px', marginTop: '8px' }}>{analyzeError}</p>
            )}
            <button
              onClick={handleAnalyze}
              disabled={analyzing || categories.length === 0}
              style={{
                marginTop: '20px', padding: '10px 24px', backgroundColor: '#2563eb',
                color: '#fff', border: 'none', borderRadius: '8px', cursor: analyzing ? 'not-allowed' : 'pointer',
                fontWeight: 600, fontSize: '14px', opacity: analyzing ? 0.7 : 1,
              }}
            >
              {analyzing ? 'Анализирую...' : 'Анализировать'}
            </button>
          </div>
        )}

        {/* Step 2 */}
        {step === 2 && (
          <div>
            <h3 style={{ margin: '0 0 4px', fontSize: '18px', fontWeight: 700 }}>
              Предварительный анализ
            </h3>
            <p style={{ color: '#64748b', fontSize: '13px', marginBottom: '16px' }}>
              Из {totalAnalyzed} позиций выбрано {selectedItems.length} наиболее дорогостоящих
              (покрытие {coveragePct}%). Снимите галочку с позиций, которые не нужно оптимизировать.
            </p>

            <div style={{ overflowX: 'auto', marginBottom: '16px' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
                <thead>
                  <tr style={{ backgroundColor: '#f8fafc' }}>
                    <th style={thStyle}></th>
                    <th style={thStyle}>Наименование</th>
                    <th style={thStyle}>Тип</th>
                    <th style={{ ...thStyle, textAlign: 'right' }}>Стоимость</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((it) => (
                    <tr key={it.row_index} style={{ borderBottom: '1px solid #f1f5f9', opacity: it.selected === false ? 0.4 : 1 }}>
                      <td style={{ padding: '8px 4px', textAlign: 'center' }}>
                        <input
                          type="checkbox"
                          checked={it.selected !== false}
                          onChange={() => toggleItem(it.row_index)}
                          style={{ cursor: 'pointer' }}
                        />
                      </td>
                      <td style={{ padding: '8px 4px', color: '#1e293b' }}>{it.name}</td>
                      <td style={{ padding: '8px 4px', color: '#64748b' }}>
                        {it.type === 'work' ? 'Работа' : it.type === 'material' ? 'Материал' : it.type}
                      </td>
                      <td style={{ padding: '8px 4px', textAlign: 'right', fontWeight: 500 }}>
                        {formatCurrency(it.total)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div style={{ marginBottom: '16px' }}>
              <label style={{ fontSize: '13px', fontWeight: 600, color: '#374151', display: 'block', marginBottom: '6px' }}>
                Инструкции для поиска (необязательно)
              </label>
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                rows={3}
                style={{ width: '100%', padding: '8px 12px', border: '1px solid #e2e8f0', borderRadius: '8px', fontSize: '13px', resize: 'vertical', boxSizing: 'border-box' }}
              />
            </div>

            {runError && (
              <p style={{ color: '#dc2626', fontSize: '13px', marginBottom: '8px' }}>{runError}</p>
            )}

            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                onClick={() => setStep(1)}
                style={{ padding: '10px 18px', background: 'transparent', border: '1px solid #e2e8f0', borderRadius: '8px', cursor: 'pointer', fontSize: '14px', color: '#64748b' }}
              >
                ← Назад
              </button>
              <button
                onClick={handleRunOptimize}
                disabled={selectedItems.length === 0}
                style={{
                  padding: '10px 24px', backgroundColor: '#2563eb', color: '#fff',
                  border: 'none', borderRadius: '8px', fontWeight: 600, fontSize: '14px',
                  cursor: selectedItems.length === 0 ? 'not-allowed' : 'pointer',
                  opacity: selectedItems.length === 0 ? 0.7 : 1,
                }}
              >
                Запустить поиск цен ({selectedItems.length} позиций)
              </button>
            </div>
          </div>
        )}

        {/* Step 3 */}
        {step === 3 && (
          <div style={{ textAlign: 'center', padding: '20px 0' }}>
            <h3 style={{ margin: '0 0 16px', fontSize: '18px', fontWeight: 700 }}>
              Поиск аналогов...
            </h3>
            {timedOut ? (
              <p style={{ color: '#dc2626', fontSize: '14px' }}>Превышено время ожидания (5 минут). Проверьте статус задачи позже.</p>
            ) : runError ? (
              <p style={{ color: '#dc2626', fontSize: '14px' }}>{runError}</p>
            ) : (
              <>
                <p style={{ color: '#64748b', fontSize: '14px', marginBottom: '20px' }}>
                  {progressMessage}
                </p>
                <div style={{ width: '100%', height: '6px', backgroundColor: '#e2e8f0', borderRadius: '3px', overflow: 'hidden', marginBottom: '8px' }}>
                  <div
                    style={{
                      height: '100%', backgroundColor: '#2563eb', borderRadius: '3px',
                      width: '40%',
                      animation: 'optimize-progress 1.5s ease-in-out infinite',
                    }}
                  />
                </div>
                <style>{`
                  @keyframes optimize-progress {
                    0% { transform: translateX(-150%); }
                    100% { transform: translateX(350%); }
                  }
                `}</style>
                <p style={{ fontSize: '12px', color: '#94a3b8' }}>Это может занять несколько минут</p>
              </>
            )}
          </div>
        )}

        {/* Step 4 */}
        {step === 4 && (
          <div>
            <h3 style={{ margin: '0 0 16px', fontSize: '18px', fontWeight: 700, color: '#15803d' }}>
              Оптимизация завершена
            </h3>
            <p style={{ color: '#64748b', fontSize: '14px', marginBottom: '24px' }}>
              Оптимизированный файл сметы готов. Скачайте xlsx с выделенными аналогами и листом сравнения.
            </p>
            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                onClick={handleDownload}
                style={{
                  padding: '10px 24px', backgroundColor: '#15803d', color: '#fff',
                  border: 'none', borderRadius: '8px', fontWeight: 600, fontSize: '14px', cursor: 'pointer',
                }}
              >
                Скачать xlsx
              </button>
              <button
                onClick={onClose}
                style={{ padding: '10px 18px', background: 'transparent', border: '1px solid #e2e8f0', borderRadius: '8px', cursor: 'pointer', fontSize: '14px', color: '#64748b' }}
              >
                Закрыть
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

const thStyle: React.CSSProperties = {
  padding: '8px 4px',
  textAlign: 'left',
  fontWeight: 600,
  color: '#64748b',
  borderBottom: '1px solid #e2e8f0',
  fontSize: '12px',
  textTransform: 'uppercase',
  letterSpacing: '0.03em',
};

export default OptimizeModal;
