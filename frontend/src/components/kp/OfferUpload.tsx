import React, { useRef, useState } from 'react';
import { Paperclip, X } from 'lucide-react';

import {
  KP_DEFAULT_VAT_RATE, KP_MAX_FILE_MB, KP_OFFER_EXTENSIONS,
  KpCategory, KpOfferForm, KpVatMode,
} from '../../types/kp';

/**
 * Форма КП: загрузка нового и правка условий уже загруженного
 * (план plans/2026-09-14-zapros-kp.md, фаза 5, критерий 15).
 *
 * * Режим НДС **обязателен** и по умолчанию не выбран: молча «без НДС»
 *   завысило бы приведённые цены на 22 % — сервер без режима тоже отвечает 422.
 * * Ставка появляется только при «с НДС», по умолчанию 22 %, правится.
 * * «Цена включает материалы» — только в запросе по работам: у материала такой
 *   отметки не бывает, сервер её отклонит.
 * * Новое КП — файл или поставщик (КП по телефону бывает без файла).
 *
 * Проверки здесь — чтобы человек узнал об ошибке до загрузки 50 МБ; окончательно
 * решает сервер, его текст ошибки показывает страница.
 */

interface Props {
  category: KpCategory;
  mode?: 'create' | 'edit';
  initial?: Partial<KpOfferForm>;
  /** В режиме правки: у КП уже есть файл — поставщик тогда необязателен. */
  hasFile?: boolean;
  busy?: boolean;
  /** true — форма очищается (КП загружено). */
  onSubmit: (form: KpOfferForm, file: File | null) => Promise<unknown> | unknown;
  onCancel?: () => void;
}

const EMPTY: KpOfferForm = {
  supplier_name: '', offer_date: '', vat_mode: null, vat_rate: String(KP_DEFAULT_VAT_RATE),
  includes_materials: false,
};

const label: React.CSSProperties = { fontSize: 13, fontWeight: 600, color: '#374151' };
const input: React.CSSProperties = {
  height: 32, padding: '0 10px', borderRadius: 8, border: '1px solid #e2e8f0',
  fontSize: 14, color: '#1e293b', background: '#fff', boxSizing: 'border-box',
};
const primary: React.CSSProperties = {
  height: 34, padding: '0 16px', borderRadius: 8, border: 'none', background: '#2563eb',
  color: '#fff', fontSize: 14, fontWeight: 600, cursor: 'pointer',
};
const secondary: React.CSSProperties = {
  height: 34, padding: '0 14px', borderRadius: 8, border: '1px solid #e2e8f0',
  background: '#fff', color: '#475569', fontSize: 14, fontWeight: 500, cursor: 'pointer',
};

function fileProblem(file: File): string | null {
  const dot = file.name.lastIndexOf('.');
  const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : '';
  if (!KP_OFFER_EXTENSIONS.includes(ext)) {
    return `${file.name} — тип файла не поддерживается (PDF, XLSX, XLS, JPG, PNG)`;
  }
  if (file.size > KP_MAX_FILE_MB * 1024 * 1024) return `${file.name} — файл больше ${KP_MAX_FILE_MB} МБ`;
  return null;
}

/** Ставка: число от 0 до 100 (не включая); пусто — сервер подставит 22 %. */
export function vatRateProblem(value: string): string | null {
  const text = value.trim().replace(',', '.');
  if (!text) return null;
  const rate = Number(text);
  if (!Number.isFinite(rate) || rate < 0 || rate >= 100) return 'Ставка НДС — число от 0 до 100 %';
  return null;
}

