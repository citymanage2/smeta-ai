import apiClient from './client';

// Документ = (карточка сметы, тип документа). Один контракт на все типы;
// чем типы отличаются — описывает row_format и набор разрешённых действий.
export type DocumentKind =
  | 'list' | 'completeness' | 'estimate' | 'optimization'
  // Раздел сводной: строки лежат снимком внутри сводной, версий у него нет.
  | 'summary-section';
export type RowFormat = 'generic' | 'estimate';
export type ReadonlyReason = 'no_permission' | 'task_processing' | 'input_readonly';

export interface DocumentRef {
  cardId: string;
  kind: DocumentKind;
  /** 'input' открывает документ исходного файла заказчика (только чтение). */
  fileSlot?: string;
  /** Номер входного файла, когда их несколько. */
  fileIndex?: number;
  versionId?: string;
}

export interface VersionBrief {
  id: string;
  version_number: number;
  version_label: string;
  version_display_name: string;
  is_rolled_back: boolean;
  created_at: string;
  // Проценты доп. расходов у каждой версии свои — сравнение версий считает
  // итоги по ним, а не по общей ставке проекта.
  overhead_pct: number;
  transport_pct: number;
  contingency_pct: number;
  expenses_overridden: boolean;
}

export interface LockInfo {
  user_id: number | null;
  user_name: string;
  heartbeat_at: string;
}

export interface DocumentMeta {
  card_id: string;
  kind: DocumentKind;
  row_format: RowFormat;
  file_slot: string;
  task_id: string;
  task_type: string;
  task_status: string;
  can_write: boolean;
  readonly_reason: ReadonlyReason | null;
  rev: number;
  active_version_id: string | null;
  versions: VersionBrief[];
  coefficient: Record<string, unknown> | null;
  has_draft: boolean;
  draft_updated_at: string | null;
  lock: LockInfo | null;
  project: { overhead_pct: number; transport_pct: number; name?: string };
  /** Только у раздела сводной: его строки разошлись со сметой. */
  divergence?: SectionDivergence | null;
}

/** Раздел сводной и смета показывают разное — обе стороны в цифрах. */
export interface SectionDivergence {
  section_rows: number;
  estimate_rows: number;
  section_total: number;
  estimate_total: number;
}

export interface DocumentRows {
  version_id: string;
  rev: number;
  rows: unknown[];
  draft_rows: unknown[] | null;
}

export interface ApplyResult {
  version_id: string;
  rev: number;
  rows_count: number;
  changes_count: number;
}

export interface HistoryChange {
  row_number: number;
  row_id: string | null;
  row_name: string;
  field: string;
  previous: unknown;
  new: unknown;
}

export interface HistoryEntry {
  id: string;
  kind: string | null;
  operation_type: string;
  description: string;
  user_id: number | null;
  user_name: string;
  created_at: string;
  changes_count: number;
  changes: HistoryChange[];
}

function base(ref: DocumentRef): string {
  return `/documents/${ref.cardId}/${ref.kind}`;
}

function slotParams(ref: DocumentRef): Record<string, string | number> {
  return {
    ...(ref.fileSlot ? { file_slot: ref.fileSlot } : {}),
    ...(ref.fileIndex !== undefined ? { file_index: ref.fileIndex } : {}),
  };
}

export async function getDocumentMeta(ref: DocumentRef): Promise<DocumentMeta> {
  const res = await apiClient.get<DocumentMeta>(base(ref), { params: slotParams(ref) });
  return res.data;
}

/**
 * Свести разошедшиеся раздел сводной и смету к одной стороне.
 *
 * `section` — верны правки раздела, они уезжают в смету; `estimate` — верна
 * смета, раздел берёт её строки. Прежние строки раздела в обоих случаях уходят
 * в историю.
 */
export async function resolveSectionDivergence(
  cardId: string,
  prefer: 'section' | 'estimate',
): Promise<{ prefer: string; rows_count: number }> {
  const res = await apiClient.post(
    `/documents/${cardId}/summary-section/divergence/resolve`, { prefer },
  );
  return res.data;
}

