import React, { useMemo, useState } from 'react';
import { EstimateVersionFull, OptimizationProposal, OptimizationStep } from '../../types';
import { applyProposals } from '../../api/estimateVersions';
import { AbcBreakdown } from './OptimizationToolbar';

interface Props {
  proposals: OptimizationProposal[];
  step: OptimizationStep;
  taskId: string;
  versionId: string;
  abcBreakdown?: AbcBreakdown;
  onProposalsApplied: (newVersion: EstimateVersionFull) => void;
  onDismiss: () => void;
}

const PROPOSAL_TYPE_LABELS: Record<string, string> = {
  add: 'Добавить позицию',
  remove: 'Удалить позицию',
  replace_tech: 'Замена технологии',
  replace_material: 'Замена материала',
  price_search: 'Поиск цены',
};

const CONFIDENCE_COLORS: Record<string, { bg: string; color: string; label: string }> = {
  high: { bg: '#dcfce7', color: '#166534', label: '●●● высокая' },
  medium: { bg: '#fef9c3', color: '#854d0e', label: '●●○ средняя' },
  low: { bg: '#fef2f2', color: '#991b1b', label: '●○○ низкая' },
};

function fmt(n: number | null | undefined): string {
  if (n == null) return '';
  return new Intl.NumberFormat('ru-RU').format(Math.round(n)) + ' ₽';
}

function fmtK(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + ' млн ₽';
  if (n >= 1_000) return (n / 1_000).toFixed(0) + ' тыс. ₽';
  return Math.round(n) + ' ₽';
}

