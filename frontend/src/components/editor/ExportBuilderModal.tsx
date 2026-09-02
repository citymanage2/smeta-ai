import React, { useMemo, useState } from 'react';
import { ArrowLeft, ArrowRight, Download, FileSpreadsheet, X } from 'lucide-react';

import { LumaSpin } from '../ui/LumaSpin';
import {
  ExportColumn,
  ExportPayload,
  ExportRow,
  PRESETS,
} from './exportBuilder';

/**
 * Конструктор выгрузки-ведомости — один на все пять типов документов.
 *
 * Два шага: настройка → предпросмотр. В предпросмотре строки правятся и
 * удаляются, поэтому на сервер уходит именно то, что человек видит.
 *
 * Колонки приходят от документа: у перечня свои, у сметы свои. Пресеты «работы»
 * и «материалы» появляются только там, где у строк есть тип, а фильтр «Разделы»
 * — только в сводной (решение пользователя 3.1).
 */

interface SectionOption {
  id: string;
  name: string;
}

interface Props {
  documentTitle: string;
  projectName?: string;
  objectName?: string;
  columns: ExportColumn[];
  rows: ExportRow[];
  /** Разделы сводной. Не передан — фильтра нет. */
  sections?: SectionOption[];
  /** Строки, отмеченные галочками в таблице до открытия окна. */
  preselectedIds?: Set<string>;
  /**
   * Свернуть одинаковые позиции в общий объём. Не передан — галочки нет:
   * сворачивать документ не по чему (например, в файле нет наименования).
   */
  collapseRows?: (rows: ExportRow[]) => ExportRow[];
  /**
   * Убрать строки-вычеты (объём < 0). Не передан — галочки нет: в документе
   * может не быть колонки объёма, и минусы не по чему искать.
   */
  dropDeductions?: (rows: ExportRow[]) => ExportRow[];
  onExport: (payload: ExportPayload) => Promise<void>;
  onClose: () => void;
}

type RowScope = 'all' | 'work' | 'material' | 'selected';

const modalOverlay: React.CSSProperties = {
  position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,0.45)',
  display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16,
};

const labelStyle: React.CSSProperties = {
  fontSize: 12, fontWeight: 600, color: '#64748b',
  textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 8,
};

function chip(active: boolean, accent = '#2563eb'): React.CSSProperties {
  return {
    padding: '5px 12px', fontSize: 13, borderRadius: 20,
    border: active ? `2px solid ${accent}` : '1px solid #e2e8f0',
    background: active ? '#eff6ff' : '#f8fafc',
    color: active ? accent : '#475569',
    fontWeight: active ? 600 : 400, cursor: 'pointer',
  };
}

