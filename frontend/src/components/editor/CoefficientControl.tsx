import { useMemo, useState } from 'react';
import { Percent } from 'lucide-react';

import { CoefficientPayload } from '../../api/documents';
import { formatFactor, isActiveCoefficient, rowCoefficient } from '../../utils/estimateCalc';

/**
 * Коэффициент к ценам — обратимая настройка документа.
 *
 * Он не переписывает цены в строках: исходные остаются в документе, а на экран
 * и в файл цены выходят умноженными. Поэтому коэффициент можно снять и увидеть
 * ровно то, что было до него.
 *
 * Отдельные множители на работы и на материалы (решение 4.1) и область
 * применения: весь документ или отмеченные галочками строки (решение 4.3).
 */

interface Props {
  coefficient: unknown;
  selectedKeys: Set<string>;
  disabled?: boolean;
  onApply: (payload: CoefficientPayload | null) => Promise<void> | void;
}

function parseFactor(value: string): number | null {
  const normalized = value.trim().replace(',', '.');
  if (normalized === '') return null;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

export const CoefficientControl: React.FC<Props> = ({
  coefficient, selectedKeys, disabled, onApply,
}) => {
  const active = isActiveCoefficient(coefficient);
  const current = useMemo(() => rowCoefficient(coefficient, null), [coefficient]);

  const [open, setOpen] = useState(false);
  const [work, setWork] = useState(() => formatFactor(current.work));
  const [material, setMaterial] = useState(() => formatFactor(current.material));
  const [onlySelected, setOnlySelected] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const scopeList = useMemo(
    () => (Array.isArray((coefficient as { scope?: unknown })?.scope)
      ? ((coefficient as { scope: string[] }).scope)
      : null),
    [coefficient],
  );

  const handleApply = async () => {
    const workFactor = parseFactor(work);
    const materialFactor = parseFactor(material);
    if (workFactor === null || materialFactor === null) {
      setError('Коэффициент — число больше нуля, например 1,05');
      return;
    }
    if (onlySelected && selectedKeys.size === 0) {
      setError('Отметьте строки галочками или снимите ограничение');
      return;
    }
    setBusy(true);
    setError('');
    try {
      await onApply({
        work: workFactor,
        material: materialFactor,
        scope: onlySelected ? [...selectedKeys] : 'all',
      });
      setOpen(false);
    } catch {
      setError('Не удалось сохранить коэффициент');
    } finally {
      setBusy(false);
    }
  };

  const handleClear = async () => {
    setBusy(true);
    try {
      await onApply(null);
      setWork('1');
      setMaterial('1');
      setOpen(false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="de-coefficient">
      <div className="de-coefficient-head">
        <button
          className="de-btn"
          onClick={() => {
            // Если строки отмечены галочками — по умолчанию применяем к ним.
            // Иначе человек, отметивший десять позиций, молча поднял бы цену
            // всей смете.
            if (!open) setOnlySelected(selectedKeys.size > 0);
            setOpen((v) => !v);
          }}
          disabled={disabled || busy}
        >
          <Percent size={14} />
          Коэффициент
        </button>

        {active && (
          <span className="de-coefficient-state">
            работы ×{formatFactor(current.work)}, материалы ×{formatFactor(current.material)}
            {scopeList ? ` (строк: ${scopeList.length})` : ' — на весь документ'}
          </span>
        )}
        {active && (
          <button className="de-btn de-btn-ghost" onClick={handleClear} disabled={busy}>
            Снять коэффициент
          </button>
        )}
      </div>

      {open && (
        <div className="de-coefficient-form">
          <label>
            Коэффициент на работы
            <input
              aria-label="Коэффициент на работы"
              value={work}
              onChange={(e) => setWork(e.target.value)}
              inputMode="decimal"
            />
          </label>
          <label>
            Коэффициент на материалы
            <input
              aria-label="Коэффициент на материалы"
              value={material}
              onChange={(e) => setMaterial(e.target.value)}
              inputMode="decimal"
            />
          </label>
          <label className="de-coefficient-scope" htmlFor="de-coefficient-scope-input">
            <input
              id="de-coefficient-scope-input"
              type="checkbox"
              checked={onlySelected}
              onChange={(e) => setOnlySelected(e.target.checked)}
            />
            Только отмеченные строки ({selectedKeys.size})
          </label>

          <button className="de-btn de-btn-primary" onClick={handleApply} disabled={busy}>
            Применить коэффициент
          </button>
          {error && <span className="de-coefficient-error">{error}</span>}
          <span className="de-coefficient-hint">
            Исходные цены сохраняются: коэффициент можно снять в любой момент.
          </span>
        </div>
      )}
    </div>
  );
};

export default CoefficientControl;
