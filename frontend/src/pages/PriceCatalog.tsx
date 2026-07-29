import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { formatApiDetail } from '../utils/formatError';
import Layout from '../components/Layout';
import { useAuthStore } from '../stores/auth';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '../components/ui/Select';
import {
  getCatalog,
  createWork,
  createMaterial,
  updateWork,
  updateMaterial,
  deleteWork,
  deleteMaterial,
  exportCatalog,
  downloadTemplate,
  CatalogItem,
  CatalogParams,
} from '../api/catalog';
import {
  CacheItem,
  getCacheWorks,
  getCacheMaterials,
  updateCacheWork,
  updateCacheMaterial,
  deleteCacheWork,
  deleteCacheMaterial,
} from '../api/priceCache';
import apiClient from '../api/client';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Tab = 'all' | 'works' | 'materials' | 'cache_works' | 'cache_materials';
type SortKey = 'name_asc' | 'name_desc' | 'price_asc' | 'price_desc' | 'date_asc' | 'date_desc';

interface FormState {
  kind: 'work' | 'material';
  name: string;
  unit: string;
  price: string;
  contractors: { name: string; price: string }[];
}

interface CacheFormState {
  name: string;
  unit: string;
  price: string;
  sources: string;
}

const EMPTY_FORM: FormState = {
  kind: 'work',
  name: '',
  unit: '',
  price: '',
  contractors: [{ name: '', price: '' }],
};

const PAGE_SIZE_OPTIONS = [20, 50, 100];

const SORT_OPTIONS: { value: SortKey; label: string }[] = [
  { value: 'name_asc', label: 'Название А→Я' },
  { value: 'name_desc', label: 'Название Я→А' },
  { value: 'price_asc', label: 'Цена ↑' },
  { value: 'price_desc', label: 'Цена ↓' },
  { value: 'date_desc', label: 'Дата (новые)' },
  { value: 'date_asc', label: 'Дата (старые)' },
];

// ---------------------------------------------------------------------------
// Column definitions per tab
// ---------------------------------------------------------------------------

interface ColDef {
  id: string;
  label: string;
  defaultWidth?: number;
  noResize?: boolean;
}

