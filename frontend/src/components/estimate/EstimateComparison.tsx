import React, { useMemo, useState, useEffect } from 'react';
import { EstimateVersionSummary, EstimateVersionFull, EstimateRow } from '../../types';
import { getVersion } from '../../api/estimateVersions';

interface EstimateComparisonProps {
  taskId: string;
  versions: EstimateVersionSummary[];
}

interface AlignedRow {
  lineage_id: string;
  name: string;
  unit: string;
  type: string;
  byVersion: Record<string, EstimateRow | null>; // versionId → row or null
}

interface VersionTotals {
  works: number;
  materials: number;
  base: number;
  overhead: number;
  transport: number;
  contingency: number;
  total: number;
  vat: number;
  grand_total: number;
}

const VAT = 0.22;

function fmt(n: number): string {
  return n.toLocaleString('ru-RU', { maximumFractionDigits: 0 });
}

function rowCost(row: EstimateRow): number {
  return (row.qty ?? 0) * ((row.price_work ?? 0) + (row.price_material ?? 0));
}

function calcTotals(rows: EstimateRow[], meta: EstimateVersionSummary): VersionTotals {
  let works = 0;
  let materials = 0;
  for (const r of rows) {
    if (r.type === 'work' || r.type === 'material') {
      works += (r.qty ?? 0) * (r.price_work ?? 0);
      materials += (r.qty ?? 0) * (r.price_material ?? 0);
    }
  }
  const base = works + materials;
  const overhead = base * (meta.overhead_pct / 100);
  const transport = base * (meta.transport_pct / 100);
  const contingency = base * (meta.contingency_pct / 100);
  const total = base + overhead + transport + contingency;
  const vat = total * VAT;
  return { works, materials, base, overhead, transport, contingency, total, vat, grand_total: total + vat };
}

function alignRows(versionData: Array<{ id: string; rows: EstimateRow[] }>): AlignedRow[] {
  const originalRows = versionData[0]?.rows ?? [];
  const lineageOrder: string[] = [];
  const seen = new Set<string>();

  // Order from original version first
  for (const r of originalRows) {
    if (!seen.has(r.lineage_id)) {
      lineageOrder.push(r.lineage_id);
      seen.add(r.lineage_id);
    }
  }

  // Then rows that appear in later versions only (added)
  for (const vd of versionData.slice(1)) {
    for (const r of vd.rows) {
      if (!seen.has(r.lineage_id)) {
        lineageOrder.push(r.lineage_id);
        seen.add(r.lineage_id);
      }
    }
  }

  // Build lookup: lineage_id → row per version
  const lookup: Record<string, Record<string, EstimateRow>> = {};
  for (const vd of versionData) {
    for (const r of vd.rows) {
      if (!lookup[r.lineage_id]) lookup[r.lineage_id] = {};
      lookup[r.lineage_id][vd.id] = r;
    }
  }

  return lineageOrder.map((lid) => {
    const anyRow = Object.values(lookup[lid] ?? {})[0]!;
    const byVersion: Record<string, EstimateRow | null> = {};
    for (const vd of versionData) {
      byVersion[vd.id] = lookup[lid]?.[vd.id] ?? null;
    }
    return {
      lineage_id: lid,
      name: anyRow.name,
      unit: anyRow.unit,
      type: anyRow.type,
      byVersion,
    };
  });
}

