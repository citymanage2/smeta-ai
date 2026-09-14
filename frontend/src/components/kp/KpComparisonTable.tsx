import React, { useState } from 'react';
import { Check, FileText, Pencil, RotateCcw, Trash2 } from 'lucide-react';

import { kpOfferDownloadUrl } from '../../api/kpRequests';
import { formatDecimal, formatMoney } from '../../utils/formatNumber';
import type {
  KpCell, KpItemDetail, KpOffer, KpPriceBody, KpRequestDetail,
} from '../../types/kp';

/**
 * Сравнительная таблица «позиция × КП»
 * (план plans/2026-09-14-zapros-kp.md, фаза 5, критерии 18–20).
 *
 * Таблица ничего не считает: приведённую цену (без НДС, за единицу позиции),
 * минимум и итоговую цену отдаёт сервер (`services/kp_pricing`) — одно место
 * приведения на всю систему. Здесь только показ и команды:
 *
 * * минимальная приведённая цена выделена зелёным, выбранное КП — рамкой;
 * * черновик ИИ подсвечен жёлтым, пока человек не подтвердит или не исправит;
 * * «включает материалы» помечено в ячейке;
 * * несводимая единица — причина в ячейке, выбрать такое КП нельзя.
 *
 * ИИ-разбор файла (фаза 6): состояние разбора и ошибка — в заголовке колонки КП,
 * «Разобрать заново» — сотруднику роли. Догадки ИИ о НДС и «включает материалы»
 * условия КП не меняют: показываются подсказкой, только если расходятся с ними.
 *
 * Правка цен и КП — только сотруднику роли, пока запрос в работе
 * (`permissions.can_edit_offers`); выбор КП — по `can_select_offer`, у продаж и
 * после завершения.
 */

interface Props {
  request: KpRequestDetail;
  busy?: boolean;
  onSetPrice: (offerId: string, itemId: string, body: KpPriceBody) => Promise<unknown>;
  onConfirm: (offerId: string, itemId: string) => Promise<unknown>;
  onConfirmAll: (offerId: string) => Promise<unknown>;
  onDeletePrice: (offerId: string, itemId: string) => Promise<unknown>;
  onSelect: (itemId: string, offerId: string | null) => Promise<unknown>;
  onEditOffer: (offer: KpOffer) => void;
  onDeleteOffer: (offer: KpOffer) => Promise<unknown>;
  /** «Разобрать заново» — поставить ИИ-разбор файла КП в очередь. */
  onReparse?: (offer: KpOffer) => Promise<unknown>;
}

const th: React.CSSProperties = {
  position: 'sticky', top: 0, background: '#f8fafc', borderBottom: '1px solid #e2e8f0',
  padding: '8px 10px', textAlign: 'left', fontSize: 12, fontWeight: 600, color: '#475569',
  verticalAlign: 'top',
};
const td: React.CSSProperties = {
  borderBottom: '1px solid #f1f5f9', padding: '8px 10px', fontSize: 13, color: '#334155',
  verticalAlign: 'top',
};
const tiny: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 3, height: 24, padding: '0 8px',
  borderRadius: 7, border: '1px solid #e2e8f0', background: '#fff', color: '#475569',
  fontSize: 12, fontWeight: 500, cursor: 'pointer', whiteSpace: 'nowrap',
};
const tag = (bg: string, fg: string): React.CSSProperties => ({
  display: 'inline-block', fontSize: 11, fontWeight: 600, borderRadius: 12,
  padding: '0 8px', background: bg, color: fg, whiteSpace: 'nowrap',
});

export function offerTitle(offer: KpOffer): string {
  return (offer.supplier_name ?? '').trim() || offer.file_name || 'КП без названия';
}

export function vatLabel(offer: KpOffer): string {
  if (offer.vat_mode === 'without_vat') return 'без НДС';
  return `с НДС ${offer.vat_rate !== null ? formatDecimal(offer.vat_rate) : '22'} %`;
}

function formatDate(value: string | null): string {
  if (!value) return '';
  const [y, m, d] = value.slice(0, 10).split('-');
  return y && m && d ? `${d}.${m}.${y}` : value;
}

