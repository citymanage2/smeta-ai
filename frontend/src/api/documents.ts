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
  project: { overhead_pct: number; transport_pct: number };
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