export async function getDocumentRows(ref: DocumentRef): Promise<DocumentRows> {
  const res = await apiClient.get<DocumentRows>(`${base(ref)}/rows`, {
    params: { ...slotParams(ref), ...(ref.versionId ? { version_id: ref.versionId } : {}) },
  });
  return res.data;
}

export async function saveDraft(
  ref: DocumentRef,
  versionId: string,
  rows: unknown[],
): Promise<void> {
  await apiClient.put(
    `${base(ref)}/draft`,
    { version_id: versionId, rows },
    { params: slotParams(ref) },
  );
}

export async function discardDraft(ref: DocumentRef, versionId: string): Promise<void> {
  await apiClient.delete(`${base(ref)}/draft`, {
    params: { ...slotParams(ref), version_id: versionId },
  });
}

export async function applyDocument(
  ref: DocumentRef,
  versionId: string,
  rev: number,
  rows?: unknown[],
): Promise<ApplyResult> {
  const res = await apiClient.post<ApplyResult>(
    `${base(ref)}/apply`,
    { version_id: versionId, rev, ...(rows ? { rows } : {}) },
    { params: slotParams(ref) },
  );
  return res.data;
}

export interface CoefficientPayload {
  work: number;
  material: number;
  /** 'all' — весь документ; список ключей строк — только отмеченные. */
  scope: 'all' | string[];
}

/** Поставить коэффициент к ценам или снять его (null). */
export async function setDocumentCoefficient(
  ref: DocumentRef,
  payload: CoefficientPayload | null,
): Promise<{ coefficient: CoefficientPayload | null }> {
  const res = await apiClient.put<{ coefficient: CoefficientPayload | null }>(
    `${base(ref)}/coefficient`, payload, { params: slotParams(ref) },
  );
  return res.data;
}

/** Выгрузка-ведомость по документу: строки приходят из предпросмотра. */
export async function exportDocument(
  ref: DocumentRef,
  payload: unknown,
  fileName = 'export.xlsx',
): Promise<void> {
  const res = await apiClient.post(`${base(ref)}/export`, payload, {
    params: slotParams(ref), responseType: 'blob',
  });
  const url = window.URL.createObjectURL(new Blob([res.data]));
  const link = document.createElement('a');
  link.href = url;
  link.setAttribute('download', fileName);
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}

export async function getDocumentHistory(ref: DocumentRef): Promise<HistoryEntry[]> {
  const res = await apiClient.get<HistoryEntry[]>(`${base(ref)}/history`, {
    params: slotParams(ref),
  });
  return res.data;
}

export async function revertDocument(
  ref: DocumentRef,
  entryId: string,
  versionId?: string,
): Promise<ApplyResult> {
  const res = await apiClient.post<ApplyResult>(
    `${base(ref)}/history/${entryId}/revert`,
    null,
    { params: { ...slotParams(ref), ...(versionId ? { version_id: versionId } : {}) } },
  );
  return res.data;
}

export async function sendHeartbeat(ref: DocumentRef): Promise<LockInfo | null> {
  const res = await apiClient.post<{ lock: LockInfo | null }>(
    `${base(ref)}/heartbeat`,
    null,
    { params: slotParams(ref) },
  );
  return res.data.lock;
}

// --- Прайс ------------------------------------------------------------------

export interface PriceListItem {
  kind: 'work' | 'material';
  name: string;
  unit: string | null;
  price: number | null;
}

export interface PriceListSummary {
  added: number;
  updated: number;
  skipped: number;
  /** Почему позиции пропущены: «без цены» → 3. */
  skipped_reasons: Record<string, number>;
}

/**
 * Отправить позиции документа в общий прайс. Работы уходят к псевдо-подрядчику
 * «Из смет», материалы — ценой; сам документ при этом не меняется.
 */
export async function addToPriceList(
  ref: DocumentRef,
  items: PriceListItem[],
): Promise<PriceListSummary> {
  const res = await apiClient.post<PriceListSummary>(
    `${base(ref)}/price-list`,
    { items },
    { params: slotParams(ref) },
  );
  return res.data;
}