const EstimateComparison: React.FC<EstimateComparisonProps> = ({ taskId, versions }) => {
  const visibleVersions = versions.filter((v) => !v.is_rolled_back);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set(visibleVersions.map((v) => v.id)));
  const [fullVersions, setFullVersions] = useState<Record<string, EstimateVersionFull>>({});
  const [loading, setLoading] = useState(false);

  // Load full versions for selected ids
  useEffect(() => {
    const missing = [...selectedIds].filter((id) => !fullVersions[id]);
    if (missing.length === 0) return;
    setLoading(true);
    Promise.all(missing.map((id) => getVersion(taskId, id).then((v) => ({ id, v }))))
      .then((results) => {
        setFullVersions((prev) => {
          const next = { ...prev };
          for (const { id, v } of results) next[id] = v;
          return next;
        });
      })
      .finally(() => setLoading(false));
  }, [selectedIds, taskId]); // eslint-disable-line react-hooks/exhaustive-deps

  const selectedVersions = visibleVersions.filter((v) => selectedIds.has(v.id));

  const versionData = selectedVersions
    .filter((v) => fullVersions[v.id])
    .map((v) => ({ id: v.id, rows: fullVersions[v.id].rows }));

  const aligned = useMemo(() => alignRows(versionData), [versionData]); // eslint-disable-line react-hooks/exhaustive-deps

  const totalsMap = useMemo(() => {
    const result: Record<string, VersionTotals> = {};
    for (const v of selectedVersions) {
      if (fullVersions[v.id]) {
        result[v.id] = calcTotals(fullVersions[v.id].rows, v);
      }
    }
    return result;
  }, [selectedVersions, fullVersions]); // eslint-disable-line react-hooks/exhaustive-deps

  // Original version for delta calc
  const originalVersion = selectedVersions.find((v) => v.version_label === 'original') ?? selectedVersions[0];
  const clientVersion = selectedVersions.find((v) => v.version_label === 'client');
  const origTotals = originalVersion ? totalsMap[originalVersion.id] : null;
  const clientTotals = clientVersion ? totalsMap[clientVersion.id] : null;

  const toggleVersion = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        if (next.size > 1) next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const deltaColor = (delta: number) =>
    delta < 0 ? '#166534' : delta > 0 ? '#dc2626' : '#475569';

  const deltaStr = (delta: number) =>
    delta === 0 ? '—' : `${delta < 0 ? '↓' : '↑'} ${delta < 0 ? '' : '+'}${fmt(delta)} руб`;

  return (
    <div>
      {/* Version selector */}
      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '20px' }}>
        <span style={{ fontSize: '13px', color: '#64748b', paddingTop: '4px' }}>Показать версии:</span>
        {visibleVersions.map((v) => (
          <label
            key={v.id}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              padding: '4px 10px',
              fontSize: '13px',
              borderRadius: '6px',
              border: selectedIds.has(v.id) ? '1px solid #2563eb' : '1px solid #e2e8f0',
              background: selectedIds.has(v.id) ? '#eff6ff' : '#fff',
              cursor: 'pointer',
              color: selectedIds.has(v.id) ? '#2563eb' : '#374151',
            }}
          >
            <input
              type="checkbox"
              checked={selectedIds.has(v.id)}
              onChange={() => toggleVersion(v.id)}
              style={{ margin: 0 }}
            />
            {v.version_display_name}
          </label>
        ))}
      </div>

      {loading && (
        <div style={{ color: '#64748b', fontSize: '14px', padding: '16px 0' }}>
          Загрузка данных версий...
        </div>
      )}

      {/* Totals summary table */}
      {selectedVersions.length > 0 && (
        <div style={{ overflowX: 'auto', marginBottom: '28px' }}>
          <table style={tableStyle}>
            <thead>
              <tr>
                <th style={{ ...thStyle, textAlign: 'left', minWidth: '200px' }}>Показатель</th>
                {selectedVersions.map((v) => (
                  <th key={v.id} style={{ ...thStyle, minWidth: '150px' }}>
                    {v.version_display_name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {([
                ['works', 'Работы, руб'],
                ['materials', 'Материалы, руб'],
                ['base', 'Итого (базис), руб'],
                ['total', 'Итого с расходами, руб'],
                ['vat', `НДС ${Math.round(VAT * 100)}%, руб`],
                ['grand_total', 'ИТОГО с НДС, руб'],
              ] as [keyof VersionTotals, string][]).map(([key, label]) => (
                <tr key={key} style={{ background: key === 'grand_total' ? '#f8fafc' : undefined }}>
                  <td style={{ ...tdStyle, fontWeight: key === 'grand_total' ? 700 : 400 }}>
                    {label}
                  </td>
                  {selectedVersions.map((v) => {
                    const t = totalsMap[v.id];
                    const val = t ? t[key] : null;
                    const origVal = origTotals ? origTotals[key] : null;
                    const delta = val != null && origVal != null && v.id !== originalVersion?.id
                      ? val - origVal
                      : null;
                    return (
                      <td
                        key={v.id}
                        style={{
                          ...tdStyle,
                          textAlign: 'right',
                          fontWeight: key === 'grand_total' ? 700 : 400,
                          color: key === 'grand_total' && delta != null ? deltaColor(delta) : undefined,
                        }}
                      >
                        {val != null ? fmt(val) : '—'}
                        {delta != null && key === 'grand_total' && (
                          <div style={{ fontSize: '11px', color: deltaColor(delta), fontWeight: 400 }}>
                            {deltaStr(delta)}
                          </div>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}

              {/* % to client */}
              {clientTotals && (
                <tr>
                  <td style={{ ...tdStyle, color: '#64748b', fontSize: '12px' }}>
                    % к смете заказчика
                  </td>
                  {selectedVersions.map((v) => {
                    const t = totalsMap[v.id];
                    if (!t || !clientTotals || clientTotals.grand_total === 0) {
                      return <td key={v.id} style={{ ...tdStyle, textAlign: 'right' }}>—</td>;
                    }
                    const pct = ((t.grand_total - clientTotals.grand_total) / clientTotals.grand_total) * 100;
                    return (
                      <td
                        key={v.id}
                        style={{
                          ...tdStyle,
                          textAlign: 'right',
                          color: deltaColor(pct),
                          fontSize: '12px',
                          fontWeight: 600,
                        }}
                      >
                        {pct === 0 ? '—' : `${pct > 0 ? '+' : ''}${pct.toFixed(1)}%`}
                      </td>
                    );
                  })}
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Row-by-row comparison */}
      {aligned.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table style={tableStyle}>
            <thead>
              <tr>
                <th style={{ ...thStyle, width: 40 }}>#</th>
                <th style={{ ...thStyle, textAlign: 'left', minWidth: 280 }}>Наименование</th>
                <th style={{ ...thStyle, width: 70 }}>Ед.</th>
                <th style={{ ...thStyle, width: 70 }}>Кол-во</th>
                {selectedVersions.map((v) => (
                  <th key={v.id} style={{ ...thStyle, minWidth: 130 }}>
                    {v.version_display_name}
                    <div style={{ fontSize: '11px', fontWeight: 400, color: '#94a3b8' }}>
                      стоимость, руб
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {aligned.map((ar, idx) => {
                // Determine if row is added or removed in any version
                const presentCount = Object.values(ar.byVersion).filter(Boolean).length;
                const totalVersions = selectedVersions.length;
                const isAdded = ar.byVersion[selectedVersions[0]?.id] == null && presentCount > 0;
                const isRemoved = ar.byVersion[selectedVersions[0]?.id] != null && presentCount < totalVersions;

                const rowBg = isAdded ? '#f0fdf4' : isRemoved ? '#fef2f2' : undefined;

                // Reference cost from original version
                const origRow = originalVersion ? ar.byVersion[originalVersion.id] : null;
                const origCost = origRow ? rowCost(origRow) : null;

                return (
                  <tr key={ar.lineage_id} style={{ background: rowBg }}>
                    <td style={{ ...tdStyle, textAlign: 'center', color: '#94a3b8', fontSize: '12px' }}>
                      {isAdded && (
                        <span
                          title={`Эта позиция добавлена в ${selectedVersions.find((v) => ar.byVersion[v.id] != null)?.version_display_name ?? ''}`}
                          style={{ color: '#16a34a', fontWeight: 700 }}
                        >
                          [+]
                        </span>
                      )}
                      {isRemoved && (
                        <span
                          title={`Эта позиция исключена в ${selectedVersions.find((v) => ar.byVersion[v.id] == null)?.version_display_name ?? ''}`}
                          style={{ color: '#dc2626', fontWeight: 700 }}
                        >
                          [−]
                        </span>
                      )}
                      {!isAdded && !isRemoved && idx + 1}
                    </td>
                    <td style={{ ...tdStyle, maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {ar.name}
                    </td>
                    <td style={{ ...tdStyle, textAlign: 'center', color: '#64748b', fontSize: '12px' }}>
                      {ar.unit}
                    </td>
                    <td style={{ ...tdStyle, textAlign: 'right', color: '#64748b', fontSize: '12px' }}>
                      {origRow?.qty ?? (Object.values(ar.byVersion).find(Boolean) as EstimateRow | undefined)?.qty ?? '—'}
                    </td>
                    {selectedVersions.map((v) => {
                      const row = ar.byVersion[v.id];
                      if (!row) {
                        return (
                          <td key={v.id} style={{ ...tdStyle, textAlign: 'right', color: '#94a3b8' }}>
                            —
                          </td>
                        );
                      }
                      const cost = rowCost(row);
                      const delta = origCost != null && v.id !== originalVersion?.id ? cost - origCost : null;
                      const isChanged = delta != null && Math.abs(delta) > 0.01;

                      return (
                        <td
                          key={v.id}
                          style={{
                            ...tdStyle,
                            textAlign: 'right',
                            background: isChanged
                              ? delta! < 0
                                ? 'rgba(187,247,208,0.35)'
                                : 'rgba(254,202,202,0.35)'
                              : undefined,
                            color: isChanged ? deltaColor(delta!) : undefined,
                            fontWeight: isChanged ? 600 : 400,
                          }}
                        >
                          {fmt(cost)}
                          {isChanged && (
                            <div style={{ fontSize: '11px', color: deltaColor(delta!), fontWeight: 400 }}>
                              {delta! < 0 ? '↓' : '↑'} {fmt(Math.abs(delta!))}
                            </div>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p style={{ fontSize: '11px', color: '#94a3b8', marginTop: '8px' }}>
            * Экономия рассчитана относительно исходной версии. Включает все позиции, в т.ч. добавленные и исключённые.
          </p>
        </div>
      )}

      {aligned.length === 0 && !loading && (
        <div style={{ padding: '20px', color: '#94a3b8', fontSize: '14px', textAlign: 'center' }}>
          Выберите хотя бы одну версию для сравнения
        </div>
      )}
    </div>
  );
};

const tableStyle: React.CSSProperties = {
  width: '100%',
  borderCollapse: 'collapse',
  fontSize: '13px',
};

const thStyle: React.CSSProperties = {
  padding: '8px 12px',
  background: '#f8fafc',
  border: '1px solid #e2e8f0',
  fontWeight: 600,
  color: '#374151',
  textAlign: 'right',
  whiteSpace: 'nowrap',
};

const tdStyle: React.CSSProperties = {
  padding: '7px 12px',
  border: '1px solid #e2e8f0',
  color: '#1e293b',
};

export default EstimateComparison;
