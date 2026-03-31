import React, { useState } from 'react';
import Layout from '../components/Layout';
import apiClient from '../api/client';

// ── Types ────────────────────────────────────────────────────────────────────

type CeilingType = 'flat' | 'cornice' | 'slope';
type FloorType = 'flat' | 'leveled';

interface RoomInput {
  length: string;
  width: string;
  height: string;
  door_count: string;
  door_width: string;
  door_height: string;
  window_count: string;
  window_width: string;
  window_height: string;
  extra_opening_area: string;
  ceiling_type: CeilingType;
  slope_angle: string;
  cornice_width: string;
  floor_type: FloorType;
  floor_screed_thickness: string;
  skirting_height: string;
  extra_wall_area: string;
  tile_height: string;
}

interface RoomResult {
  perimeter: number;
  floor_area: number;
  ceiling_area: number;
  total_volume: number;
  wall_area_gross: number;
  wall_area_net: number;
  wall_tile_area: number;
  door_area: number;
  window_area: number;
  ceiling_area_gross: number;
  cornice_area: number;
  floor_screed_volume: number;
  skirting_length: number;
  skirting_area: number;
  paint_area_net: number;
  wallpaper_area_net: number;
}

// ── Defaults ─────────────────────────────────────────────────────────────────

const DEFAULT: RoomInput = {
  length: '',
  width: '',
  height: '',
  door_count: '0',
  door_width: '0.9',
  door_height: '2.1',
  window_count: '0',
  window_width: '1.2',
  window_height: '1.4',
  extra_opening_area: '0',
  ceiling_type: 'flat',
  slope_angle: '30',
  cornice_width: '0',
  floor_type: 'flat',
  floor_screed_thickness: '0.05',
  skirting_height: '0.1',
  extra_wall_area: '0',
  tile_height: '0',
};

// ── Result groups ─────────────────────────────────────────────────────────────

const RESULT_GROUPS: Array<{
  title: string;
  rows: Array<{ key: keyof RoomResult; label: string; unit: string }>;
}> = [
  {
    title: 'Площади',
    rows: [
      { key: 'floor_area', label: 'Площадь пола', unit: 'м²' },
      { key: 'ceiling_area_gross', label: 'Площадь потолка (с наклоном)', unit: 'м²' },
      { key: 'ceiling_area', label: 'Площадь потолка (расчётная)', unit: 'м²' },
      { key: 'cornice_area', label: 'Площадь карниза', unit: 'м²' },
      { key: 'wall_area_gross', label: 'Площадь стен (грязная)', unit: 'м²' },
      { key: 'wall_area_net', label: 'Площадь стен (чистая)', unit: 'м²' },
      { key: 'door_area', label: 'Площадь дверей', unit: 'м²' },
      { key: 'window_area', label: 'Площадь окон', unit: 'м²' },
      { key: 'skirting_area', label: 'Площадь плинтуса', unit: 'м²' },
    ],
  },
  {
    title: 'Объёмы',
    rows: [
      { key: 'total_volume', label: 'Объём комнаты', unit: 'м³' },
      { key: 'floor_screed_volume', label: 'Объём стяжки пола', unit: 'м³' },
    ],
  },
  {
    title: 'Периметр и длины',
    rows: [
      { key: 'perimeter', label: 'Периметр', unit: 'м' },
      { key: 'skirting_length', label: 'Длина плинтуса', unit: 'м' },
    ],
  },
  {
    title: 'Отделка',
    rows: [
      { key: 'paint_area_net', label: 'Площадь под покраску', unit: 'м²' },
      { key: 'wallpaper_area_net', label: 'Площадь под обои', unit: 'м²' },
      { key: 'wall_tile_area', label: 'Площадь под плитку (пояс)', unit: 'м²' },
    ],
  },
];

// ── Helpers ───────────────────────────────────────────────────────────────────

function field(
  label: string,
  value: string,
  onChange: (v: string) => void,
  opts?: { type?: string; min?: string; step?: string; required?: boolean },
) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: '4px', flex: 1, minWidth: '140px' }}>
      <span style={{ fontSize: '12px', color: '#64748b', fontWeight: 500 }}>{label}</span>
      <input
        type={opts?.type ?? 'number'}
        value={value}
        onChange={e => onChange(e.target.value)}
        min={opts?.min ?? '0'}
        step={opts?.step ?? '0.01'}
        required={opts?.required}
        style={{
          padding: '8px 10px',
          border: '1px solid #e2e8f0',
          borderRadius: '7px',
          fontSize: '14px',
          outline: 'none',
          boxSizing: 'border-box',
          width: '100%',
        }}
      />
    </label>
  );
}