export const ExportBuilderModal: React.FC<Props> = ({
  documentTitle, projectName, objectName, columns, rows, sections,
  preselectedIds, collapseRows, dropDeductions, onExport, onClose,
}) => {
  const hasKinds = useMemo(() => rows.some((row) => row._kind === 'work' || row._kind === 'material'), [rows]);
  const hasSelection = (preselectedIds?.size ?? 0) > 0;

  const [step, setStep] = useState<'config' | 'preview'>('config');
  const [scope, setScope] = useState<RowScope>(hasSelection ? 'selected' : 'all');
  const [visibleKeys, setVisibleKeys] = useState<string[]>(() => columns.map((c) => c.key));
  const [sectionIds, setSectionIds] = useState<string[]>([]);
  const [title, setTitle] = useState(documentTitle);
  const [showObject, setShowObject] = useState(true);
  const [showProject, setShowProject] = useState(true);
  const [showDate, setShowDate] = useState(true);
  const [showTotal, setShowTotal] = useState(true);
  // Одинаковые позиции — одной строкой с общим объёмом. По умолчанию выключено:
  // обычная ведомость должна остаться построчной, как была.
  const [collapse, setCollapse] = useState(false);
  // Строки-вычеты в файле. По умолчанию выключено: ведомость должна остаться
  // такой же, какой была до появления галочки.
  const [dropMinus, setDropMinus] = useState(false);

  const [previewRows, setPreviewRows] = useState<ExportRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const visibleColumns = useMemo(
    () => columns.filter((column) => visibleKeys.includes(column.key)),
    [columns, visibleKeys],
  );

  const applyPreset = (presetId: 'works' | 'materials') => {
    const preset = PRESETS.find((p) => p.id === presetId)!;
    setScope(preset.kind === 'work' ? 'work' : 'material');
    setVisibleKeys(columns
      .map((c) => c.key)
      .filter((key) => !preset.dropColumns.includes(key)));
    setTitle(preset.label);
  };

  const buildRows = (): ExportRow[] => {
    let result = rows.filter((row) => row._kind !== 'section');
    if (scope === 'work' || scope === 'material') {
      result = result.filter((row) => row._kind === scope);
    }
    if (scope === 'selected' && preselectedIds) {
      result = result.filter((row) => preselectedIds.has(row._id));
    }
    if (sections && sectionIds.length > 0) {
      result = result.filter((row) => row._section && sectionIds.includes(row._section));
    }
    // Вычеты убираются до свёртки — как и на экране: иначе спрятанная строка
    // всё равно попала бы в общий объём группы.
    if (dropMinus && dropDeductions) result = dropDeductions(result);
    // Свёртка идёт последней, по уже отобранным строкам: иначе в общий объём
    // попали бы позиции, которые человек из выгрузки исключил.
    if (collapse && collapseRows) result = collapseRows(result);
    return result.map((row) => ({ ...row }));
  };

  const handleNext = () => {
    setPreviewRows(buildRows());
    setError('');
    setStep('preview');
  };

  const handleDownload = async () => {
    setBusy(true);
    setError('');
    try {
      await onExport({
        columns: visibleColumns,
        rows: previewRows,
        header: {
          title,
          object_name: showObject && objectName ? objectName : '',
          project_name: showProject && projectName ? projectName : '',
          show_date: showDate,
          show_total: showTotal,
        },
        sheet_name: title || documentTitle,
        file_name: `${title || documentTitle}.xlsx`,
      });
    } catch {
      setError('Не удалось сформировать файл');
    } finally {
      setBusy(false);
    }
  };

  const updateCell = (index: number, key: string, raw: string, numeric: boolean) => {
    setPreviewRows((prev) => {
      const next = [...prev];
      const value = numeric
        ? (raw.trim() === '' ? null : Number(raw.replace(',', '.')))
        : raw;
      next[index] = { ...next[index], [key]: numeric && Number.isNaN(value) ? null : value };
      return next;
    });
  };

  return (
    <div style={modalOverlay} onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div style={{
        background: '#fff', borderRadius: 12,
        width: step === 'preview' ? 'min(1200px, 96vw)' : 560,
        maxHeight: '90vh', display: 'flex', flexDirection: 'column',
        boxShadow: '0 20px 60px rgba(0,0,0,0.2)', overflow: 'hidden',
      }}>
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '18px 20px 14px', borderBottom: '1px solid #f1f5f9',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <FileSpreadsheet size={18} color="#2563eb" />
            <span style={{ fontWeight: 700, fontSize: 15, color: '#1e293b' }}>
              {step === 'config' ? 'Сформировать выгрузку' : 'Предпросмотр и правка'}
            </span>
            <span style={{
              fontSize: 11, padding: '2px 8px', borderRadius: 20,
              background: step === 'config' ? '#eff6ff' : '#f0fdf4',
              color: step === 'config' ? '#2563eb' : '#16a34a', fontWeight: 600,
            }}>
              {step === 'config' ? 'Шаг 1 из 2' : 'Шаг 2 из 2'}
            </span>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#94a3b8' }}>
            <X size={18} />
          </button>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: step === 'preview' ? 0 : 20 }}>
          {step === 'config' ? (
            <div>
              {hasKinds && (
                <div style={{ marginBottom: 20 }}>
                  <div style={labelStyle}>Готовые ведомости</div>
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    {PRESETS.map((preset) => (
                      <button key={preset.id} onClick={() => applyPreset(preset.id)} style={chip(false, '#7c3aed')}>
                        {preset.label}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {sections && sections.length > 0 && (
                <div style={{ marginBottom: 20 }}>
                  <div style={labelStyle}>Разделы</div>
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    {sections.map((section) => {
                      const active = sectionIds.includes(section.id);
                      return (
                        <button
                          key={section.id}
                          onClick={() => setSectionIds((prev) => (active
                            ? prev.filter((id) => id !== section.id)
                            : [...prev, section.id]))}
                          style={chip(active)}
                        >
                          {section.name}
                        </button>
                      );
                    })}
                  </div>
                  {sectionIds.length === 0 && (
                    <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 6 }}>
                      Ничего не выбрано — войдут все разделы
                    </div>
                  )}
                </div>
              )}

              <div style={{ marginBottom: 20 }}>
                <div style={labelStyle}>Какие строки</div>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  {([
                    ['all', 'Все строки'],
                    ...(hasKinds ? [['work', 'Только работы'], ['material', 'Только материалы']] : []),
                    ...(hasSelection ? [['selected', `Только отмеченные строки (${preselectedIds!.size})`]] : []),
                  ] as [RowScope, string][]).map(([value, label]) => (
                    <button key={value} onClick={() => setScope(value)} style={chip(scope === value)}>
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              {dropDeductions && (
                <div style={{ marginBottom: 20 }}>
                  <div style={labelStyle}>Строки с минусом</div>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: '#475569' }}>
                    <input
                      type="checkbox"
                      aria-label="Убрать строки с отрицательным объёмом"
                      checked={dropMinus}
                      onChange={(e) => setDropMinus(e.target.checked)}
                    />
                    Убрать строки с отрицательным объёмом
                  </label>
                  <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 6 }}>
                    Такие строки уточняют объём соседней позиции и в стоимость не
                    идут — итог файла от этого не изменится.
                  </div>
                </div>
              )}

              {collapseRows && (
                <div style={{ marginBottom: 20 }}>
                  <div style={labelStyle}>Одинаковые позиции</div>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: '#475569' }}>
                    <input
                      type="checkbox"
                      aria-label="Свернуть одинаковые позиции"
                      checked={collapse}
                      onChange={(e) => setCollapse(e.target.checked)}
                    />
                    Свернуть одинаковые позиции в общий объём
                  </label>
                  <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 6 }}>
                    Одна работа или материал — одна строка с суммарным объёмом и
                    стоимостью. Файл выйдет единым списком, без разбивки по листам.
                  </div>
                </div>
              )}

              <div style={{ marginBottom: 20 }}>
                <div style={labelStyle}>Столбцы</div>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  {columns.map((column) => {
                    const active = visibleKeys.includes(column.key);
                    return (
                      <button
                        key={column.key}
                        onClick={() => setVisibleKeys((prev) => (active
                          ? prev.filter((key) => key !== column.key)
                          : [...prev, column.key]))}
                        style={{
                          ...chip(active, '#7c3aed'),
                          textDecoration: active ? 'none' : 'line-through',
                        }}
                      >
                        {column.label}
                      </button>
                    );
                  })}
                </div>
              </div>

              <div>
                <div style={labelStyle}>Шапка файла</div>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12, color: '#475569', marginBottom: 10 }}>
                  Заголовок
                  <input
                    aria-label="Заголовок"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    style={{ padding: '6px 8px', fontSize: 13, border: '1px solid #d1d5db', borderRadius: 6 }}
                  />
                </label>
                <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 13, color: '#475569' }}>
                  {([
                    ['Объект', showObject, setShowObject],
                    ['Проект', showProject, setShowProject],
                    ['Дата формирования', showDate, setShowDate],
                    ['Итоговая строка', showTotal, setShowTotal],
                  ] as [string, boolean, (v: boolean) => void][]).map(([label, value, set]) => (
                    <label key={label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <input
                        type="checkbox"
                        aria-label={label}
                        checked={value}
                        onChange={(e) => set(e.target.checked)}
                      />
                      {label}
                    </label>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <PreviewTable
              rows={previewRows}
              columns={visibleColumns}
              onUpdateCell={updateCell}
              onDeleteRow={(index) => setPreviewRows((prev) => prev.filter((_, i) => i !== index))}
            />
          )}
        </div>

        <div style={{
          padding: '14px 20px', borderTop: '1px solid #f1f5f9',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8,
        }}>
          {step === 'config' ? (
            <>
              <span style={{ fontSize: 12, color: '#94a3b8' }}>
                {visibleKeys.length} из {columns.length} столбцов
              </span>
              <button
                onClick={handleNext}
                disabled={visibleKeys.length === 0}
                style={{
                  display: 'flex', alignItems: 'center', gap: 6,
                  padding: '8px 18px', fontSize: 13, fontWeight: 600, borderRadius: 8,
                  border: 'none',
                  background: visibleKeys.length > 0 ? '#2563eb' : '#e2e8f0',
                  color: visibleKeys.length > 0 ? '#fff' : '#94a3b8',
                  cursor: visibleKeys.length > 0 ? 'pointer' : 'not-allowed',
                }}
              >
                Далее <ArrowRight size={14} />
              </button>
            </>
          ) : (
            <>
              <button
                onClick={() => setStep('config')}
                style={{
                  display: 'flex', alignItems: 'center', gap: 6,
                  padding: '8px 16px', fontSize: 13, borderRadius: 8,
                  border: '1px solid #e2e8f0', background: '#fff', color: '#374151', cursor: 'pointer',
                }}
              >
                <ArrowLeft size={14} /> Назад
              </button>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                {error && <span style={{ fontSize: 12, color: '#dc2626' }}>{error}</span>}
                <span style={{ fontSize: 12, color: '#94a3b8' }}>{previewRows.length} строк</span>
                <button
                  onClick={handleDownload}
                  disabled={busy || previewRows.length === 0}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 6,
                    padding: '8px 18px', fontSize: 13, fontWeight: 600, borderRadius: 8,
                    border: 'none',
                    background: previewRows.length > 0 ? '#16a34a' : '#e2e8f0',
                    color: previewRows.length > 0 ? '#fff' : '#94a3b8',
                    cursor: previewRows.length > 0 && !busy ? 'pointer' : 'not-allowed',
                  }}
                >
                  {busy ? <LumaSpin size="sm" color="#fff" /> : <Download size={14} />}
                  Скачать Excel
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

// --- Предпросмотр ----------------------------------------------------------

interface PreviewProps {
  rows: ExportRow[];
  columns: ExportColumn[];
  onUpdateCell: (index: number, key: string, raw: string, numeric: boolean) => void;
  onDeleteRow: (index: number) => void;
}

const PreviewTable: React.FC<PreviewProps> = ({ rows, columns, onUpdateCell, onDeleteRow }) => {
  if (rows.length === 0) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: '#94a3b8' }}>
        Нет строк по выбранным условиям
      </div>
    );
  }

  const th: React.CSSProperties = {
    padding: '8px 10px', fontSize: 12, fontWeight: 700, color: '#fff',
    background: '#334155', textAlign: 'left', whiteSpace: 'nowrap',
    position: 'sticky', top: 0, zIndex: 1,
  };

  return (
    <div>
      <div style={{ padding: '10px 16px', borderBottom: '1px solid #f1f5f9', background: '#f8fafc', fontSize: 12, color: '#94a3b8' }}>
        Ячейки редактируемы — в файл уйдёт то, что видно здесь
      </div>
      <div style={{ overflow: 'auto', maxHeight: 'calc(90vh - 220px)' }}>
        <table style={{ borderCollapse: 'collapse', width: '100%' }}>
          <thead>
            <tr>
              {columns.map((column) => <th key={column.key} style={th}>{column.label}</th>)}
              <th style={{ ...th, width: 36 }} />
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={row._id + index} style={{ background: index % 2 === 0 ? '#fff' : '#fafafa' }}>
                {columns.map((column) => {
                  const value = row[column.key];
                  return (
                    <td key={column.key} style={{ padding: 0, borderBottom: '1px solid #f1f5f9' }}>
                      <input
                        style={{
                          width: '100%', border: 'none', outline: 'none', padding: '6px 10px',
                          fontSize: 13, background: 'transparent', boxSizing: 'border-box',
                          textAlign: column.numeric ? 'right' : 'left',
                        }}
                        defaultValue={value === null || value === undefined ? '' : String(value)}
                        onBlur={(e) => onUpdateCell(index, column.key, e.target.value, column.numeric)}
                      />
                    </td>
                  );
                })}
                <td style={{ textAlign: 'center', borderBottom: '1px solid #f1f5f9' }}>
                  <button
                    onClick={() => onDeleteRow(index)}
                    title="Удалить строку"
                    style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#fca5a5', fontSize: 16 }}
                  >
                    ×
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default ExportBuilderModal;