// --- Проверка единиц измерения у цен ----------------------------------------

export interface PriceUnitsCheckResult {
  /** Сколько строк с ценой проверено. */
  checked: number;
  /** В скольких единица цены разошлась с единицей позиции. */
  flagged: number;
  version_id: string;
  rev: number;
}

/**
 * Пройти по смете и пометить строки, где цена похожа на цену за другую единицу
 * измерения. Нужна сметам, посчитанным до того, как подбор цены начал сверять
 * единицу: цена за тонну могла встать в строку с килограммами.
 *
 * Цены не меняются — проверка показывает, где смотреть, решает человек.
 */
export async function checkPriceUnits(
  ref: DocumentRef,
  versionId: string,
  rev: number,
): Promise<PriceUnitsCheckResult> {
  const res = await apiClient.post<PriceUnitsCheckResult>(
    `${base(ref)}/price-units-check`,
    { version_id: versionId, rev },
    { params: slotParams(ref) },
  );
  return res.data;
}

// --- Поиск аналогов через ИИ -------------------------------------------------

export interface AnalogVariant {
  name: string;
  unit: string;
  price: number;
  /** Выгода в рублях по объёму позиции — считает сервер. */
  delta: number;
  reason: string;
  source: string;
}

export interface AnalogResult {
  row_id: string;
  name: string;
  unit: string;
  price: number;
  variants: AnalogVariant[];
}

export type AnalogStatus = 'queued' | 'running' | 'done' | 'failed' | 'cancelled';

export interface AnalogsState {
  run_id: string | null;
  status: AnalogStatus | null;
  processed: number;
  total: number;
  results: AnalogResult[];
  error: string | null;
  created_at: string | null;
}

export interface AnalogRowIn {
  row_id: string;
  name: string;
  unit: string | null;
  qty: number | null;
  price: number | null;
  kind: 'work' | 'material';
}

export interface AnalogsStartResult {
  run_id: string;
  status: AnalogStatus;
  total: number;
  estimate: { positions: number; searches: number; minutes: number };
}

/** Запустить фоновый поиск аналогов. Документ при этом не меняется. */
export async function startAnalogs(
  ref: DocumentRef,
  rows: AnalogRowIn[],
  versionId?: string,
): Promise<AnalogsStartResult> {
  const res = await apiClient.post<AnalogsStartResult>(
    `${base(ref)}/analogs`,
    { rows, version_id: versionId ?? null },
    { params: slotParams(ref) },
  );
  return res.data;
}

export async function getAnalogsState(ref: DocumentRef): Promise<AnalogsState> {
  const res = await apiClient.get<AnalogsState>(`${base(ref)}/analogs`, {
    params: slotParams(ref),
  });
  return res.data;
}

export async function cancelAnalogs(ref: DocumentRef): Promise<AnalogsState> {
  const res = await apiClient.post<AnalogsState>(`${base(ref)}/analogs/cancel`, null, {
    params: slotParams(ref),
  });
  return res.data;
}

/** Задача → документ. Для старых ссылок вида /tasks/{id}, где карточка неизвестна. */
export interface DocumentLocation {
  project_id: string;
  card_id: string;
  kind: DocumentKind;
}

export async function locateDocumentByTask(taskId: string): Promise<DocumentLocation> {
  const res = await apiClient.get<DocumentLocation>(`/documents/by-task/${taskId}`);
  return res.data;
}

/** Тип задачи → тип документа. Точка входа в редактор знает тип задачи. */
export function kindFromTaskType(taskType: string): DocumentKind | null {
  switch (taskType) {
    case 'LIST_FROM_GRAND':
    case 'LIST_FROM_PROJECT':
      return 'list';
    case 'CHECK_LIST_COMPLETENESS':
    case 'CHECK_PROJECT_COMPLETENESS':
      return 'completeness';
    case 'ESTIMATE_FROM_LIST':
      return 'estimate';
    case 'ESTIMATE_OPTIMIZATION':
      return 'optimization';
    default:
      return null;
  }
}