const OptimizationProposalsPanel: React.FC<Props> = ({
  proposals,
  step,
  taskId,
  versionId,
  abcBreakdown,
  onProposalsApplied,
  onDismiss,
}) => {
  const [accepted, setAccepted] = useState<Set<string>>(new Set());
  const [rejected, setRejected] = useState<Set<string>>(new Set());
  const [showLow, setShowLow] = useState(false);
  const [confirmAll, setConfirmAll] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');

  const sorted = useMemo(
    () => [...proposals].sort((a, b) => (b.economy_rub ?? 0) - (a.economy_rub ?? 0)),
    [proposals],
  );

  const highMed = sorted.filter((p) => p.confidence !== 'low');
  const low = sorted.filter((p) => p.confidence === 'low');

  const totalEconomy = useMemo(
    () => proposals.filter((p) => accepted.has(p.id)).reduce((s, p) => s + (p.economy_rub ?? 0), 0),
    [proposals, accepted],
  );

  const allAcceptableIds = highMed.map((p) => p.id);

  const toggleAccepted = (id: string) => {
    setAccepted((prev) => {
      const n = new Set(prev);
      if (n.has(id)) n.delete(id); else n.add(id);
      return n;
    });
    setRejected((prev) => { const n = new Set(prev); n.delete(id); return n; });
  };

  const toggleRejected = (id: string) => {
    setRejected((prev) => {
      const n = new Set(prev);
      if (n.has(id)) n.delete(id); else n.add(id);
      return n;
    });
    setAccepted((prev) => { const n = new Set(prev); n.delete(id); return n; });
  };

  const acceptAll = () => {
    setAccepted(new Set(allAcceptableIds));
    setRejected(new Set());
    setConfirmAll(false);
  };

  const handleFix = async () => {
    if (accepted.size === 0) {
      onDismiss();
      return;
    }
    setSaving(true);
    setSaveError('');
    try {
      const newVersion = await applyProposals(taskId, versionId, [...accepted]);
      onProposalsApplied(newVersion);
    } catch (e: unknown) {
      setSaveError(e instanceof Error ? e.message : 'Ошибка сохранения');
    } finally {
      setSaving(false);
    }
  };

  const renderProposalCard = (p: OptimizationProposal) => {
    const isAcc = accepted.has(p.id);
    const isRej = rejected.has(p.id);
    const conf = CONFIDENCE_COLORS[p.confidence] ?? CONFIDENCE_COLORS.medium;
    const isPriceSearch = p.proposal_type === 'price_search';

    return (
      <div
        key={p.id}
        style={{
          padding: '12px 14px',
          background: isAcc ? '#f0fdf4' : isRej ? '#f8fafc' : '#fff',
          border: `1px solid ${isAcc ? '#86efac' : isRej ? '#e2e8f0' : '#e2e8f0'}`,
          borderRadius: '8px',
          marginBottom: '8px',
          opacity: isRej ? 0.55 : 1,
          transition: 'all 0.15s',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
          <div style={{ flex: 1 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <span
                style={{
                  fontSize: '11px',
                  fontWeight: 600,
                  padding: '2px 6px',
                  borderRadius: '4px',
                  background: '#f1f5f9',
                  color: '#475569',
                }}
              >
                {PROPOSAL_TYPE_LABELS[p.proposal_type] ?? p.proposal_type}
              </span>
              <span
                style={{
                  fontSize: '11px',
                  padding: '2px 6px',
                  borderRadius: '4px',
                  background: conf.bg,
                  color: conf.color,
                }}
              >
                {conf.label}
              </span>
              {p.economy_rub != null && p.economy_rub > 0 && (
                <span style={{ fontSize: '13px', fontWeight: 700, color: '#166534' }}>
                  −{fmt(p.economy_rub)}
                </span>
              )}
            </div>

            <div style={{ fontWeight: 600, fontSize: '13px', color: '#1e293b', marginBottom: 4 }}>
              {p.description}
            </div>
            <div style={{ fontSize: '12px', color: '#64748b', lineHeight: 1.5 }}>
              {p.explanation}
            </div>
            {p.source && (
              <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: 4 }}>
                Источник: {p.source}
              </div>
            )}
          </div>

          {!isPriceSearch && (
            <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
              <button
                onClick={() => toggleAccepted(p.id)}
                style={{
                  padding: '5px 10px',
                  borderRadius: '5px',
                  border: `1px solid ${isAcc ? '#86efac' : '#e2e8f0'}`,
                  background: isAcc ? '#dcfce7' : '#fff',
                  color: isAcc ? '#166534' : '#475569',
                  fontSize: '12px',
                  fontWeight: 500,
                  cursor: 'pointer',
                }}
              >
                {isAcc ? '✓ Принято' : 'Принять'}
              </button>
              <button
                onClick={() => toggleRejected(p.id)}
                style={{
                  padding: '5px 10px',
                  borderRadius: '5px',
                  border: `1px solid ${isRej ? '#fecaca' : '#e2e8f0'}`,
                  background: isRej ? '#fee2e2' : '#fff',
                  color: isRej ? '#dc2626' : '#64748b',
                  fontSize: '12px',
                  cursor: 'pointer',
                }}
              >
                {isRej ? '✕ Отклонено' : 'Отклонить'}
              </button>
            </div>
          )}
        </div>
      </div>
    );
  };

  const stepName: Record<OptimizationStep, string> = {
    completeness: 'Шаг 1 — Полнота',
    redundancy: 'Шаг 2 — Лишние позиции',
    technology: 'Шаг 3 — Технологии',
    materials: 'Шаг 4 — Материалы',
  };

  return (
    <div
      style={{
        background: '#fff',
        border: '1px solid #e2e8f0',
        borderRadius: '10px',
        padding: '18px 20px',
        marginBottom: '16px',
      }}
    >
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '14px' }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: '15px', color: '#0f172a' }}>
            {stepName[step]} — результаты анализа
          </div>
          <div style={{ fontSize: '12px', color: '#64748b', marginTop: 4 }}>
            Найдено предложений: {proposals.length}
            {totalEconomy > 0 && (
              <span style={{ marginLeft: 12, color: '#166534', fontWeight: 600 }}>
                Принятая экономия: −{fmtK(totalEconomy)}
              </span>
            )}
          </div>
        </div>
        <button
          onClick={onDismiss}
          style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer', fontSize: '16px', padding: '0 4px' }}
        >
          ✕
        </button>
      </div>

      {/* ABC Breakdown for steps 3 and 4 */}
      {abcBreakdown && abcBreakdown.total_sum > 0 && (
        <div
          style={{
            background: '#f8fafc',
            borderRadius: '8px',
            padding: '12px 14px',
            marginBottom: '14px',
            fontSize: '12px',
            color: '#475569',
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: 6 }}>ABC-анализ</div>
          <div style={{ display: 'flex', gap: 16 }}>
            <span>
              <strong style={{ color: '#166534' }}>Группа А</strong>: {abcBreakdown.a_count} поз. —{' '}
              {fmtK(abcBreakdown.a_sum)} ({Math.round((abcBreakdown.a_sum / abcBreakdown.total_sum) * 100)}%) →{' '}
              <em>анализируются</em>
            </span>
            <span>
              <strong style={{ color: '#92400e' }}>Группа Б</strong>: {abcBreakdown.b_count} поз.
            </span>
            <span>
              <strong style={{ color: '#64748b' }}>Группа В</strong>: {abcBreakdown.c_count} поз.
            </span>
          </div>
        </div>
      )}

      {/* Bulk actions */}
      {highMed.length > 0 && (
        <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
          {!confirmAll ? (
            <button
              onClick={() => setConfirmAll(true)}
              style={{
                padding: '6px 12px',
                borderRadius: '6px',
                border: '1px solid #bbf7d0',
                background: '#f0fdf4',
                color: '#166534',
                fontSize: '12px',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              Принять все ({highMed.length})
            </button>
          ) : (
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: '12px' }}>
              <span style={{ color: '#64748b' }}>Принять все {highMed.length} предложений?</span>
              <button
                onClick={acceptAll}
                style={{ padding: '4px 10px', borderRadius: '5px', border: '1px solid #86efac', background: '#dcfce7', color: '#166534', fontSize: '12px', cursor: 'pointer' }}
              >
                Да, принять
              </button>
              <button
                onClick={() => setConfirmAll(false)}
                style={{ padding: '4px 10px', borderRadius: '5px', border: '1px solid #e2e8f0', background: '#fff', color: '#64748b', fontSize: '12px', cursor: 'pointer' }}
              >
                Отмена
              </button>
            </div>
          )}
          {accepted.size > 0 && (
            <button
              onClick={() => { setAccepted(new Set()); setRejected(new Set()); }}
              style={{ padding: '6px 12px', borderRadius: '6px', border: '1px solid #e2e8f0', background: '#fff', color: '#64748b', fontSize: '12px', cursor: 'pointer' }}
            >
              Сбросить выбор
            </button>
          )}
        </div>
      )}

      {/* Main proposals */}
      {highMed.length === 0 && low.length === 0 && (
        <div style={{ color: '#94a3b8', fontSize: '13px', padding: '12px 0' }}>
          Предложений не найдено.
        </div>
      )}

      {highMed.map(renderProposalCard)}

      {/* Low confidence section */}
      {low.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <button
            onClick={() => setShowLow((v) => !v)}
            style={{
              background: 'none',
              border: 'none',
              color: '#94a3b8',
              fontSize: '12px',
              cursor: 'pointer',
              padding: '4px 0',
              display: 'flex',
              alignItems: 'center',
              gap: 6,
            }}
          >
            <span style={{ transform: showLow ? 'rotate(90deg)' : '', display: 'inline-block', transition: '0.15s' }}>›</span>
            Ещё {low.length} предложений с низкой уверенностью — требует проверки специалиста
          </button>
          {showLow && (
            <div style={{ marginTop: 8 }}>
              <div
                style={{
                  padding: '6px 10px',
                  background: '#fef2f2',
                  borderRadius: '6px',
                  fontSize: '11px',
                  color: '#991b1b',
                  marginBottom: 8,
                }}
              >
                ⚠ Предложения с низкой уверенностью. Рекомендуем проверить вручную перед принятием.
              </div>
              {low.map(renderProposalCard)}
            </div>
          )}
        </div>
      )}

      {/* Footer: fix version */}
      <div
        style={{
          marginTop: 16,
          paddingTop: 14,
          borderTop: '1px solid #f1f5f9',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 12,
          flexWrap: 'wrap',
        }}
      >
        <div style={{ fontSize: '12px', color: '#64748b' }}>
          {accepted.size > 0 ? (
            <>
              Принято: <strong style={{ color: '#166534' }}>{accepted.size} из {proposals.length}</strong>
              {totalEconomy > 0 && <span style={{ marginLeft: 8 }}>• Экономия: <strong style={{ color: '#166534' }}>−{fmtK(totalEconomy)}</strong></span>}
            </>
          ) : (
            <>Принято: 0 из {proposals.length}</>
          )}
        </div>

        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={onDismiss}
            style={{
              padding: '8px 14px',
              borderRadius: '6px',
              border: '1px solid #e2e8f0',
              background: '#fff',
              color: '#64748b',
              fontSize: '13px',
              cursor: 'pointer',
            }}
          >
            Закрыть
          </button>
          <button
            onClick={handleFix}
            disabled={saving}
            style={{
              padding: '8px 16px',
              borderRadius: '6px',
              border: '1px solid #86efac',
              background: accepted.size > 0 ? '#dcfce7' : '#f0fdf4',
              color: '#166534',
              fontSize: '13px',
              fontWeight: 600,
              cursor: saving ? 'wait' : 'pointer',
              opacity: saving ? 0.7 : 1,
            }}
          >
            {saving
              ? 'Сохранение...'
              : accepted.size > 0
              ? `Зафиксировать с изменениями (${accepted.size})`
              : 'Зафиксировать без изменений'}
          </button>
        </div>
      </div>

      {saveError && (
        <div style={{ marginTop: 8, fontSize: '12px', color: '#dc2626' }}>
          Ошибка: {saveError}
        </div>
      )}
    </div>
  );
};

export default OptimizationProposalsPanel;
