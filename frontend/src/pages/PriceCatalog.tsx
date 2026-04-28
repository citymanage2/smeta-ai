import React, { useCallback, useEffect, useRef, useState } from 'react';
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
import apiClient from '../api/client';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Tab = 'all' | 'works' | 'materials';
type SortKey = 'name_asc' | 'name_desc' | 'price_asc' | 'price_desc' | 'date_asc' | 'date_desc';

interface FormState {
  kind: 'work' | 'material';
  name: string;
  unit: string;
  price: string;
  contractors: { name: string; price: string }[];
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

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const s = {
  page: {
    padding: '28px 32px',
    maxWidth: 1200,
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
    gap: 10,
    marginBottom: 16,
    flexWrap: 'wrap' as const,
  } as React.CSSProperties,

  searchInput: {
    flex: '1 1 200px',
    padding: '7px 12px',
    border: '1px solid #e2e8f0',
    borderRadius: 6,
    fontSize: 13,
    color: '#1e293b',
    outline: 'none',
    minWidth: 180,
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

  table: {
    width: '100%',
    borderCollapse: 'collapse' as const,
    fontSize: 13,
    background: '#fff',
    borderRadius: 8,
    overflow: 'hidden',
    boxShadow: '0 1px 4px rgba(0,0,0,0.06)',
  } as React.CSSProperties,

  th: {
    padding: '10px 12px',
    textAlign: 'left' as const,
    fontSize: 12,
    fontWeight: 600,
    color: '#64748b',
    background: '#f8fafc',
    borderBottom: '1px solid #e2e8f0',
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,

  td: {
    padding: '9px 12px',
    color: '#1e293b',
    borderBottom: '1px solid #f1f5f9',
    verticalAlign: 'middle' as const,
  } as React.CSSProperties,

  kindBadge: (kind: 'work' | 'material'): React.CSSProperties => ({
    display: 'inline-block',
    padding: '2px 8px',
    borderRadius: 4,
    fontSize: 11,
    fontWeight: 500,
    background: kind === 'work' ? '#dbeafe' : '#dcfce7',
    color: kind === 'work' ? '#1d4ed8' : '#15803d',
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
};

// ---------------------------------------------------------------------------
// ItemFormModal — add / edit
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
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg || 'Ошибка сохранения');
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
            <select
              style={{ ...s.input, cursor: 'pointer' }}
              value={form.kind}
              onChange={e => setField('kind', e.target.value as 'work' | 'material')}
            >
              <option value="work">Работа</option>
              <option value="material">Материал</option>
            </select>
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
// ImportButton — использует существующий /admin/price-lists/{type}
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
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      alert(msg || 'Ошибка импорта');
    } finally {
      setLoading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  return (
    <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
      <select
        style={{ ...s.select, fontSize: 12 }}
        value={type}
        onChange={e => setType(e.target.value as 'works' | 'materials')}
      >
        <option value="works">Работы</option>
        <option value="materials">Материалы</option>
      </select>
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
  const [tab, setTab] = useState<Tab>('all');
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [sort, setSort] = useState<SortKey>('name_asc');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const [items, setItems] = useState<CatalogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);

  const [showAdd, setShowAdd] = useState(false);
  const [editItem, setEditItem] = useState<CatalogItem | null>(null);
  const [deleteItem, setDeleteItem] = useState<CatalogItem | null>(null);

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
      const params: CatalogParams = { tab, sort, page, page_size: pageSize };
      if (debouncedSearch) params.search = debouncedSearch;
      const data = await getCatalog(params);
      setItems(data.items);
      setTotal(data.total);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, [tab, debouncedSearch, sort, page, pageSize]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const startIdx = (page - 1) * pageSize + 1;
  const endIdx = Math.min(page * pageSize, total);

  // ---------------------------------------------------------------------------
  // Save handlers
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

  const editFormFor = (item: CatalogItem): FormState => ({
    kind: item.kind,
    name: item.name,
    unit: item.unit || '',
    price: item.kind === 'material' ? String(item.price ?? '') : '',
    contractors: item.kind === 'work' ? contractorsFromPrices(item.prices) : [{ name: '', price: '' }],
  });

  // ---------------------------------------------------------------------------
  // Table columns
  // ---------------------------------------------------------------------------

  const renderHead = () => {
    if (tab === 'works') {
      return (
        <tr>
          <th style={s.th}>#</th>
          <th style={s.th}>Наименование</th>
          <th style={s.th}>Ед. изм.</th>
          <th style={s.th}>Подрядчики</th>
          <th style={s.th}>Мин. цена</th>
          <th style={s.th}>Обновлено</th>
          <th style={{ ...s.th, width: 90 }}></th>
        </tr>
      );
    }
    if (tab === 'materials') {
      return (
        <tr>
          <th style={s.th}>#</th>
          <th style={s.th}>Наименование</th>
          <th style={s.th}>Ед. изм.</th>
          <th style={s.th}>Цена</th>
          <th style={s.th}>Обновлено</th>
          <th style={{ ...s.th, width: 90 }}></th>
        </tr>
      );
    }
    return (
      <tr>
        <th style={s.th}>#</th>
        <th style={s.th}>Наименование</th>
        <th style={s.th}>Тип</th>
        <th style={s.th}>Ед. изм.</th>
        <th style={s.th}>Цена</th>
        <th style={s.th}>Обновлено</th>
        <th style={{ ...s.th, width: 90 }}></th>
      </tr>
    );
  };

  const renderRow = (item: CatalogItem, idx: number) => {
    const rowNum = startIdx + idx;
    const actions = (
      <td style={{ ...s.td, whiteSpace: 'nowrap' }}>
        <button
          style={{ ...s.btn, padding: '4px 10px', fontSize: 12 }}
          onClick={() => setEditItem(item)}
          title="Редактировать"
        >
          ✎
        </button>
        <button
          style={{ ...s.btn, ...s.btnDanger, padding: '4px 10px', fontSize: 12, marginLeft: 4 }}
          onClick={() => setDeleteItem(item)}
          title="Удалить"
        >
          ✕
        </button>
      </td>
    );

    if (tab === 'works') {
      const contractors = item.prices ? Object.entries(item.prices).map(([k, v]) => `${k}: ${formatPrice(v)}`).join(', ') : '—';
      return (
        <tr key={item.id} style={{ background: idx % 2 === 0 ? '#fff' : '#fafafa' }}>
          <td style={{ ...s.td, color: '#94a3b8', width: 36 }}>{rowNum}</td>
          <td style={s.td}>{item.name}</td>
          <td style={{ ...s.td, color: '#64748b' }}>{item.unit || '—'}</td>
          <td style={{ ...s.td, color: '#64748b', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{contractors}</td>
          <td style={{ ...s.td, fontWeight: 500 }}>{formatPrice(item.price)}</td>
          <td style={{ ...s.td, color: '#94a3b8' }}>{formatDate(item.updated_at)}</td>
          {actions}
        </tr>
      );
    }

    if (tab === 'materials') {
      return (
        <tr key={item.id} style={{ background: idx % 2 === 0 ? '#fff' : '#fafafa' }}>
          <td style={{ ...s.td, color: '#94a3b8', width: 36 }}>{rowNum}</td>
          <td style={s.td}>{item.name}</td>
          <td style={{ ...s.td, color: '#64748b' }}>{item.unit || '—'}</td>
          <td style={{ ...s.td, fontWeight: 500 }}>{formatPrice(item.price)}</td>
          <td style={{ ...s.td, color: '#94a3b8' }}>{formatDate(item.updated_at)}</td>
          {actions}
        </tr>
      );
    }

    return (
      <tr key={item.id} style={{ background: idx % 2 === 0 ? '#fff' : '#fafafa' }}>
        <td style={{ ...s.td, color: '#94a3b8', width: 36 }}>{rowNum}</td>
        <td style={s.td}>{item.name}</td>
        <td style={s.td}>
          <span style={s.kindBadge(item.kind)}>
            {item.kind === 'work' ? 'Работа' : 'Материал'}
          </span>
        </td>
        <td style={{ ...s.td, color: '#64748b' }}>{item.unit || '—'}</td>
        <td style={{ ...s.td, fontWeight: 500 }}>{formatPrice(item.price)}</td>
        <td style={{ ...s.td, color: '#94a3b8' }}>{formatDate(item.updated_at)}</td>
        {actions}
      </tr>
    );
  };

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div style={s.page}>
      {/* Header */}
      <div style={s.header}>
        <h1 style={s.title}>Каталог расценок</h1>
        <div style={s.headerActions}>
          <ImportButton onDone={fetchData} />
          <button
            style={s.btn}
            onClick={() => exportCatalog(tab, debouncedSearch || undefined)}
          >
            ↓ Экспорт
          </button>
          <div style={{ display: 'flex', gap: 6 }}>
            <button style={s.btn} onClick={() => downloadTemplate('works')}>Шаблон работ</button>
            <button style={s.btn} onClick={() => downloadTemplate('materials')}>Шаблон материалов</button>
          </div>
          <button
            style={{ ...s.btn, ...s.btnPrimary }}
            onClick={() => setShowAdd(true)}
          >
            + Добавить позицию
          </button>
        </div>
      </div>

      {/* Controls */}
      <div style={s.controls}>
        <input
          style={s.searchInput}
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Поиск по названию..."
        />
        <select style={s.select} value={sort} onChange={e => setSort(e.target.value as SortKey)}>
          {SORT_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, color: '#64748b' }}>
          Строк:
          <select style={s.select} value={pageSize} onChange={e => setPageSize(Number(e.target.value))}>
            {PAGE_SIZE_OPTIONS.map(n => <option key={n} value={n}>{n}</option>)}
          </select>
        </div>
      </div>

      {/* Tabs */}
      <div style={s.tabs}>
        {(['all', 'works', 'materials'] as Tab[]).map(t => (
          <button key={t} style={s.tab(tab === t)} onClick={() => setTab(t)}>
            {t === 'all' ? 'Все' : t === 'works' ? 'Работы' : 'Материалы'}
          </button>
        ))}
      </div>

      {/* Table */}
      {loading ? (
        <div style={s.emptyState}>Загрузка...</div>
      ) : items.length === 0 ? (
        <div style={s.emptyState}>
          {debouncedSearch
            ? `Ничего не найдено по запросу «${debouncedSearch}»`
            : 'Нет позиций. Загрузите прайс или добавьте вручную.'}
        </div>
      ) : (
        <table style={s.table}>
          <thead>{renderHead()}</thead>
          <tbody>
            {items.map((item, idx) => renderRow(item, idx))}
          </tbody>
        </table>
      )}

      {/* Pagination */}
      {total > 0 && (
        <div style={s.pagination}>
          <span style={s.paginationInfo}>
            {startIdx}–{endIdx} из {total}
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

      {/* Modals */}
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
    </div>
  );
}
