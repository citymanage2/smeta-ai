// Запрос КП у отдела производства работ — типы HTTP-контракта.
//
// Зеркало `backend/app/schemas/kp_request.py`. План:
// plans/2026-09-14-zapros-kp.md, фазы 2–3. Ключ S3 в контракт не входит:
// файл скачивается только через роутер с проверкой роли.

export type KpCategory = 'material' | 'work';
export type KpStatus = 'new' | 'in_progress' | 'done' | 'cancelled';
/** Стадии, с которых ставится запрос. */
export type KpSourceKind = 'list' | 'completeness' | 'estimate' | 'optimization';

export const KP_SOURCE_KINDS: readonly KpSourceKind[] = [
  'list', 'completeness', 'estimate', 'optimization',
];

/** Позиция запроса. В предпросмотре — ещё не сохранённая, без id. */
export interface KpItem {
  id: string | null;
  position: number;
  item_type: KpCategory | null;
  name: string;
  unit: string | null;
  qty: number | null;
  sheet: string | null;
  source_no: string | null;
  /** Строки документа, свёрнутые в позицию. */
  source_row_ids: string[];
  selected_offer_id: string | null;
}

export interface KpPreviewGroup {
  category: KpCategory | 'unknown';
  target_role?: string | null;
  /** Активных сотрудников роли; 0 — группу отправить нельзя. */
  employees?: number | null;
  items: KpItem[];
}

export interface KpPreview {
  version_id: string;
  groups: {
    material: KpPreviewGroup;
    work: KpPreviewGroup;
    unknown: KpPreviewGroup;
  };
  /** Разделы и строки без наименования — в запрос не попадают. */
  skipped: number;
  /** Отмеченные строки, которых нет в сохранённом документе. */
  missing_row_ids: string[];
}

export interface KpPreviewBody {
  card_id: string;
  kind: KpSourceKind;
  version_id: string | null;
  row_ids: string[];
}

export interface KpCreatePayload {
  card_id: string;
  kind: KpSourceKind;
  version_id: string | null;
  author_comment: string | null;
  groups: Array<{ category: KpCategory; row_ids: string[] }>;
}

export interface KpFile {
  id: string;
  file_name: string;
  mime_type: string;
  size_bytes: number;
  uploaded_by: number | null;
  uploaded_by_name: string | null;
  created_at: string;
}

export interface KpRequestBrief {
  id: string;
  project_id: string;
  project_name: string | null;
  card_id: string;
  card_name: string | null;
  source_kind: string;
  category: KpCategory;
  target_role: string;
  status: KpStatus;
  author_id: number | null;
  author_name: string | null;
  author_comment: string | null;
  taken_by_id: number | null;
  taken_by_name: string | null;
  taken_at: string | null;
  completed_by_id: number | null;
  completed_by_name: string | null;
  completed_at: string | null;
  applied_at: string | null;
  items_count: number;
  files_count: number;
  created_at: string;
  updated_at: string | null;
}

export interface KpPermissions {
  can_work: boolean;
  can_manage: boolean;
  can_edit_files: boolean;
}

export interface KpRequestDetail extends KpRequestBrief {
  source_task_id: string | null;
  source_version_id: string | null;
  report: string | null;
  pricelist_status: string | null;
  pricelist_summary: Record<string, unknown> | null;
  pricelist_error: string | null;
  pricelist_written_at: string | null;
  applied_version_id: string | null;
  items: KpItem[];
  files: KpFile[];
  permissions: KpPermissions;
}

export interface KpCounters {
  new: number;
  done_not_applied: Record<string, number>;
}

// Подписи — одни на весь интерфейс запросов КП. `Record` не даст забыть
// подпись, если появится новый статус.
export const KP_STATUS_LABELS: Record<KpStatus, string> = {
  new: 'Новый',
  in_progress: 'В работе',
  done: 'Завершён',
  cancelled: 'Отменён',
};

export const KP_CATEGORY_LABELS: Record<KpCategory, string> = {
  material: 'Материалы',
  work: 'Работы',
};

/** Кому уходит группа: «Материалы → отдел снабжения». */
export const KP_DEPARTMENT_LABELS: Record<KpCategory, string> = {
  material: 'отдел снабжения',
  work: 'подрядчики',
};

/** Вложения автора — те же ограничения, что проверяет сервер. */
export const KP_ATTACHMENT_EXTENSIONS: readonly string[] = [
  '.pdf', '.xlsx', '.xls', '.doc', '.docx', '.jpg', '.jpeg', '.png',
];
export const KP_MAX_FILE_MB = 50;
export const KP_MAX_FILES = 10;