/** Строка состояния ИИ-разбора; null — разбора нет (КП без файла). */
export function parseStatusText(offer: KpOffer): string | null {
  switch (offer.parse_status) {
    case 'queued': return 'Разбор ИИ: в очереди';
    case 'processing': return 'ИИ разбирает файл…';
    case 'parsed': {
      const found = offer.parse_hints?.prices_found;
      return typeof found === 'number' ? `Разобрано ИИ: цен — ${found}` : 'Разобрано ИИ';
    }
    case 'failed': return 'Разбор ИИ не удался';
    default: return null;
  }
}

/**
 * Подсказки разбора, которые расходятся с условиями КП. Совпала догадка — молчим:
 * подтверждать то, что человек и так выбрал, незачем.
 */
export function parseHintNotes(offer: KpOffer, isWork: boolean): string[] {
  const hints = offer.parse_hints;
  if (!hints) return [];
  const notes: string[] = [];
  if (hints.vat_mode) {
    const rate = hints.vat_mode === 'with_vat' && typeof hints.vat_rate === 'number' ? hints.vat_rate : null;
    const modeDiffers = hints.vat_mode !== offer.vat_mode;
    const rateDiffers = !modeDiffers && rate !== null && rate !== (offer.vat_rate ?? 22);
    if (modeDiffers || rateDiffers) {
      const label = hints.vat_mode === 'without_vat'
        ? 'без НДС'
        : `с НДС${rate !== null ? ` ${formatDecimal(rate)} %` : ''}`;
      notes.push(`По мнению ИИ, в КП цены ${label} — проверьте условия`);
    }
  }
  if (isWork && typeof hints.includes_materials === 'boolean' && hints.includes_materials !== offer.includes_materials) {
    notes.push(hints.includes_materials
      ? 'По мнению ИИ, цены включают материалы — проверьте отметку'
      : 'По мнению ИИ, цены без материалов — проверьте отметку');
  }
  return notes;
}

/** «1 250,5» → 1250.5; мусор — null. */
export function parsePrice(text: string): number | null {
  const cleaned = text.replace(/[\s\u00a0\u202f]/g, '').replace(',', '.');
  if (!cleaned) return null;
  const value = Number(cleaned);
  return Number.isFinite(value) && value > 0 ? value : null;
}

function money(value: number, unit: string | null): string {
  return `${formatMoney(value)} ₽${unit ? ` / ${unit}` : ''}`;
}

/** Отметка «включает материалы» у цены: '' — как у КП. */
type OwnIncludes = '' | 'yes' | 'no';

