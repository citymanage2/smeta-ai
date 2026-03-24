import React, { useState, useEffect } from 'react';
import { findAnalogues, applyAnalogue, revertAnalogue, listEstimateItems, EstimateItem, Analogue } from '../api/projects';

interface Props {
  taskId: string;
  item: EstimateItem;
  onChanged?: () => void;
}

const AnaloguePanel: React.FC<Props> = ({ taskId, item, onChanged }) => {
  const [searching, setSearching] = useState(false);
  const [analogues, setAnalogues] = useState<Analogue[] | null>(null);
  const [applying, setApplying] = useState<string | null>(null);
  const [reverting, setReverting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Check cache on mount
  useEffect(() => {
    const cached = (item.extra as Record<string, unknown>)?.analogues_cache;
    if (Array.isArray(cached)) setAnalogues(cached as Analogue[]);
  }, [item.extra]);

  const handleSearch = async () => {
    setSearching(true);
    setError(null);
    setAnalogues(null);
    try {
      await findAnalogues(taskId, item.id);
      // Poll for result (background task writes to extra.analogues_cache)
      await pollForAnalogues();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Ошибка поиска');
      setSearching(false);
    }
  };

  const pollForAnalogues = async () => {
    let attempts = 0;
    const maxAttempts = 30; // 60 seconds max
    while (attempts < maxAttempts) {
      await new Promise(r => setTimeout(r, 2000));
      attempts++;
      try {
        const items = await listEstimateItems(taskId);
        const updated = items.find(i => i.id === item.id);
        const cache = (updated?.extra as Record<string, unknown>)?.analogues_cache;
        if (Array.isArray(cache) && !(updated?.extra as Record<string, unknown>)?.analogues_searching) {
          setAnalogues(cache as Analogue[]);
          setSearching(false);
          return;
        }
      } catch {
        // continue polling
      }
    }
    setError('Превышено время ожидания. Попробуйте ещё раз.');
    setSearching(false);
  };

  const handleApply = async (analogue: Analogue) => {
    setApplying(analogue.name);
    setError(null);
    try {
      await applyAnalogue(taskId, item.id, {
        analogue_name: analogue.name,
        analogue_price: analogue.price,
        analogue_note: analogue.note,
        supplier: analogue.supplier,
      });
      onChanged?.();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Ошибка применения');
    } finally {
      setApplying(null);
    }
  };

  const handleRevert = async () => {
    setReverting(true);
    setError(null);
    try {
      await revertAnalogue(taskId, item.id);
      onChanged?.();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Ошибка отмены');
    } finally {
      setReverting(false);
    }
  };

  const currentPrice = (item.work_price || 0) + (item.mat_price || 0);

  return (
    <div style={{
      border: '1px solid #e0e7ff',
      borderRadius: 10,
      padding: '12px 16px',
      background: '#f5f8ff',
      fontSize: 13,
    }}>
      {/* Item info */}
      <div style={{ marginBottom: 10 }}>
        <span style={{ fontWeight: 600, color: '#1e3a8a' }}>
          Аналоги: {item.name}
        </span>
        {item.is_analogue && (
          <span style={{
            marginLeft: 8, background: '#dbeafe', color: '#1d4ed8',
            borderRadius: 6, padding: '1px 8px', fontSize: 11, fontWeight: 600,
          }}>
            Аналог
          </span>
        )}
        <div style={{ color: '#6b7280', marginTop: 3 }}>
          Текущая цена:{' '}
          <strong style={{ color: '#111827' }}>
            {currentPrice.toLocaleString('ru-RU', { maximumFractionDigits: 2 })} ₽/{item.unit || 'ед.'}
          </strong>
          {item.quantity && (
            <span style={{ color: '#9ca3af', marginLeft: 6 }}>
              × {item.quantity} = {(currentPrice * item.quantity).toLocaleString('ru-RU', { maximumFractionDigits: 0 })} ₽
            </span>
          )}
        </div>
      </div>

      {/* Revert button if analogue */}
      {item.is_analogue && (
        <div style={{ marginBottom: 10 }}>
          <button
            disabled={reverting}
            onClick={handleRevert}
            style={{
              border: '1px solid #fca5a5', background: '#fff',
              borderRadius: 7, padding: '5px 14px', cursor: reverting ? 'not-allowed' : 'pointer',
              fontSize: 12, color: '#dc2626',
            }}
          >
            {reverting ? 'Откат...' : '↩ Откатить к оригиналу'}
          </button>
        </div>
      )}

      {/* Search button */}
      {!item.is_analogue && !searching && analogues === null && (
        <button
          onClick={handleSearch}
          style={{
            border: 'none', background: '#2563eb', color: '#fff',
            borderRadius: 7, padding: '6px 14px', cursor: 'pointer',
            fontSize: 12, fontWeight: 600,
          }}
        >
          🔍 Найти аналоги
        </button>
      )}

      {/* Searching skeleton */}
      {searching && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {[1, 2, 3].map(i => (
            <div key={i} style={{
              height: 36, borderRadius: 8,
              background: 'linear-gradient(90deg, #e5e7eb 25%, #f3f4f6 50%, #e5e7eb 75%)',
              backgroundSize: '200% 100%',
              animation: 'shimmer 1.4s infinite',
            }} />
          ))}
          <p style={{ color: '#6b7280', fontSize: 12, margin: '4px 0 0' }}>
            Поиск аналогов в интернете... (5–15 сек)
          </p>
        </div>
      )}

      {/* Analogues table */}
      {!searching && analogues !== null && (
        <>
          {analogues.length === 0 ? (
            <div style={{ color: '#9ca3af', fontSize: 13 }}>
              Аналоги не найдены. Попробуйте позже.
              <button
                onClick={handleSearch}
                style={{
                  marginLeft: 8, border: 'none', background: 'none',
                  cursor: 'pointer', color: '#2563eb', fontSize: 12, textDecoration: 'underline',
                }}
              >
                Повторить поиск
              </button>
            </div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr>
                  {['Наименование', 'Цена', 'Экон.', ''].map(h => (
                    <th key={h} style={{
                      textAlign: h === '' ? 'center' : 'left',
                      padding: '4px 6px',
                      color: '#6b7280', fontWeight: 600, borderBottom: '1px solid #e5e7eb',
                    }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {analogues.map((a, idx) => (
                  <tr key={idx} style={{ borderBottom: '1px solid #f3f4f6' }}>
                    <td style={{ padding: '6px', color: '#111827' }}>
                      <div>{a.name}</div>
                      <div style={{ color: '#9ca3af', fontSize: 11 }}>{a.supplier}</div>
                    </td>
                    <td style={{ padding: '6px', whiteSpace: 'nowrap', color: '#111827' }}>
                      {a.price.toLocaleString('ru-RU', { maximumFractionDigits: 2 })} ₽
                    </td>
                    <td style={{ padding: '6px', color: '#059669', fontWeight: 600, whiteSpace: 'nowrap' }}>
                      -{a.saving_pct.toFixed(1)}%
                    </td>
                    <td style={{ padding: '6px', textAlign: 'center' }}>
                      <button
                        disabled={applying === a.name}
                        onClick={() => handleApply(a)}
                        style={{
                          border: 'none', background: '#059669', color: '#fff',
                          borderRadius: 6, padding: '4px 10px',
                          cursor: applying === a.name ? 'not-allowed' : 'pointer',
                          fontSize: 11, fontWeight: 600, whiteSpace: 'nowrap',
                        }}
                      >
                        {applying === a.name ? '...' : 'Применить'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <button
            onClick={handleSearch}
            style={{
              marginTop: 8, border: 'none', background: 'none',
              cursor: 'pointer', color: '#6b7280', fontSize: 11, textDecoration: 'underline',
            }}
          >
            Обновить поиск
          </button>
        </>
      )}

      {error && (
        <p style={{ color: '#dc2626', fontSize: 12, marginTop: 6 }}>{error}</p>
      )}

      <style>{`
        @keyframes shimmer {
          0% { background-position: -200% 0; }
          100% { background-position: 200% 0; }
        }
      `}</style>
    </div>
  );
};

export default AnaloguePanel;