function selectField<T extends string>(
  label: string,
  value: T,
  onChange: (v: T) => void,
  options: Array<{ value: T; label: string }>,
) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: '4px', flex: 1, minWidth: '160px' }}>
      <span style={{ fontSize: '12px', color: '#64748b', fontWeight: 500 }}>{label}</span>
      <select
        value={value}
        onChange={e => onChange(e.target.value as T)}
        style={{
          padding: '8px 10px',
          border: '1px solid #e2e8f0',
          borderRadius: '7px',
          fontSize: '14px',
          outline: 'none',
          backgroundColor: '#fff',
          boxSizing: 'border-box',
          width: '100%',
        }}
      >
        {options.map(o => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </label>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

const Calculator: React.FC = () => {
  const [form, setForm] = useState<RoomInput>(DEFAULT);
  const [result, setResult] = useState<RoomResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  function set<K extends keyof RoomInput>(key: K, value: RoomInput[K]) {
    setForm(prev => ({ ...prev, [key]: value }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const payload = {
        length: parseFloat(form.length),
        width: parseFloat(form.width),
        height: parseFloat(form.height),
        door_count: parseInt(form.door_count),
        door_width: parseFloat(form.door_width),
        door_height: parseFloat(form.door_height),
        window_count: parseInt(form.window_count),
        window_width: parseFloat(form.window_width),
        window_height: parseFloat(form.window_height),
        extra_opening_area: parseFloat(form.extra_opening_area),
        ceiling_type: form.ceiling_type,
        slope_angle: parseFloat(form.slope_angle),
        cornice_width: parseFloat(form.cornice_width),
        floor_type: form.floor_type,
        floor_screed_thickness: parseFloat(form.floor_screed_thickness),
        skirting_height: parseFloat(form.skirting_height),
        extra_wall_area: parseFloat(form.extra_wall_area),
        tile_height: parseFloat(form.tile_height),
      };
      const resp = await apiClient.post<RoomResult>('/calculator/room', payload);
      setResult(resp.data);
      setTimeout(() => {
        document.getElementById('calc-results')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }, 50);
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? 'Ошибка при расчёте');
    } finally {
      setLoading(false);
    }
  }

  // ── Section header helper ─────────────────────────────────────────────────

  function sectionTitle(title: string) {
    return (
      <div style={{ fontSize: '13px', fontWeight: 700, color: '#2563eb', marginBottom: '10px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
        {title}
      </div>
    );
  }

  function formCard(title: string, children: React.ReactNode) {
    return (
      <div style={{ backgroundColor: '#fff', border: '1px solid #e2e8f0', borderRadius: '10px', padding: '16px 20px', marginBottom: '12px' }}>
        {sectionTitle(title)}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px' }}>
          {children}
        </div>
      </div>
    );
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <Layout>
      <div style={{ maxWidth: '860px', margin: '0 auto' }}>
        <h1 style={{ fontSize: '22px', fontWeight: 700, color: '#1e293b', marginBottom: '4px' }}>
          Строительный калькулятор
        </h1>
        <p style={{ fontSize: '13px', color: '#94a3b8', marginBottom: '24px', marginTop: 0 }}>
          Расчёт площадей, объёмов и материалов для отделки помещения
        </p>

        <form onSubmit={handleSubmit}>

          {/* Gabarity */}
          {formCard('Габариты комнаты', <>
            {field('Длина, м', form.length, v => set('length', v), { required: true, min: '0.1' })}
            {field('Ширина, м', form.width, v => set('width', v), { required: true, min: '0.1' })}
            {field('Высота, м', form.height, v => set('height', v), { required: true, min: '0.1' })}
          </>)}

          {/* Doors */}
          {formCard('Двери', <>
            {field('Количество', form.door_count, v => set('door_count', v), { step: '1', min: '0' })}
            {field('Ширина, м', form.door_width, v => set('door_width', v))}
            {field('Высота, м', form.door_height, v => set('door_height', v))}
          </>)}

          {/* Windows */}
          {formCard('Окна', <>
            {field('Количество', form.window_count, v => set('window_count', v), { step: '1', min: '0' })}
            {field('Ширина, м', form.window_width, v => set('window_width', v))}
            {field('Высота, м', form.window_height, v => set('window_height', v))}
          </>)}

          {/* Additional */}
          <div style={{ backgroundColor: '#fff', border: '1px solid #e2e8f0', borderRadius: '10px', padding: '16px 20px', marginBottom: '12px' }}>
            {sectionTitle('Дополнительно')}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px' }}>
              {field('Доп. проёмы, м²', form.extra_opening_area, v => set('extra_opening_area', v))}
              {field('Доп. площадь стен, м²', form.extra_wall_area, v => set('extra_wall_area', v))}
              {field('Высота плиточного пояса, м', form.tile_height, v => set('tile_height', v))}
            </div>

            <div style={{ marginTop: '14px', borderTop: '1px solid #f1f5f9', paddingTop: '14px' }}>
              <div style={{ fontSize: '12px', fontWeight: 600, color: '#64748b', marginBottom: '10px', textTransform: 'uppercase', letterSpacing: '0.3px' }}>Потолок</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px' }}>
                {selectField<CeilingType>('Тип потолка', form.ceiling_type, v => set('ceiling_type', v), [
                  { value: 'flat', label: 'Плоский (flat)' },
                  { value: 'cornice', label: 'С карнизом (cornice)' },
                  { value: 'slope', label: 'Наклонный (slope)' },
                ])}
                {form.ceiling_type === 'slope' &&
                  field('Угол наклона, °', form.slope_angle, v => set('slope_angle', v), { min: '0', step: '0.1' })}
                {form.ceiling_type === 'cornice' &&
                  field('Ширина карниза, м', form.cornice_width, v => set('cornice_width', v))}
              </div>
            </div>

            <div style={{ marginTop: '14px', borderTop: '1px solid #f1f5f9', paddingTop: '14px' }}>
              <div style={{ fontSize: '12px', fontWeight: 600, color: '#64748b', marginBottom: '10px', textTransform: 'uppercase', letterSpacing: '0.3px' }}>Пол и плинтус</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px' }}>
                {selectField<FloorType>('Тип пола', form.floor_type, v => set('floor_type', v), [
                  { value: 'flat', label: 'Ровный (flat)' },
                  { value: 'leveled', label: 'С выравниванием (leveled)' },
                ])}
                {field('Толщина стяжки, м', form.floor_screed_thickness, v => set('floor_screed_thickness', v), { step: '0.001', min: '0' })}
                {field('Высота плинтуса, м', form.skirting_height, v => set('skirting_height', v), { step: '0.01', min: '0' })}
              </div>
            </div>
          </div>

          {error && (
            <div style={{ padding: '10px 14px', backgroundColor: '#fef2f2', color: '#dc2626', borderRadius: '8px', fontSize: '13px', marginBottom: '12px' }}>
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            style={{
              width: '100%',
              padding: '12px',
              backgroundColor: loading ? '#93c5fd' : '#2563eb',
              color: '#fff',
              border: 'none',
              borderRadius: '8px',
              cursor: loading ? 'not-allowed' : 'pointer',
              fontSize: '15px',
              fontWeight: 700,
              marginBottom: '32px',
            }}
          >
            {loading ? 'Расчёт...' : 'Рассчитать'}
          </button>
        </form>

        {/* Results */}
        {result && (
          <div id="calc-results">
            <h2 style={{ fontSize: '18px', fontWeight: 700, color: '#1e293b', marginBottom: '16px' }}>
              Результаты расчёта
            </h2>

            {RESULT_GROUPS.map(group => (
              <div
                key={group.title}
                style={{ backgroundColor: '#fff', border: '1px solid #e2e8f0', borderRadius: '10px', marginBottom: '12px', overflow: 'hidden' }}
              >
                <div style={{ padding: '10px 16px', backgroundColor: '#f8fafc', borderBottom: '1px solid #e2e8f0', fontSize: '12px', fontWeight: 700, color: '#2563eb', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                  {group.title}
                </div>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <tbody>
                    {group.rows.map((row, idx) => {
                      const val = result[row.key];
                      const isZero = val === 0;
                      return (
                        <tr
                          key={row.key}
                          style={{ backgroundColor: idx % 2 === 0 ? '#fff' : '#f8fafc' }}
                        >
                          <td style={{ padding: '9px 16px', fontSize: '13px', color: isZero ? '#94a3b8' : '#334155', borderBottom: '1px solid #f1f5f9' }}>
                            {row.label}
                          </td>
                          <td style={{ padding: '9px 16px', fontSize: '14px', fontWeight: 600, color: isZero ? '#cbd5e1' : '#1e293b', textAlign: 'right', whiteSpace: 'nowrap', borderBottom: '1px solid #f1f5f9' }}>
                            {val.toLocaleString('ru-RU', { minimumFractionDigits: 0, maximumFractionDigits: 3 })} {row.unit}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ))}
          </div>
        )}
      </div>
    </Layout>
  );
};

export default Calculator;