function PriceEditor({
  item, offer, cellData, isWork, busy, onSave, onDelete, onCancel,
}: {
  item: KpItemDetail;
  offer: KpOffer;
  cellData: KpCell;
  isWork: boolean;
  busy: boolean;
  onSave: (body: KpPriceBody) => void;
  onDelete: (() => void) | null;
  onCancel: () => void;
}) {
  const [price, setPrice] = useState(cellData.price !== null ? String(cellData.price).replace('.', ',') : '');
  const [unit, setUnit] = useState(cellData.price !== null ? (cellData.unit ?? '') : (item.unit ?? ''));
  // Своя отметка у цены видна, только если она расходится с отметкой КП.
  const [own, setOwn] = useState<OwnIncludes>(
    cellData.price !== null && cellData.includes_materials !== offer.includes_materials
      ? (cellData.includes_materials ? 'yes' : 'no')
      : '',
  );
  const parsed = parsePrice(price);
  const prefix = `kp-price-${item.id}-${offer.id}`;

  return (
    <form
      style={{ display: 'flex', flexDirection: 'column', gap: 6 }}
      onSubmit={(e) => {
        e.preventDefault();
        if (parsed === null || busy) return;
        onSave({
          price: parsed,
          unit: unit.trim() || null,
          includes_materials: isWork && own ? own === 'yes' : null,
        });
      }}
    >
      <label htmlFor={`${prefix}-price`} style={{ fontSize: 11, color: '#64748b' }}>Цена</label>
      <input
        id={`${prefix}-price`}
        autoFocus
        inputMode="decimal"
        value={price}
        onChange={(e) => setPrice(e.target.value)}
        style={{ height: 28, width: 110, padding: '0 6px', borderRadius: 6, border: '1px solid #e2e8f0', fontSize: 13 }}
      />
      <label htmlFor={`${prefix}-unit`} style={{ fontSize: 11, color: '#64748b' }}>Ед. изм. в КП</label>
      <input
        id={`${prefix}-unit`}
        value={unit}
        maxLength={64}
        onChange={(e) => setUnit(e.target.value)}
        style={{ height: 28, width: 110, padding: '0 6px', borderRadius: 6, border: '1px solid #e2e8f0', fontSize: 13 }}
      />
      {isWork && (
        <select
          aria-label="Цена включает материалы"
          value={own}
          onChange={(e) => setOwn(e.target.value as OwnIncludes)}
          style={{ height: 28, borderRadius: 6, border: '1px solid #e2e8f0', fontSize: 12 }}
        >
          <option value="">Материалы — как у КП</option>
          <option value="yes">Включает материалы</option>
          <option value="no">Без материалов</option>
        </select>
      )}
      {price.trim() && parsed === null && (
        <span style={{ fontSize: 11, color: '#b91c1c' }}>Цена — число больше нуля</span>
      )}
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
        <button type="submit" style={{ ...tiny, background: '#2563eb', color: '#fff', border: 'none' }} disabled={busy || parsed === null}>
          Сохранить
        </button>
        <button type="button" style={tiny} disabled={busy} onClick={onCancel}>Отмена</button>
        {onDelete && (
          <button type="button" style={{ ...tiny, color: '#dc2626' }} disabled={busy} onClick={onDelete}>
            Удалить цену
          </button>
        )}
      </div>
    </form>
  );
}