const COL_DEFS: Record<Tab, ColDef[]> = {
  all: [
    { id: 'num', label: '№', defaultWidth: 50, noResize: true },
    { id: 'type', label: 'Тип', defaultWidth: 90 },
    { id: 'name', label: 'Наименование', defaultWidth: 320 },
    { id: 'unit', label: 'Ед. изм', defaultWidth: 80 },
    { id: 'price', label: 'Цена, руб', defaultWidth: 120 },
    { id: 'updated', label: 'Обновлено', defaultWidth: 110 },
    { id: 'actions', label: '', defaultWidth: 90, noResize: true },
  ],
  works: [
    { id: 'num', label: '№', defaultWidth: 50, noResize: true },
    { id: 'name', label: 'Наименование', defaultWidth: 280 },
    { id: 'unit', label: 'Ед. изм', defaultWidth: 80 },
    { id: 'contractors', label: 'Подрядчики', defaultWidth: 220 },
    { id: 'minprice', label: 'Мин. цена, руб', defaultWidth: 130 },
    { id: 'updated', label: 'Обновлено', defaultWidth: 110 },
    { id: 'actions', label: '', defaultWidth: 90, noResize: true },
  ],
  materials: [
    { id: 'num', label: '№', defaultWidth: 50, noResize: true },
    { id: 'name', label: 'Наименование', defaultWidth: 380 },
    { id: 'unit', label: 'Ед. изм', defaultWidth: 80 },
    { id: 'price', label: 'Цена, руб', defaultWidth: 120 },
    { id: 'updated', label: 'Обновлено', defaultWidth: 110 },
    { id: 'actions', label: '', defaultWidth: 90, noResize: true },
  ],
  cache_works: [
    { id: 'num', label: '№', defaultWidth: 50, noResize: true },
    { id: 'name', label: 'Наименование', defaultWidth: 250 },
    { id: 'unit', label: 'Ед. изм', defaultWidth: 80 },
    { id: 'price', label: 'Цена, руб', defaultWidth: 110 },
    { id: 'sources', label: 'Источник', defaultWidth: 200 },
    { id: 'updated', label: 'Обновлено', defaultWidth: 110 },
    { id: 'expires', label: 'Истекает', defaultWidth: 90 },
    { id: 'actions', label: '', defaultWidth: 80, noResize: true },
  ],
  cache_materials: [
    { id: 'num', label: '№', defaultWidth: 50, noResize: true },
    { id: 'name', label: 'Наименование', defaultWidth: 250 },
    { id: 'unit', label: 'Ед. изм', defaultWidth: 80 },
    { id: 'price', label: 'Цена, руб', defaultWidth: 110 },
    { id: 'sources', label: 'Источник', defaultWidth: 200 },
    { id: 'updated', label: 'Обновлено', defaultWidth: 110 },
    { id: 'expires', label: 'Истекает', defaultWidth: 90 },
    { id: 'actions', label: '', defaultWidth: 80, noResize: true },
  ],
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatPrice(price: number | null | undefined): string {
  if (price == null) return '—';
  return price.toLocaleString('ru-RU', { maximumFractionDigits: 2 });
}

function formatDate(dt: string): string {
  try {
    return new Date(dt).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' });
  } catch {
    return '';
  }
}

function buildPricesFromContractors(contractors: { name: string; price: string }[]): Record<string, number> {
  const result: Record<string, number> = {};
  for (const c of contractors) {
    const name = c.name.trim();
    const price = parseFloat(c.price);
    if (name && !isNaN(price) && price > 0) {
      result[name] = price;
    }
  }
  return result;
}

function contractorsFromPrices(prices: Record<string, number> | null): { name: string; price: string }[] {
  if (!prices || Object.keys(prices).length === 0) return [{ name: '', price: '' }];
  return Object.entries(prices).map(([name, price]) => ({ name, price: String(price) }));
}

function renderExpires(days: number) {
  if (days < 0) return <span style={{ color: '#ef4444', fontWeight: 500 }}>Устарело</span>;
  if (days <= 7) return <span style={{ color: '#f97316', fontWeight: 500 }}>{days} дн.</span>;
  return <span style={{ color: '#64748b' }}>{days} дн.</span>;
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const s = {
  page: {
    maxWidth: 1300,
    margin: '0 auto',
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Inter', sans-serif",
  } as React.CSSProperties,

  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 20,
    flexWrap: 'wrap' as const,
    gap: 12,
  } as React.CSSProperties,

  title: {
    fontSize: 22,
    fontWeight: 700,
    color: '#1e293b',
    margin: 0,
  } as React.CSSProperties,

  headerActions: {
    display: 'flex',
    gap: 8,
    flexWrap: 'wrap' as const,
  } as React.CSSProperties,

  btn: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    padding: '7px 14px',
    borderRadius: 6,
    fontSize: 13,
    fontWeight: 500,
    cursor: 'pointer',
    border: '1px solid #e2e8f0',
    background: '#fff',
    color: '#374151',
    transition: 'background 0.15s',
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,

  btnPrimary: {
    background: '#2563eb',
    color: '#fff',
    border: '1px solid #2563eb',
  } as React.CSSProperties,

  btnDanger: {
    color: '#ef4444',
    borderColor: '#fca5a5',
  } as React.CSSProperties,

  controls: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    marginBottom: 16,
  } as React.CSSProperties,

  searchInput: {
    flex: 1,
    minWidth: 0,
    padding: '7px 12px',
    border: '1px solid #e2e8f0',
    borderRadius: 6,
    fontSize: 13,
    color: '#1e293b',
    outline: 'none',
  } as React.CSSProperties,

  select: {
    padding: '7px 10px',
    border: '1px solid #e2e8f0',
    borderRadius: 6,
    fontSize: 13,
    color: '#374151',
    background: '#fff',
    cursor: 'pointer',
  } as React.CSSProperties,

  tabs: {
    display: 'flex',
    gap: 0,
    borderBottom: '2px solid #e2e8f0',
    marginBottom: 16,
  } as React.CSSProperties,

  tab: (active: boolean): React.CSSProperties => ({
    padding: '8px 20px',
    fontSize: 13,
    fontWeight: active ? 600 : 400,
    color: active ? '#2563eb' : '#64748b',
    borderBottom: active ? '2px solid #2563eb' : '2px solid transparent',
    marginBottom: -2,
    cursor: 'pointer',
    background: 'none',
    border: 'none',
    borderBottomWidth: 2,
    borderBottomStyle: 'solid',
    borderBottomColor: active ? '#2563eb' : 'transparent',
    transition: 'color 0.12s',
  }),

  tableWrap: {
    overflowX: 'auto' as const,
    borderRadius: 8,
    boxShadow: '0 1px 4px rgba(0,0,0,0.06)',
  } as React.CSSProperties,

  table: {
    width: '100%',
    borderCollapse: 'collapse' as const,
    tableLayout: 'fixed' as const,
    fontSize: 13,
    background: '#fff',
  } as React.CSSProperties,

  th: {
    padding: '10px 12px',
    textAlign: 'left' as const,
    fontSize: 12,
    fontWeight: 600,
    color: '#64748b',
    background: '#f8fafc',
    borderBottom: '1px solid #e2e8f0',
    position: 'relative' as const,
    userSelect: 'none' as const,
    whiteSpace: 'nowrap' as const,
    overflow: 'hidden' as const,
  } as React.CSSProperties,

  td: {
    padding: '9px 12px',
    color: '#1e293b',
    borderBottom: '1px solid #f1f5f9',
    verticalAlign: 'top' as const,
    wordBreak: 'break-word' as const,
    overflowWrap: 'break-word' as const,
  } as React.CSSProperties,

  kindBadge: (kind: 'work' | 'material'): React.CSSProperties => ({
    display: 'inline-block',
    padding: '2px 8px',
    borderRadius: 4,
    fontSize: 11,
    fontWeight: 500,
    background: kind === 'work' ? '#dbeafe' : '#dcfce7',
    color: kind === 'work' ? '#1d4ed8' : '#15803d',
    whiteSpace: 'nowrap',
  }),

  pagination: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 16,
    flexWrap: 'wrap' as const,
    gap: 10,
  } as React.CSSProperties,

  paginationInfo: {
    fontSize: 13,
    color: '#64748b',
  } as React.CSSProperties,

  paginationBtns: {
    display: 'flex',
    gap: 4,
    alignItems: 'center',
  } as React.CSSProperties,

  pageBtn: (active: boolean, disabled?: boolean): React.CSSProperties => ({
    padding: '5px 10px',
    borderRadius: 5,
    border: '1px solid #e2e8f0',
    background: active ? '#2563eb' : '#fff',
    color: active ? '#fff' : disabled ? '#cbd5e1' : '#374151',
    fontSize: 13,
    cursor: disabled ? 'default' : 'pointer',
    minWidth: 32,
    textAlign: 'center',
  }),

  emptyState: {
    textAlign: 'center' as const,
    padding: '48px 24px',
    color: '#94a3b8',
    fontSize: 14,
  } as React.CSSProperties,

  // Modal
  overlay: {
    position: 'fixed' as const,
    inset: 0,
    background: 'rgba(15,23,42,0.35)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 1000,
  } as React.CSSProperties,

  modal: {
    background: '#fff',
    borderRadius: 10,
    padding: '28px 32px',
    width: '100%',
    maxWidth: 520,
    maxHeight: '90vh',
    overflowY: 'auto' as const,
    boxShadow: '0 8px 32px rgba(0,0,0,0.18)',
  } as React.CSSProperties,

  modalTitle: {
    fontSize: 17,
    fontWeight: 700,
    color: '#1e293b',
    marginBottom: 20,
  } as React.CSSProperties,

  field: {
    marginBottom: 14,
  } as React.CSSProperties,

  label: {
    display: 'block',
    fontSize: 12,
    fontWeight: 600,
    color: '#475569',
    marginBottom: 4,
  } as React.CSSProperties,

  input: {
    width: '100%',
    padding: '8px 10px',
    border: '1px solid #e2e8f0',
    borderRadius: 6,
    fontSize: 13,
    color: '#1e293b',
    outline: 'none',
    boxSizing: 'border-box' as const,
  } as React.CSSProperties,

  modalFooter: {
    display: 'flex',
    justifyContent: 'flex-end',
    gap: 10,
    marginTop: 20,
  } as React.CSSProperties,

  error: {
    padding: '10px 14px',
    background: '#fee2e2',
    color: '#b91c1c',
    borderRadius: 6,
    fontSize: 13,
    marginBottom: 14,
  } as React.CSSProperties,

  resizeHandle: {
    position: 'absolute' as const,
    right: 0,
    top: 0,
    bottom: 0,
    width: 5,
    cursor: 'col-resize',
    zIndex: 1,
    background: 'transparent',
  } as React.CSSProperties,

  resizeHandleHover: {
    background: 'rgba(37,99,235,0.25)',
  } as React.CSSProperties,
};