const OfferUpload: React.FC<Props> = ({
  category, mode = 'create', initial, hasFile = false, busy = false, onSubmit, onCancel,
}) => {
  const [form, setForm] = useState<KpOfferForm>({ ...EMPTY, ...initial });
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const set = <K extends keyof KpOfferForm>(key: K, value: KpOfferForm[K]) => (
    setForm((prev) => ({ ...prev, [key]: value }))
  );

  const setVatMode = (value: KpVatMode) => setForm((prev) => ({
    ...prev,
    vat_mode: value,
    // Вернулись к «с НДС» с пустой ставкой — снова 22 %.
    vat_rate: value === 'with_vat' && !prev.vat_rate.trim() ? String(KP_DEFAULT_VAT_RATE) : prev.vat_rate,
  }));

  const rateError = form.vat_mode === 'with_vat' ? vatRateProblem(form.vat_rate) : null;
  const needsSupplier = mode === 'create' ? !file : !hasFile;
  const problems: string[] = [];
  if (!form.vat_mode) problems.push('Укажите, цены в КП с НДС или без НДС');
  if (needsSupplier && !form.supplier_name.trim()) {
    problems.push(mode === 'create' ? 'Приложите файл КП или укажите поставщика' : 'Укажите поставщика');
  }
  if (rateError) problems.push(rateError);
  const disabled = busy || problems.length > 0;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (disabled) return;
    const payload: KpOfferForm = {
      ...form,
      includes_materials: category === 'work' ? form.includes_materials : false,
    };
    const result = await onSubmit(payload, mode === 'create' ? file : null);
    if (result === true && mode === 'create') {
      setForm({ ...EMPTY });
      setFile(null);
      if (inputRef.current) inputRef.current.value = '';
    }
  };

  const idPrefix = mode === 'create' ? 'kp-offer-new' : 'kp-offer-edit';

  return (
    <form
      onSubmit={submit}
      data-testid={`${idPrefix}-form`}
      style={{
        display: 'flex', flexDirection: 'column', gap: 12, padding: 16,
        border: '1px solid #e2e8f0', borderRadius: 12, background: '#fff',
      }}
    >
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16 }}>
        {mode === 'create' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 220 }}>
            <label htmlFor={`${idPrefix}-file`} style={label}>Файл КП</label>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <input
                ref={inputRef}
                id={`${idPrefix}-file`}
                type="file"
                accept={KP_OFFER_EXTENSIONS.join(',')}
                style={{ fontSize: 13, maxWidth: 260 }}
                disabled={busy}
                onChange={(e) => {
                  const picked = e.target.files?.[0] ?? null;
                  const problem = picked ? fileProblem(picked) : null;
                  setFileError(problem);
                  setFile(problem ? null : picked);
                  if (problem && inputRef.current) inputRef.current.value = '';
                }}
              />
              {file && (
                <button
                  type="button"
                  aria-label="Убрать файл"
                  style={{ ...secondary, height: 26, padding: '0 6px' }}
                  onClick={() => {
                    setFile(null);
                    if (inputRef.current) inputRef.current.value = '';
                  }}
                >
                  <X size={12} />
                </button>
              )}
            </div>
            <span style={{ fontSize: 12, color: '#94a3b8' }}>
              <Paperclip size={11} /> PDF, XLSX, XLS, JPG, PNG — до {KP_MAX_FILE_MB} МБ, PDF до 100 стр.
            </span>
          </div>
        )}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: '1 1 220px' }}>
          <label htmlFor={`${idPrefix}-supplier`} style={label}>Поставщик</label>
          <input
            id={`${idPrefix}-supplier`}
            style={input}
            maxLength={500}
            value={form.supplier_name}
            disabled={busy}
            onChange={(e) => set('supplier_name', e.target.value)}
            placeholder="ООО «Поставщик»"
          />
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <label htmlFor={`${idPrefix}-date`} style={label}>Дата КП</label>
          <input
            id={`${idPrefix}-date`}
            type="date"
            style={input}
            value={form.offer_date}
            disabled={busy}
            onChange={(e) => set('offer_date', e.target.value)}
          />
        </div>
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 16 }}>
        <fieldset style={{ border: 'none', padding: 0, margin: 0, display: 'flex', alignItems: 'center', gap: 12 }}>
          <legend style={{ ...label, float: 'left', marginRight: 12 }}>Цены в КП</legend>
          {(['with_vat', 'without_vat'] as const).map((value) => (
            <label key={value} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 14, color: '#334155' }}>
              <input
                type="radio"
                name={`${idPrefix}-vat`}
                value={value}
                checked={form.vat_mode === value}
                disabled={busy}
                onChange={() => setVatMode(value)}
              />
              {value === 'with_vat' ? 'с НДС' : 'без НДС'}
            </label>
          ))}
        </fieldset>

        {form.vat_mode === 'with_vat' && (
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <label htmlFor={`${idPrefix}-rate`} style={label}>Ставка НДС, %</label>
            <input
              id={`${idPrefix}-rate`}
              style={{ ...input, width: 72, borderColor: rateError ? '#fecaca' : '#e2e8f0' }}
              inputMode="decimal"
              value={form.vat_rate}
              disabled={busy}
              onChange={(e) => set('vat_rate', e.target.value)}
            />
          </div>
        )}

        {category === 'work' && (
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 14, color: '#334155' }}>
            <input
              type="checkbox"
              checked={form.includes_materials}
              disabled={busy}
              onChange={(e) => set('includes_materials', e.target.checked)}
            />
            Цена включает материалы
          </label>
        )}
      </div>

      {(fileError || problems.length > 0) && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2, fontSize: 12 }}>
          {fileError && <span style={{ color: '#b91c1c' }}>{fileError}</span>}
          {problems.map((text) => <span key={text} style={{ color: '#64748b' }}>{text}</span>)}
        </div>
      )}

      <div style={{ display: 'flex', gap: 8 }}>
        <button type="submit" style={{ ...primary, background: disabled ? '#93c5fd' : '#2563eb' }} disabled={disabled}>
          {mode === 'create' ? 'Загрузить КП' : 'Сохранить условия'}
        </button>
        {onCancel && (
          <button type="button" style={secondary} disabled={busy} onClick={onCancel}>Отмена</button>
        )}
      </div>
    </form>
  );
};

export default OfferUpload;
