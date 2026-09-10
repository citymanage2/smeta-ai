import React, { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import Layout from '../components/Layout';
import { LumaSpin } from '../components/ui/LumaSpin';
import {
  acceptPriceSuggestion, getPriceSuggestions, rejectPriceSuggestion,
  undoPriceDecision,
} from '../api/priceSuggestions';
import { PriceSuggestion } from '../types/priceSuggestions';
import { formatMoney } from '../utils/formatNumber';

/**
 * Что система выучила из правок — и чего ждёт подтверждения.
 *
 * План: plans/2026-09-10-sverka-i-obuchenie-na-pravkah.md, Фаза 7.
 *
 * Экран ничего не применяет сам. Пока человек не нажал «Запомнить», цена в
 * общий прайс не уходит — это правило 9 CLAUDE.md, а не настройка.
 */

const cardStyle: React.CSSProperties = {
  background: '#ffffff',
  border: '1px solid #e2e8f0',
  borderRadius: '8px',
  padding: '16px',
};

const labelStyle: React.CSSProperties = {
  fontSize: '11px',
  textTransform: 'uppercase',
  letterSpacing: '0.5px',
  color: '#94a3b8',
  fontWeight: 600,
};

const tabStyle = (active: boolean): React.CSSProperties => ({
  padding: '6px 12px',
  borderRadius: '7px',
  border: '1px solid ' + (active ? '#2563eb' : '#e2e8f0'),
  background: active ? '#eff6ff' : '#ffffff',
  color: active ? '#1d4ed8' : '#334155',
  fontSize: '13px',
  fontWeight: 600,
  cursor: 'pointer',
});

const btnStyle = (kind: 'primary' | 'ghost'): React.CSSProperties => ({
  padding: '7px 14px',
  borderRadius: '8px',
  border: kind === 'primary' ? 'none' : '1px solid #e2e8f0',
  background: kind === 'primary' ? '#2563eb' : '#ffffff',
  color: kind === 'primary' ? '#ffffff' : '#334155',
  fontSize: '13px',
  fontWeight: 600,
  cursor: 'pointer',
});

function typeLabel(rowType: string): string {
  return rowType === 'material' ? 'Материал' : 'Работа';
}

function money(value: number): string {
  return `${formatMoney(value)} ₽`;
}

const PriceLearningPage: React.FC = () => {
  const [items, setItems] = useState<PriceSuggestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [decided, setDecided] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  // Цену можно поправить перед подтверждением: человек — источник истины.
  const [edited, setEdited] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setItems(await getPriceSuggestions({ decided }));
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Не удалось загрузить предложения');
    } finally {
      setLoading(false);
    }
  }, [decided]);

  useEffect(() => { load(); }, [load]);

  const keyOf = (item: PriceSuggestion) =>
    `${item.name_key}|${item.row_type}|${item.unit}`;

  const payloadOf = (item: PriceSuggestion, withPrice = true) => ({
    name: item.display_name,
    row_type: item.row_type,
    unit: item.unit,
    ...(withPrice
      ? { price: Number(edited[keyOf(item)] ?? item.suggested_price) }
      : {}),
  });

  const handleAccept = async (item: PriceSuggestion) => {
    const key = keyOf(item);
    const price = Number(edited[key] ?? item.suggested_price);
    if (!Number.isFinite(price) || price <= 0) {
      toast.error('Цена должна быть больше нуля');
      return;
    }
    setBusy(key);
    try {
      await acceptPriceSuggestion(payloadOf(item));
      toast.success(`«${item.display_name}» — цена ${money(price)} запомнена`);
      await load();
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || 'Не удалось записать цену');
    } finally {
      setBusy(null);
    }
  };

  const handleReject = async (item: PriceSuggestion) => {
    const key = keyOf(item);
    setBusy(key);
    try {
      await rejectPriceSuggestion(payloadOf(item));
      await load();
    } catch {
      toast.error('Не удалось сохранить решение');
    } finally {
      setBusy(null);
    }
  };

  const handleUndo = async (item: PriceSuggestion) => {
    const key = keyOf(item);
    setBusy(key);
    try {
      await undoPriceDecision(payloadOf(item, false));
      await load();
    } catch {
      toast.error('Не удалось вернуть предложение');
    } finally {
      setBusy(null);
    }
  };

  return (
    <Layout>
      <div style={{ maxWidth: '900px' }}>
        <h1 style={{ fontSize: '24px', fontWeight: 700, color: '#0f172a', margin: '0 0 6px' }}>
          Выученные цены
        </h1>
        <p style={{ fontSize: '14px', color: '#64748b', margin: '0 0 20px' }}>
          Позиции, которые вы правите раз за разом. Подтвердите цену — и в
          следующих сметах система посчитает её сама. Пока не нажали, в прайс
          ничего не уходит.
        </p>

        {error && (
          <div style={{
            ...cardStyle, background: '#fef2f2', borderColor: '#fecaca',
            color: '#dc2626', marginBottom: '16px',
          }}>
            {error}
          </div>
        )}

        <div style={{ display: 'flex', gap: '8px', marginBottom: '16px' }}>
          <button style={tabStyle(!decided)} onClick={() => setDecided(false)}>
            Ждут решения
          </button>
          <button style={tabStyle(decided)} onClick={() => setDecided(true)}>
            Уже решённые
          </button>
        </div>

        {loading && (
          <div style={{ ...cardStyle, textAlign: 'center' }}>
            <LumaSpin size="sm" color="#64748b" />
          </div>
        )}

        {!loading && items.length === 0 && (
          <div style={{ ...cardStyle, color: '#64748b', fontSize: '14px' }}>
            {decided
              ? 'Решений пока нет.'
              : 'Пока нечего предлагать. Предложение появляется, когда одну и ту же позицию поправили по цене хотя бы дважды.'}
          </div>
        )}

        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {!loading && items.map((item) => {
            const key = keyOf(item);
            const isBusy = busy === key;
            return (
              <div key={key} style={cardStyle}>
                <div style={{
                  display: 'flex', justifyContent: 'space-between',
                  alignItems: 'baseline', gap: '12px', flexWrap: 'wrap',
                }}>
                  <div style={{ fontSize: '15px', fontWeight: 600, color: '#0f172a' }}>
                    {item.display_name}
                  </div>
                  <div style={{ fontSize: '12px', color: '#94a3b8' }}>
                    {typeLabel(item.row_type)}
                    {item.unit ? ` · ${item.unit}` : ''}
                    {` · правок: ${item.touches} в ${item.tasks} смет.`}
                  </div>
                </div>

                <div style={{ margin: '10px 0', fontSize: '14px', color: '#334155' }}>
                  {item.system_price !== null && (
                    <>
                      система посчитала{' '}
                      <strong>{money(item.system_price)}</strong>
                      {' → '}
                    </>
                  )}
                  вы поставили <strong>{money(item.suggested_price)}</strong>
                  {item.min_price !== item.max_price && (
                    <span style={{ color: '#94a3b8' }}>
                      {' '}(от {money(item.min_price)} до {money(item.max_price)})
                    </span>
                  )}
                </div>

                {item.prices_disagree && (
                  <div style={{
                    background: '#fffbeb', border: '1px solid #fde047',
                    borderRadius: '8px', padding: '8px 10px',
                    fontSize: '12.5px', color: '#92400e', marginBottom: '10px',
                  }}>
                    Цены расходятся больше чем в полтора раза — возможно, это
                    разные работы под одним названием. Проверьте число перед тем,
                    как запоминать.
                  </div>
                )}

                {item.sources.length > 0 && (
                  <div style={{ fontSize: '12px', color: '#94a3b8', marginBottom: '10px' }}>
                    система брала цену из: {item.sources.join(', ')}
                  </div>
                )}

                {!decided && (
                  <>
                    <div style={{
                      background: '#f8fafc', borderRadius: '8px', padding: '8px 10px',
                      fontSize: '12px', color: '#64748b', marginBottom: '12px',
                    }}>
                      Цена запишется в общий прайс как «Из смет» и станет главнее
                      цен подрядчиков по этой позиции. В расчёт она попадёт после
                      обновления прайса в рабочем процессе.
                    </div>

                    <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
                      <div>
                        <div style={labelStyle}>Запомнить цену</div>
                        <input
                          type="number"
                          step="0.01"
                          aria-label={`Цена для «${item.display_name}»`}
                          value={edited[key] ?? String(item.suggested_price)}
                          onChange={(e) => setEdited({ ...edited, [key]: e.target.value })}
                          style={{
                            width: '140px', padding: '7px 10px', fontSize: '15px',
                            border: '1px solid #e2e8f0', borderRadius: '8px',
                          }}
                        />
                      </div>
                      <button
                        style={btnStyle('primary')}
                        disabled={isBusy}
                        onClick={() => handleAccept(item)}
                      >
                        {isBusy ? 'Записываю…' : 'Запомнить'}
                      </button>
                      <button
                        style={btnStyle('ghost')}
                        disabled={isBusy}
                        onClick={() => handleReject(item)}
                      >
                        Не запоминать
                      </button>
                    </div>
                  </>
                )}

                {decided && (
                  <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <span style={{ fontSize: '13px', color: '#64748b' }}>
                      {item.decision === 'accepted' ? 'Запомнено' : 'Отклонено'}
                    </span>
                    <button
                      style={btnStyle('ghost')}
                      disabled={isBusy}
                      onClick={() => handleUndo(item)}
                    >
                      Вернуть в очередь
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </Layout>
  );
};

export default PriceLearningPage;
