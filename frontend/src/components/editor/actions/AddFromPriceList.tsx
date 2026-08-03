import React, { useCallback, useEffect, useState } from 'react';
import { Search, X } from 'lucide-react';

import { getCatalog, matchPreview } from '../../../api/catalog';
import { LumaSpin } from '../../ui/LumaSpin';
import { PricePosition } from './priceInsert';

/**
 * «Из прайса» — найти позиции в общем прайсе и вставить их в документ.
 *
 * Поиск идёт по смыслу (те же векторы, что при расчёте сметы), поэтому
 * «кладка кирпича» находит «кладку стен из кирпича». Если поиск по смыслу
 * ничего не дал — например, у прайса нет векторов, — ищем по названию, иначе
 * человек остался бы с пустым окном при непустом прайсе.
 *
 * Выбранные позиции вставляются после текущей строки (решение пользователя 7.1).
 */

interface Props {
  /** Наименование текущей строки — с него начинается поиск. */
  currentRowName?: string;
  onInsert: (positions: PricePosition[]) => void;
}

type Kind = 'work' | 'material';

const overlayStyle: React.CSSProperties = {
  position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,0.45)',
  display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16,
};

const modalStyle: React.CSSProperties = {
  background: '#fff', borderRadius: 12, width: 'min(720px, 100%)',
  maxHeight: '85vh', display: 'flex', flexDirection: 'column', overflow: 'hidden',
};

function chip(active: boolean): React.CSSProperties {
  return {
    padding: '5px 12px', fontSize: 13, borderRadius: 20,
    border: active ? '2px solid #2563eb' : '1px solid #e2e8f0',
    background: active ? '#eff6ff' : '#f8fafc',
    color: active ? '#2563eb' : '#475569',
    fontWeight: active ? 600 : 400, cursor: 'pointer',
  };
}

const AddFromPriceList: React.FC<Props> = ({ currentRowName, onInsert }) => {
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<Kind>('work');
  const [query, setQuery] = useState(currentRowName ?? '');
  const [found, setFound] = useState<PricePosition[]>([]);
  const [loading, setLoading] = useState(false);
  // Порядок выбора запоминаем: в документ позиции встают в том порядке, в
  // каком их отметили, а не в порядке выдачи поиска. Храним номера, а не
  // названия: в прайсе встречаются позиции с одинаковым названием.
  const [picked, setPicked] = useState<number[]>([]);

  const search = useCallback(async (text: string, target: Kind) => {
    const name = text.trim();
    if (!name) {
      setFound([]);
      return;
    }
    setLoading(true);
    try {
      const smart = await matchPreview(name, target);
      let positions: PricePosition[] = smart.candidates.map((candidate) => ({
        kind: target,
        name: candidate.name,
        unit: candidate.unit,
        price: candidate.price,
      }));

      if (positions.length === 0) {
        const plain = await getCatalog({
          tab: target === 'work' ? 'works' : 'materials',
          search: name,
          page_size: 20,
        });
        positions = plain.items.map((item) => ({
          kind: target,
          name: item.name,
          unit: item.unit,
          price: item.price,
        }));
      }

      setFound(positions);
    } catch {
      setFound([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    search(query, kind);
    // Поиск повторяется при смене вида позиций; текст запроса человек
    // подтверждает кнопкой, иначе поиск дёргался бы на каждую букву.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, kind]);

  const toggle = (index: number) => {
    setPicked((prev) => (
      prev.includes(index) ? prev.filter((item) => item !== index) : [...prev, index]
    ));
  };

  const handleInsert = () => {
    const positions = picked
      .map((index) => found[index])
      .filter((item): item is PricePosition => item !== undefined);
    if (positions.length === 0) return;
    onInsert(positions);
    setOpen(false);
    setPicked([]);
  };

  return (
    <>
      <button
        className="de-btn"
        onClick={() => { setQuery(currentRowName ?? ''); setOpen(true); }}
        title="Найти позицию в прайсе и вставить её после текущей строки"
      >
        <Search size={14} />
        Из прайса
      </button>

      {open && (
        <div style={overlayStyle} role="dialog" aria-modal="true">
          <div style={modalStyle}>
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '14px 18px', borderBottom: '1px solid #e2e8f0',
            }}>
              <b style={{ fontSize: 15 }}>Добавить из прайса</b>
              <button
                className="de-icon-btn"
                onClick={() => { setOpen(false); setPicked([]); }}
                title="Закрыть"
              >
                <X size={16} />
              </button>
            </div>

            <div style={{ padding: '14px 18px', display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <button style={chip(kind === 'work')} onClick={() => setKind('work')}>
                Работы
              </button>
              <button style={chip(kind === 'material')} onClick={() => setKind('material')}>
                Материалы
              </button>
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') search(query, kind); }}
                placeholder="Что ищем в прайсе"
                aria-label="Поиск по прайсу"
                style={{
                  flex: 1, minWidth: 220, padding: '6px 10px',
                  border: '1px solid #e2e8f0', borderRadius: 8, fontSize: 13,
                }}
              />
              <button className="de-btn" onClick={() => search(query, kind)}>
                Найти
              </button>
            </div>

            <div style={{ overflowY: 'auto', padding: '0 18px 12px' }}>
              {loading && (
                <div style={{ padding: 16, display: 'flex', gap: 8, alignItems: 'center' }}>
                  <LumaSpin size="sm" color="#3b82f6" /> Ищем в прайсе…
                </div>
              )}
              {!loading && found.length === 0 && (
                <div style={{ padding: 16, color: '#64748b', fontSize: 13 }}>
                  В прайсе ничего похожего не нашлось. Попробуйте другое название.
                </div>
              )}
              {!loading && found.map((item, index) => (
                <label
                  key={`${item.name}#${index}`}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 10, padding: '8px 4px',
                    borderBottom: '1px solid #f1f5f9', fontSize: 13, cursor: 'pointer',
                  }}
                >
                  <input
                    type="checkbox"
                    aria-label={item.name}
                    checked={picked.includes(index)}
                    onChange={() => toggle(index)}
                  />
                  <span style={{ flex: 1 }}>{item.name}</span>
                  <span style={{ color: '#64748b' }}>{item.unit || '—'}</span>
                  <b style={{ minWidth: 90, textAlign: 'right' }}>
                    {item.price != null ? `${item.price.toLocaleString('ru-RU')} ₽` : 'нет цены'}
                  </b>
                </label>
              ))}
            </div>

            <div style={{
              padding: '12px 18px', borderTop: '1px solid #e2e8f0',
              display: 'flex', justifyContent: 'flex-end', gap: 8,
            }}>
              <button className="de-btn" onClick={() => { setOpen(false); setPicked([]); }}>
                Отмена
              </button>
              <button
                className="de-btn de-btn-primary"
                onClick={handleInsert}
                disabled={picked.length === 0}
              >
                Вставить{picked.length > 0 ? ` (${picked.length})` : ''}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};

export default AddFromPriceList;