const KpComparisonTable: React.FC<Props> = ({
  request, busy = false, onSetPrice, onConfirm, onConfirmAll, onDeletePrice, onSelect,
  onEditOffer, onDeleteOffer, onReparse,
}) => {
  // Одна открытая ячейка на таблицу: `${itemId}:${offerId}`.
  const [editing, setEditing] = useState<string | null>(null);
  const perms = request.permissions;
  const canEdit = !!perms.can_edit_offers && request.status === 'in_progress';
  const canSelect = !!perms.can_select_offer;
  const isWork = request.category === 'work';
  const offers = request.offers;

  const draftsByOffer = new Map<string, number>();
  for (const item of request.items) {
    for (const c of item.cells) {
      if (c.confirmed === false) draftsByOffer.set(c.offer_id, (draftsByOffer.get(c.offer_id) ?? 0) + 1);
    }
  }

  const renderCell = (item: KpItemDetail, offer: KpOffer) => {
    const itemId = item.id ?? '';
    const key = `${itemId}:${offer.id}`;
    const data: KpCell = item.cells.find((c) => c.offer_id === offer.id) ?? {
      offer_id: offer.id, price: null, unit: null, name_in_offer: null, source: null,
      confidence: null, confirmed: null, includes_materials: offer.includes_materials,
      normalized_price: null, unit_status: null, reason: null,
    };
    const hasPrice = data.price !== null;
    const isMin = hasPrice && item.min_offer_id === offer.id;
    const isSelected = item.selected_offer_id === offer.id;
    const isDraft = hasPrice && data.confirmed === false;

    let background = '#fff';
    if (isDraft) background = '#fffbeb';
    else if (isMin) background = '#f0fdf4';

    return (
      <td
        key={offer.id}
        data-testid={`kp-cell-${itemId}-${offer.id}`}
        data-min={isMin ? 'true' : undefined}
        data-draft={isDraft ? 'true' : undefined}
        data-selected={isSelected ? 'true' : undefined}
        style={{
          ...td, background, minWidth: 170,
          boxShadow: isSelected ? 'inset 0 0 0 2px #2563eb' : undefined,
        }}
      >
        {editing === key && canEdit ? (
          <PriceEditor
            item={item}
            offer={offer}
            cellData={data}
            isWork={isWork}
            busy={busy}
            onCancel={() => setEditing(null)}
            onSave={async (body) => {
              // false — сервер отказал: ячейка остаётся открытой с введённым.
              if ((await onSetPrice(offer.id, itemId, body)) !== false) setEditing(null);
            }}
            onDelete={hasPrice ? async () => {
              if (!window.confirm('Удалить цену этой позиции в КП?')) return;
              if ((await onDeletePrice(offer.id, itemId)) !== false) setEditing(null);
            } : null}
          />
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            {hasPrice ? (
              <>
                <span style={{ fontWeight: 600, color: '#1e293b' }}>{money(data.price as number, data.unit)}</span>
                {data.name_in_offer && (
                  <span style={{ fontSize: 11, color: '#94a3b8' }} title="Наименование в КП">{data.name_in_offer}</span>
                )}
                {data.normalized_price !== null ? (
                  <span style={{ fontSize: 12, color: '#475569' }} title="Без НДС, за единицу позиции">
                    {money(data.normalized_price, item.unit)} без НДС
                  </span>
                ) : data.reason ? (
                  <span style={{ fontSize: 12, color: '#b91c1c' }}>{data.reason}</span>
                ) : null}
              </>
            ) : (
              <span style={{ color: '#cbd5e1' }}>—</span>
            )}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {isMin && <span style={tag('#dcfce7', '#15803d')}>Минимум</span>}
              {isSelected && <span style={tag('#dbeafe', '#1d4ed8')}>Выбрано</span>}
              {isDraft && (
                <span style={tag('#fef3c7', '#b45309')} title={data.confidence ? `Уверенность ИИ: ${data.confidence}` : undefined}>
                  Черновик ИИ
                </span>
              )}
              {hasPrice && isWork && data.includes_materials && (
                <span style={tag('#fae8ff', '#86198f')}>Включает материалы</span>
              )}
            </div>
            {isSelected && data.normalized_price === null && (
              <span style={{ fontSize: 11, color: '#b45309' }}>Цены для сравнения нет — в итог идёт минимум</span>
            )}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 2 }}>
              {canEdit && isDraft && (
                <button type="button" style={tiny} disabled={busy} onClick={() => onConfirm(offer.id, itemId)}>
                  <Check size={11} /> Подтвердить
                </button>
              )}
              {canEdit && (
                <button
                  type="button"
                  style={tiny}
                  disabled={busy}
                  aria-label={hasPrice ? 'Изменить цену' : 'Ввести цену'}
                  onClick={() => setEditing(key)}
                >
                  <Pencil size={11} /> {hasPrice ? 'Изменить' : 'Ввести'}
                </button>
              )}
              {canSelect && isSelected && (
                <button type="button" style={tiny} disabled={busy} onClick={() => onSelect(itemId, null)}>
                  Снять выбор
                </button>
              )}
              {canSelect && !isSelected && data.normalized_price !== null && data.confirmed === true && (
                <button type="button" style={tiny} disabled={busy} onClick={() => onSelect(itemId, offer.id)}>
                  Выбрать
                </button>
              )}
            </div>
          </div>
        )}
      </td>
    );
  };

  return (
    <div style={{ overflowX: 'auto', border: '1px solid #e2e8f0', borderRadius: 12, background: '#fff' }}>
      <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 520 + offers.length * 170 }}>
        <thead>
          <tr>
            <th style={{ ...th, width: 56 }}>№</th>
            <th style={{ ...th, minWidth: 220 }}>Позиция</th>
            <th style={{ ...th, width: 90 }}>Кол-во</th>
            {offers.map((offer) => {
              const drafts = draftsByOffer.get(offer.id) ?? 0;
              return (
                <th key={offer.id} style={{ ...th, minWidth: 170 }} data-testid={`kp-offer-${offer.id}`}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                    <span style={{ fontSize: 13, color: '#1e293b' }}>{offerTitle(offer)}</span>
                    <span style={{ fontWeight: 400, color: '#64748b' }}>
                      {[formatDate(offer.offer_date), vatLabel(offer)].filter(Boolean).join(' · ')}
                    </span>
                    {isWork && offer.includes_materials && (
                      <span style={tag('#fae8ff', '#86198f')}>Цены включают материалы</span>
                    )}
                    {offer.has_file && (
                      <a
                        href={kpOfferDownloadUrl(offer.id)}
                        target="_blank"
                        rel="noreferrer"
                        style={{ display: 'inline-flex', alignItems: 'center', gap: 3, color: '#2563eb', fontWeight: 400 }}
                      >
                        <FileText size={11} /> {offer.file_name ?? 'Файл КП'}
                      </a>
                    )}
                    {parseStatusText(offer) && (
                      <span
                        data-testid={`kp-parse-${offer.id}`}
                        style={{ fontWeight: 400, color: offer.parse_status === 'failed' ? '#b91c1c' : '#64748b' }}
                      >
                        {parseStatusText(offer)}
                      </span>
                    )}
                    {offer.parse_status === 'failed' && offer.parse_error && (
                      <span role="alert" style={{ fontWeight: 400, fontSize: 12, color: '#b91c1c', maxWidth: 260 }}>
                        {offer.parse_error}
                      </span>
                    )}
                    {parseHintNotes(offer, isWork).map((note) => (
                      <span key={note} style={{ fontWeight: 400, fontSize: 12, color: '#b45309', maxWidth: 260 }}>
                        {note}
                      </span>
                    ))}
                    {offer.created_by_name && (
                      <span style={{ fontWeight: 400, color: '#94a3b8' }}>Загрузил: {offer.created_by_name}</span>
                    )}
                    {canEdit && (
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                        {drafts > 0 && (
                          <button type="button" style={tiny} disabled={busy} onClick={() => onConfirmAll(offer.id)}>
                            <Check size={11} /> Подтвердить все по КП ({drafts})
                          </button>
                        )}
                        {onReparse && offer.has_file
                          && (offer.parse_status === 'parsed' || offer.parse_status === 'failed' || offer.parse_status === null) && (
                          <button type="button" style={tiny} disabled={busy} onClick={() => onReparse(offer)}>
                            <RotateCcw size={11} /> Разобрать заново
                          </button>
                        )}
                        <button type="button" style={tiny} disabled={busy} onClick={() => onEditOffer(offer)}>
                          <Pencil size={11} /> Условия
                        </button>
                        <button
                          type="button"
                          style={{ ...tiny, color: '#dc2626' }}
                          disabled={busy}
                          aria-label="Удалить КП"
                          onClick={() => onDeleteOffer(offer)}
                        >
                          <Trash2 size={11} />
                        </button>
                      </div>
                    )}
                  </div>
                </th>
              );
            })}
            <th style={{ ...th, minWidth: 150 }}>Итог</th>
          </tr>
        </thead>
        <tbody>
          {request.items.map((item) => (
            <tr key={item.id ?? item.position}>
              <td style={{ ...td, color: '#94a3b8' }}>{item.source_no ?? ''}</td>
              <td style={td}>
                <div style={{ color: '#1e293b' }}>{item.name}</div>
                {item.sheet && <div style={{ fontSize: 11, color: '#94a3b8' }}>{item.sheet}</div>}
              </td>
              <td style={{ ...td, whiteSpace: 'nowrap' }}>
                {item.qty !== null ? formatDecimal(item.qty) : '—'} {item.unit ?? ''}
              </td>
              {offers.map((offer) => renderCell(item, offer))}
              <td style={td} data-testid={`kp-best-${item.id}`}>
                {item.best ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                    <span style={{ fontWeight: 600, color: '#15803d' }}>{money(item.best.price, item.unit)}</span>
                    <span style={{ fontSize: 12, color: '#64748b' }}>
                      {item.best.supplier_name || 'КП без названия'} · {item.best.selected ? 'выбрано' : 'минимум'}
                    </span>
                    {isWork && item.best.includes_materials && (
                      <span style={tag('#fae8ff', '#86198f')}>Включает материалы</span>
                    )}
                  </div>
                ) : (
                  <span style={{ color: '#cbd5e1' }}>—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {offers.length === 0 && (
        <div style={{ padding: '10px 12px', fontSize: 13, color: '#94a3b8' }}>
          КП ещё не загружены — колонки появятся после загрузки.
        </div>
      )}
    </div>
  );
};

export default KpComparisonTable;