// ---------------------------------------------------------------------------
// SourceTooltip
// ---------------------------------------------------------------------------

function SourceTooltip({ text }: { text: string | null }) {
  const [show, setShow] = useState(false);
  if (!text) return <span style={{ color: '#94a3b8' }}>—</span>;
  const truncated = text.length > 40 ? text.slice(0, 40) + '…' : text;
  return (
    <span
      style={{ position: 'relative', cursor: 'default' }}
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
    >
      {truncated}
      {show && text.length > 40 && (
        <span
          style={{
            position: 'absolute',
            bottom: 'calc(100% + 4px)',
            left: 0,
            background: '#1e293b',
            color: '#fff',
            fontSize: 11,
            padding: '5px 10px',
            borderRadius: 4,
            whiteSpace: 'pre-line',
            zIndex: 200,
            maxWidth: 340,
            lineHeight: 1.6,
            pointerEvents: 'none',
            boxShadow: '0 4px 12px rgba(0,0,0,0.2)',
          }}
        >
          {text.replace(/; /g, '\n')}
        </span>
      )}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Tooltip button (instant tooltip, no browser delay)
// ---------------------------------------------------------------------------

interface TooltipBtnProps {
  label: string;
  onClick: () => void;
  danger?: boolean;
  icon: string;
}

function TooltipBtn({ label, onClick, danger, icon }: TooltipBtnProps) {
  const [show, setShow] = useState(false);
  return (
    <span style={{ position: 'relative', display: 'inline-block' }}>
      <button
        style={{
          ...s.btn,
          padding: '4px 10px',
          fontSize: 12,
          ...(danger ? s.btnDanger : {}),
        }}
        onClick={onClick}
        onMouseEnter={() => setShow(true)}
        onMouseLeave={() => setShow(false)}
        type="button"
      >
        {icon}
      </button>
      {show && (
        <span
          style={{
            position: 'absolute',
            bottom: 'calc(100% + 4px)',
            left: '50%',
            transform: 'translateX(-50%)',
            background: '#1e293b',
            color: '#fff',
            fontSize: 11,
            padding: '3px 8px',
            borderRadius: 4,
            whiteSpace: 'nowrap',
            pointerEvents: 'none',
            zIndex: 200,
          }}
        >
          {label}
        </span>
      )}
    </span>
  );
}

// ---------------------------------------------------------------------------
// ResizableTh
// ---------------------------------------------------------------------------

interface ResizableThProps {
  col: ColDef;
  width: number;
  onResizeStart: (e: React.MouseEvent, colId: string) => void;
  children: React.ReactNode;
}

function ResizableTh({ col, width, onResizeStart, children }: ResizableThProps) {
  const [hoverHandle, setHoverHandle] = useState(false);
  return (
    <th style={{ ...s.th, width, minWidth: width }}>
      {children}
      {!col.noResize && (
        <div
          style={{ ...s.resizeHandle, ...(hoverHandle ? s.resizeHandleHover : {}) }}
          onMouseEnter={() => setHoverHandle(true)}
          onMouseLeave={() => setHoverHandle(false)}
          onMouseDown={e => onResizeStart(e, col.id)}
        />
      )}
    </th>
  );
}

// ---------------------------------------------------------------------------
// ItemFormModal — add / edit (for catalog items)
// ---------------------------------------------------------------------------

interface ItemFormModalProps {
  title: string;
  initial: FormState;
  onClose: () => void;
  onSave: (form: FormState) => Promise<void>;
  allowKindChange: boolean;
}

function ItemFormModal({ title, initial, onClose, onSave, allowKindChange }: ItemFormModalProps) {
  const [form, setForm] = useState<FormState>(initial);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const setField = (key: keyof FormState, value: unknown) =>
    setForm(f => ({ ...f, [key]: value }));

  const setContractor = (idx: number, field: 'name' | 'price', value: string) => {
    setForm(f => {
      const contractors = [...f.contractors];
      contractors[idx] = { ...contractors[idx], [field]: value };
      return { ...f, contractors };
    });
  };

  const addContractor = () =>
    setForm(f => ({ ...f, contractors: [...f.contractors, { name: '', price: '' }] }));

  const removeContractor = (idx: number) =>
    setForm(f => ({ ...f, contractors: f.contractors.filter((_, i) => i !== idx) }));

  const handleSave = async () => {
    if (!form.name.trim()) { setError('Введите название'); return; }
    setSaving(true);
    setError('');
    try {
      await onSave(form);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(formatApiDetail(detail, 'Не удалось сохранить позицию. Попробуйте ещё раз.'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={s.overlay} onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div style={s.modal}>
        <div style={s.modalTitle}>{title}</div>

        {error && <div style={s.error}>{error}</div>}

        {allowKindChange && (
          <div style={s.field}>
            <label style={s.label}>Тип</label>
            <Select value={form.kind} onValueChange={v => setField('kind', v as 'work' | 'material')}>
              <SelectTrigger style={{ width: '100%' }}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="work">Работа</SelectItem>
                <SelectItem value="material">Материал</SelectItem>
              </SelectContent>
            </Select>
          </div>
        )}

        <div style={s.field}>
          <label style={s.label}>Наименование *</label>
          <input
            style={s.input}
            value={form.name}
            onChange={e => setField('name', e.target.value)}
            placeholder="Например: Кладка кирпича"
            autoFocus
          />
        </div>

        <div style={s.field}>
          <label style={s.label}>Ед. изм.</label>
          <input
            style={s.input}
            value={form.unit}
            onChange={e => setField('unit', e.target.value)}
            placeholder="м², шт, т..."
          />
        </div>

        {form.kind === 'material' ? (
          <div style={s.field}>
            <label style={s.label}>Цена</label>
            <input
              style={s.input}
              type="number"
              min="0"
              step="0.01"
              value={form.price}
              onChange={e => setField('price', e.target.value)}
              placeholder="0.00"
            />
          </div>
        ) : (
          <div style={s.field}>
            <label style={s.label}>Подрядчики и цены</label>
            {form.contractors.map((c, idx) => (
              <div key={idx} style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
                <input
                  style={{ ...s.input, flex: 2 }}
                  value={c.name}
                  onChange={e => setContractor(idx, 'name', e.target.value)}
                  placeholder="Имя подрядчика"
                />
                <input
                  style={{ ...s.input, flex: 1 }}
                  type="number"
                  min="0"
                  step="0.01"
                  value={c.price}
                  onChange={e => setContractor(idx, 'price', e.target.value)}
                  placeholder="Цена"
                />
                {form.contractors.length > 1 && (
                  <button
                    style={{ ...s.btn, padding: '7px 10px', color: '#ef4444', borderColor: '#fca5a5' }}
                    onClick={() => removeContractor(idx)}
                    type="button"
                  >
                    ✕
                  </button>
                )}
              </div>
            ))}
            <button style={{ ...s.btn, fontSize: 12 }} onClick={addContractor} type="button">
              + Добавить подрядчика
            </button>
          </div>
        )}

        <div style={s.modalFooter}>
          <button style={s.btn} onClick={onClose} disabled={saving}>Отмена</button>
          <button
            style={{ ...s.btn, ...s.btnPrimary, opacity: saving ? 0.7 : 1 }}
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? 'Сохранение...' : 'Сохранить'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// CacheFormModal — edit cache items
// ---------------------------------------------------------------------------

interface CacheFormModalProps {
  title: string;
  initial: CacheFormState;
  onClose: () => void;
  onSave: (form: CacheFormState) => Promise<void>;
}

function CacheFormModal({ title, initial, onClose, onSave }: CacheFormModalProps) {
  const [form, setForm] = useState<CacheFormState>(initial);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const setField = (key: keyof CacheFormState, value: string) =>
    setForm(f => ({ ...f, [key]: value }));

  const handleSave = async () => {
    if (!form.name.trim()) { setError('Введите название'); return; }
    setSaving(true);
    setError('');
    try {
      await onSave(form);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(formatApiDetail(detail, 'Не удалось сохранить. Попробуйте ещё раз.'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={s.overlay} onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div style={s.modal}>
        <div style={s.modalTitle}>{title}</div>

        {error && <div style={s.error}>{error}</div>}

        <div style={s.field}>
          <label style={s.label}>Наименование *</label>
          <input
            style={s.input}
            value={form.name}
            onChange={e => setField('name', e.target.value)}
            autoFocus
          />
        </div>

        <div style={s.field}>
          <label style={s.label}>Ед. изм.</label>
          <input
            style={s.input}
            value={form.unit}
            onChange={e => setField('unit', e.target.value)}
            placeholder="м², шт, т..."
          />
        </div>

        <div style={s.field}>
          <label style={s.label}>Цена</label>
          <input
            style={s.input}
            type="number"
            min="0"
            step="0.01"
            value={form.price}
            onChange={e => setField('price', e.target.value)}
            placeholder="0.00"
          />
        </div>

        <div style={s.field}>
          <label style={s.label}>Источник</label>
          <input
            style={s.input}
            value={form.sources}
            onChange={e => setField('sources', e.target.value)}
            placeholder="Источник 1: X руб; Источник 2: Y руб"
          />
        </div>

        <div style={s.modalFooter}>
          <button style={s.btn} onClick={onClose} disabled={saving}>Отмена</button>
          <button
            style={{ ...s.btn, ...s.btnPrimary, opacity: saving ? 0.7 : 1 }}
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? 'Сохранение...' : 'Сохранить'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ConfirmModal
// ---------------------------------------------------------------------------

interface ConfirmModalProps {
  message: string;
  onCancel: () => void;
  onConfirm: () => Promise<void>;
}

function ConfirmModal({ message, onCancel, onConfirm }: ConfirmModalProps) {
  const [loading, setLoading] = useState(false);

  const handleConfirm = async () => {
    setLoading(true);
    try { await onConfirm(); } finally { setLoading(false); }
  };

  return (
    <div style={s.overlay} onClick={e => { if (e.target === e.currentTarget) onCancel(); }}>
      <div style={{ ...s.modal, maxWidth: 380 }}>
        <div style={{ fontSize: 15, color: '#1e293b', marginBottom: 20, lineHeight: 1.5 }}>{message}</div>
        <div style={s.modalFooter}>
          <button style={s.btn} onClick={onCancel} disabled={loading}>Отмена</button>
          <button
            style={{ ...s.btn, ...s.btnDanger, background: '#fee2e2', opacity: loading ? 0.7 : 1 }}
            onClick={handleConfirm}
            disabled={loading}
          >
            {loading ? 'Удаление...' : 'Удалить'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ImportButton
// ---------------------------------------------------------------------------

interface ImportButtonProps {
  onDone: () => void;
}

function ImportButton({ onDone }: ImportButtonProps) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [type, setType] = useState<'works' | 'materials'>('works');
  const [loading, setLoading] = useState(false);

  const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setLoading(true);
    try {
      const form = new FormData();
      form.append('file', file);
      await apiClient.post(`/admin/price-lists/${type}`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      onDone();
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      alert(formatApiDetail(detail, 'Не удалось импортировать файл. Проверьте формат и попробуйте ещё раз.'));
    } finally {
      setLoading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  return (
    <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
      <Select value={type} onValueChange={v => setType(v as 'works' | 'materials')} size="sm">
        <SelectTrigger>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="works">Работы</SelectItem>
          <SelectItem value="materials">Материалы</SelectItem>
        </SelectContent>
      </Select>
      <button
        style={{ ...s.btn, opacity: loading ? 0.7 : 1 }}
        onClick={() => fileRef.current?.click()}
        disabled={loading}
      >
        {loading ? 'Импорт...' : '↑ Импорт'}
      </button>
      <input ref={fileRef} type="file" accept=".xlsx,.xls,.csv,.txt" style={{ display: 'none' }} onChange={handleFile} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function PriceCatalog() {
  const navigate = useNavigate();
  const { isAdmin, isManager } = useAuthStore();
  const [tab, setTab] = useState<Tab>('all');
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [sort, setSort] = useState<SortKey>('name_asc');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  // Catalog state
  const [items, setItems] = useState<CatalogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);

  const [showAdd, setShowAdd] = useState(false);
  const [editItem, setEditItem] = useState<CatalogItem | null>(null);
  const [deleteItem, setDeleteItem] = useState<CatalogItem | null>(null);

  // Cache state
  const [cacheItems, setCacheItems] = useState<CacheItem[]>([]);
  const [cacheTotal, setCacheTotal] = useState(0);
  const [editCacheItem, setEditCacheItem] = useState<CacheItem | null>(null);
  const [deleteCacheItem, setDeleteCacheItem] = useState<CacheItem | null>(null);

  const isCacheTab = tab === 'cache_works' || tab === 'cache_materials';
  const displayTotal = isCacheTab ? cacheTotal : total;

  // Column widths: keyed by `${tab}_${colId}`
  const [colWidths, setColWidths] = useState<Record<string, number>>(() => {
    const init: Record<string, number> = {};
    for (const [t, cols] of Object.entries(COL_DEFS)) {
      for (const col of cols) {
        if (col.defaultWidth) init[`${t}_${col.id}`] = col.defaultWidth;
      }
    }
    return init;
  });

  const resizingRef = useRef<{ colKey: string; startX: number; startW: number } | null>(null);

  const handleResizeStart = (e: React.MouseEvent, colId: string) => {
    const colKey = `${tab}_${colId}`;
    const th = (e.currentTarget as HTMLElement).closest('th');
    if (!th) return;
    resizingRef.current = { colKey, startX: e.clientX, startW: th.offsetWidth };

    const onMove = (evt: MouseEvent) => {
      if (!resizingRef.current) return;
      const delta = evt.clientX - resizingRef.current.startX;
      const newW = Math.max(50, resizingRef.current.startW + delta);
      setColWidths(prev => ({ ...prev, [resizingRef.current!.colKey]: newW }));
    };
    const onUp = () => {
      resizingRef.current = null;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    e.preventDefault();
  };

  const getWidth = (colId: string) => colWidths[`${tab}_${colId}`] ?? 100;

  // Debounce search
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  // Reset page on filter change
  useEffect(() => { setPage(1); }, [tab, debouncedSearch, sort, pageSize]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      if (isCacheTab) {
        const params = { page, page_size: pageSize, ...(debouncedSearch ? { search: debouncedSearch } : {}) };
        const data = tab === 'cache_works'
          ? await getCacheWorks(params)
          : await getCacheMaterials(params);
        setCacheItems(data.items);
        setCacheTotal(data.total);
      } else {
        const params: CatalogParams = { tab, sort, page, page_size: pageSize };
        if (debouncedSearch) params.search = debouncedSearch;
        const data = await getCatalog(params);
        setItems(data.items);
        setTotal(data.total);
      }
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, [tab, debouncedSearch, sort, page, pageSize, isCacheTab]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const totalPages = Math.max(1, Math.ceil(displayTotal / pageSize));
  const startIdx = (page - 1) * pageSize + 1;
  const endIdx = Math.min(page * pageSize, displayTotal);

  // ---------------------------------------------------------------------------
  // Save handlers — catalog
  // ---------------------------------------------------------------------------

  const handleAdd = async (form: FormState) => {
    if (form.kind === 'work') {
      await createWork({
        name: form.name,
        unit: form.unit || undefined,
        prices: buildPricesFromContractors(form.contractors),
      });
    } else {
      await createMaterial({
        name: form.name,
        unit: form.unit || undefined,
        price: form.price ? parseFloat(form.price) : undefined,
      });
    }
    setShowAdd(false);
    fetchData();
  };

  const handleEdit = async (form: FormState) => {
    if (!editItem) return;
    if (editItem.kind === 'work') {
      await updateWork(editItem.id, {
        name: form.name,
        unit: form.unit || undefined,
        prices: buildPricesFromContractors(form.contractors),
      });
    } else {
      await updateMaterial(editItem.id, {
        name: form.name,
        unit: form.unit || undefined,
        price: form.price ? parseFloat(form.price) : undefined,
      });
    }
    setEditItem(null);
    fetchData();
  };

  const handleDelete = async () => {
    if (!deleteItem) return;
    if (deleteItem.kind === 'work') {
      await deleteWork(deleteItem.id);
    } else {
      await deleteMaterial(deleteItem.id);
    }
    setDeleteItem(null);
    fetchData();
  };

  // ---------------------------------------------------------------------------
  // Save handlers — cache
  // ---------------------------------------------------------------------------

  const handleEditCache = async (form: CacheFormState) => {
    if (!editCacheItem) return;
    const data = {
      name: form.name,
      unit: form.unit || undefined,
      price: form.price ? parseFloat(form.price) : undefined,
      sources: form.sources || undefined,
    };
    if (tab === 'cache_works') {
      await updateCacheWork(editCacheItem.id, data);
    } else {
      await updateCacheMaterial(editCacheItem.id, data);
    }
    setEditCacheItem(null);
    fetchData();
  };

  const handleDeleteCache = async () => {
    if (!deleteCacheItem) return;
    if (tab === 'cache_works') {
      await deleteCacheWork(deleteCacheItem.id);
    } else {
      await deleteCacheMaterial(deleteCacheItem.id);
    }
    setDeleteCacheItem(null);
    fetchData();
  };

  const editFormFor = (item: CatalogItem): FormState => ({
    kind: item.kind,
    name: item.name,
    unit: item.unit || '',
    price: item.kind === 'material' ? String(item.price ?? '') : '',
    contractors: item.kind === 'work' ? contractorsFromPrices(item.prices) : [{ name: '', price: '' }],
  });

  const cacheEditFormFor = (item: CacheItem): CacheFormState => ({
    name: item.name,
    unit: item.unit || '',
    price: String(item.price),
    sources: item.sources || '',
  });

  // ---------------------------------------------------------------------------
  // Table rendering
  // ---------------------------------------------------------------------------

  // Каталог — общий корпоративный справочник: по нему считаются сметы всех
  // пользователей. Менять его вправе только руководитель или админ (на бэкенде
  // это get_manager_user). Рядовому исполнителю кнопки не показываем — иначе он
  // нажмёт и получит 403 без объяснения.
  const actionsTd = (item: CatalogItem) => (
    <td style={{ ...s.td, whiteSpace: 'nowrap', verticalAlign: 'middle' }}>
      {isManager ? (
        <>
          <TooltipBtn label="Редактировать" icon="✎" onClick={() => setEditItem(item)} />
          {' '}
          <TooltipBtn label="Удалить" icon="✕" onClick={() => setDeleteItem(item)} danger />
        </>
      ) : (
        <span style={{ color: '#94a3b8', fontSize: 12 }}>только просмотр</span>
      )}
    </td>
  );

  const renderColgroup = () => (
    <colgroup>
      {COL_DEFS[tab].map(col => (
        <col key={col.id} style={{ width: getWidth(col.id) }} />
      ))}
    </colgroup>
  );

  const renderHead = () => (
    <tr>
      {COL_DEFS[tab].map(col => (
        <ResizableTh
          key={col.id}
          col={col}
          width={getWidth(col.id)}
          onResizeStart={handleResizeStart}
        >
          {col.label}
        </ResizableTh>
      ))}
    </tr>
  );

  const renderRow = (item: CatalogItem, idx: number) => {
    const rowNum = startIdx + idx;
    const rowBg = { background: idx % 2 === 0 ? '#fff' : '#fafafa' };

    if (tab === 'works') {
      const contractorsText = item.prices
        ? Object.entries(item.prices).map(([k, v]) => `${k}: ${formatPrice(v)}`).join('\n')
        : '—';
      return (
        <tr key={item.id} style={rowBg}>
          <td style={{ ...s.td, color: '#94a3b8' }}>{rowNum}</td>
          <td style={s.td}>{item.name}</td>
          <td style={{ ...s.td, color: '#64748b' }}>{item.unit || '—'}</td>
          <td style={{ ...s.td, color: '#64748b', whiteSpace: 'pre-line' }}>{contractorsText}</td>
          <td style={{ ...s.td, fontWeight: 500 }}>{formatPrice(item.price)}</td>
          <td style={{ ...s.td, color: '#94a3b8' }}>{formatDate(item.updated_at)}</td>
          {actionsTd(item)}
        </tr>
      );
    }

    if (tab === 'materials') {
      return (
        <tr key={item.id} style={rowBg}>
          <td style={{ ...s.td, color: '#94a3b8' }}>{rowNum}</td>
          <td style={s.td}>{item.name}</td>
          <td style={{ ...s.td, color: '#64748b' }}>{item.unit || '—'}</td>
          <td style={{ ...s.td, fontWeight: 500 }}>{formatPrice(item.price)}</td>
          <td style={{ ...s.td, color: '#94a3b8' }}>{formatDate(item.updated_at)}</td>
          {actionsTd(item)}
        </tr>
      );
    }

    // tab === 'all'
    return (
      <tr key={item.id} style={rowBg}>
        <td style={{ ...s.td, color: '#94a3b8' }}>{rowNum}</td>
        <td style={s.td}>
          <span style={s.kindBadge(item.kind)}>
            {item.kind === 'work' ? 'Работа' : 'Материал'}
          </span>
        </td>
        <td style={s.td}>{item.name}</td>
        <td style={{ ...s.td, color: '#64748b' }}>{item.unit || '—'}</td>
        <td style={{ ...s.td, fontWeight: 500 }}>{formatPrice(item.price)}</td>
        <td style={{ ...s.td, color: '#94a3b8' }}>{formatDate(item.updated_at)}</td>
        {actionsTd(item)}
      </tr>
    );
  };

  const renderCacheRow = (item: CacheItem, idx: number) => {
    const rowNum = startIdx + idx;
    const rowBg = { background: idx % 2 === 0 ? '#fff' : '#fafafa' };
    return (
      <tr key={item.id} style={rowBg}>
        <td style={{ ...s.td, color: '#94a3b8' }}>{rowNum}</td>
        <td style={s.td}>{item.name}</td>
        <td style={{ ...s.td, color: '#64748b' }}>{item.unit || '—'}</td>
        <td style={{ ...s.td, fontWeight: 500 }}>{formatPrice(item.price)}</td>
        <td style={s.td}><SourceTooltip text={item.sources} /></td>
        <td style={{ ...s.td, color: '#94a3b8' }}>{formatDate(item.updated_at)}</td>
        <td style={s.td}>{renderExpires(item.expires_in_days)}</td>
        <td style={{ ...s.td, whiteSpace: 'nowrap', verticalAlign: 'middle' }}>
          <TooltipBtn label="Редактировать" icon="✎" onClick={() => setEditCacheItem(item)} />
          {' '}
          <TooltipBtn label="Удалить" icon="✕" onClick={() => setDeleteCacheItem(item)} danger />
        </td>
      </tr>
    );
  };

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <Layout>
      <div style={s.page}>
        {/* Header */}
        <div style={s.header}>
          <h1 style={s.title}>Каталог расценок</h1>
          {!isCacheTab && (
            <div style={s.headerActions}>
              <ImportButton onDone={fetchData} />
              <button
                style={s.btn}
                onClick={() => exportCatalog(tab as 'all' | 'works' | 'materials', debouncedSearch || undefined)}
              >
                ↓ Экспорт
              </button>
              <div style={{ display: 'flex', gap: 6 }}>
                <button style={s.btn} onClick={() => downloadTemplate('works')}>Шаблон работ</button>
                <button style={s.btn} onClick={() => downloadTemplate('materials')}>Шаблон материалов</button>
              </div>
              {isManager && (
                <button
                  style={{ ...s.btn, ...s.btnPrimary }}
                  onClick={() => setShowAdd(true)}
                >
                  + Добавить позицию
                </button>
              )}
            </div>
          )}
        </div>

        {/* Controls */}
        <div style={s.controls}>
          <input
            style={s.searchInput}
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Поиск по названию..."
          />
          {!isCacheTab && (
            <Select value={sort} onValueChange={v => setSort(v as SortKey)} size="sm">
              <SelectTrigger style={{ width: 160, flexShrink: 0 }}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SORT_OPTIONS.map(o => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
              </SelectContent>
            </Select>
          )}
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, color: '#64748b', flexShrink: 0, whiteSpace: 'nowrap' }}>
            Строк:
            <Select value={String(pageSize)} onValueChange={v => setPageSize(Number(v))} size="sm">
              <SelectTrigger style={{ width: 70 }}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PAGE_SIZE_OPTIONS.map(n => <SelectItem key={n} value={String(n)}>{n}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
        </div>

        {/* Tabs */}
        <div style={s.tabs}>
          {(['all', 'works', 'materials', 'cache_works', 'cache_materials'] as Tab[]).map(t => (
            <button key={t} style={s.tab(tab === t)} onClick={() => setTab(t)}>
              {t === 'all'
                ? 'Все'
                : t === 'works'
                  ? 'Работы'
                  : t === 'materials'
                    ? 'Материалы'
                    : t === 'cache_works'
                      ? 'Кеш работ'
                      : 'Кеш материалов'}
            </button>
          ))}
          {isAdmin && (
            <button style={s.tab(false)} onClick={() => navigate('/retraining')}>
              Дообучение
            </button>
          )}
        </div>

        {/* Table */}
        {loading ? (
          <div style={s.emptyState}>Загрузка...</div>
        ) : isCacheTab ? (
          cacheItems.length === 0 ? (
            <div style={s.emptyState}>
              {debouncedSearch
                ? `Ничего не найдено по запросу «${debouncedSearch}»`
                : 'Кеш цен пуст. Записи появятся автоматически после web-поиска.'}
            </div>
          ) : (
            <div style={s.tableWrap}>
              <table style={s.table}>
                {renderColgroup()}
                <thead>{renderHead()}</thead>
                <tbody>
                  {cacheItems.map((item, idx) => renderCacheRow(item, idx))}
                </tbody>
              </table>
            </div>
          )
        ) : (
          items.length === 0 ? (
            <div style={s.emptyState}>
              {debouncedSearch
                ? `Ничего не найдено по запросу «${debouncedSearch}»`
                : 'Нет позиций. Загрузите прайс или добавьте вручную.'}
            </div>
          ) : (
            <div style={s.tableWrap}>
              <table style={s.table}>
                {renderColgroup()}
                <thead>{renderHead()}</thead>
                <tbody>
                  {items.map((item, idx) => renderRow(item, idx))}
                </tbody>
              </table>
            </div>
          )
        )}

        {/* Pagination */}
        {displayTotal > 0 && (
          <div style={s.pagination}>
            <span style={s.paginationInfo}>
              {startIdx}–{endIdx} из {displayTotal}
            </span>
            <div style={s.paginationBtns}>
              <button
                style={s.pageBtn(false, page === 1)}
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={page === 1}
              >
                ←
              </button>
              {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
                let p: number;
                if (totalPages <= 7) {
                  p = i + 1;
                } else if (page <= 4) {
                  p = i + 1;
                } else if (page >= totalPages - 3) {
                  p = totalPages - 6 + i;
                } else {
                  p = page - 3 + i;
                }
                return (
                  <button key={p} style={s.pageBtn(p === page)} onClick={() => setPage(p)}>
                    {p}
                  </button>
                );
              })}
              <button
                style={s.pageBtn(false, page === totalPages)}
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
              >
                →
              </button>
            </div>
          </div>
        )}

        {/* Catalog modals */}
        {showAdd && (
          <ItemFormModal
            title="Добавить позицию"
            initial={{ ...EMPTY_FORM, kind: tab === 'materials' ? 'material' : 'work' }}
            onClose={() => setShowAdd(false)}
            onSave={handleAdd}
            allowKindChange={true}
          />
        )}

        {editItem && (
          <ItemFormModal
            title={`Редактировать: ${editItem.kind === 'work' ? 'Работа' : 'Материал'}`}
            initial={editFormFor(editItem)}
            onClose={() => setEditItem(null)}
            onSave={handleEdit}
            allowKindChange={false}
          />
        )}

        {deleteItem && (
          <ConfirmModal
            message={`Удалить позицию «${deleteItem.name}»? Это действие необратимо.`}
            onCancel={() => setDeleteItem(null)}
            onConfirm={handleDelete}
          />
        )}

        {/* Cache modals */}
        {editCacheItem && (
          <CacheFormModal
            title={`Редактировать запись кеша`}
            initial={cacheEditFormFor(editCacheItem)}
            onClose={() => setEditCacheItem(null)}
            onSave={handleEditCache}
          />
        )}

        {deleteCacheItem && (
          <ConfirmModal
            message={`Удалить запись кеша «${deleteCacheItem.name}»? Это действие необратимо.`}
            onCancel={() => setDeleteCacheItem(null)}
            onConfirm={handleDeleteCache}
          />
        )}
      </div>
    </Layout>
  );
}
