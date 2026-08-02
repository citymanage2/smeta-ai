import React from 'react';
import { AlertTriangle, ExternalLink, StopCircle, X } from 'lucide-react';

import { AnalogVariant, AnalogsState } from '../../api/documents';
import { LumaSpin } from '../ui/LumaSpin';

/**
 * Найденные аналоги: что нашлось на каждую позицию и во сколько это дешевле.
 *
 * Панель ничего не меняет сама — замена происходит только по кнопке
 * «Заменить», и правка идёт в черновик, поэтому откатывается Ctrl+Z.
 */

interface Props {
  state: AnalogsState;
  onReplace: (rowId: string, variant: AnalogVariant) => void;
  onCancel: () => void;
  onClose: () => void;
}

const fmt = (n: number) => Math.round(n).toLocaleString('ru-RU');

const cardStyle: React.CSSProperties = {
  border: '1px solid #e2e8f0', borderRadius: 10, padding: 12, marginBottom: 10,
  background: '#fff',
};

const AnalogsPanel: React.FC<Props> = ({ state, onReplace, onCancel, onClose }) => {
  const running = state.status === 'running' || state.status === 'queued';

  return (
    <div className="de-analogs" style={{
      border: '1px solid #e2e8f0', borderRadius: 12, padding: 14, marginBottom: 12,
      background: '#f8fafc',
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 10,
      }}>
        <b style={{ fontSize: 14 }}>Аналоги подешевле</b>
        <div style={{ display: 'flex', gap: 8 }}>
          {running && (
            <button className="de-btn" onClick={onCancel} title="Остановить поиск">
              <StopCircle size={14} />
              Остановить
            </button>
          )}
          <button className="de-icon-btn" onClick={onClose} title="Скрыть">
            <X size={16} />
          </button>
        </div>
      </div>

      {running && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
          <LumaSpin size="sm" color="#3b82f6" />
          Идёт поиск: обработано {state.processed} из {state.total}
        </div>
      )}

      {state.status === 'failed' && (
        <div style={{
          display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 13,
          color: '#b91c1c',
        }}>
          <AlertTriangle size={16} />
          <span>{state.error || 'Поиск аналогов не удался'}</span>
        </div>
      )}

      {state.status === 'cancelled' && (
        <div style={{ fontSize: 13, color: '#64748b', marginBottom: 8 }}>
          Поиск остановлен. Найденное до остановки — ниже.
        </div>
      )}

      {state.results.map((result) => (
        <div key={result.row_id} style={cardStyle}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
            {result.name}
            <span style={{ color: '#64748b', fontWeight: 400 }}>
              {' '}— сейчас {fmt(result.price)} ₽ за {result.unit || 'ед.'}
            </span>
          </div>

          {result.variants.length === 0 ? (
            <div style={{ fontSize: 13, color: '#64748b' }}>
              Аналогов не нашлось — позиция остаётся как есть.
            </div>
          ) : result.variants.map((variant, index) => (
            <div
              key={`${variant.name}#${index}`}
              style={{
                display: 'flex', gap: 12, alignItems: 'flex-start',
                padding: '8px 0', borderTop: index > 0 ? '1px solid #f1f5f9' : undefined,
              }}
            >
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13 }}>{variant.name}</div>
                <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>
                  {fmt(variant.price)} ₽ за {variant.unit || 'ед.'}
                  {variant.reason ? ` · ${variant.reason}` : ''}
                </div>
                {variant.source && (
                  <a
                    href={variant.source}
                    target="_blank"
                    rel="noreferrer"
                    style={{
                      fontSize: 12, color: '#2563eb', display: 'inline-flex',
                      alignItems: 'center', gap: 4, marginTop: 2,
                    }}
                  >
                    <ExternalLink size={12} />
                    Источник
                  </a>
                )}
              </div>
              <b style={{ color: '#15803d', fontSize: 13, whiteSpace: 'nowrap' }}>
                −{fmt(variant.delta)} ₽
              </b>
              <button
                className="de-btn"
                onClick={() => onReplace(result.row_id, variant)}
                title="Подставить этот вариант вместо исходной позиции"
              >
                Заменить
              </button>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
};

export default AnalogsPanel;
