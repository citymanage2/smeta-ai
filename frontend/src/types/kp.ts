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
  /** Подтверждённые цены неудалённых КП: 0 — ставить в оптимизацию нечего. */
  confirmed_prices_count: number;
  created_at: string;
  updated_at: string | null;
}

export interface KpPermissions {
  can_work: boolean;
  can_manage: boolean;
  can_edit_files: boolean;
  /** Загрузить/править/удалить КП и цены (сотрудник роли, до завершения). */
  can_edit_offers?: boolean;
  /** Завершить запрос (сотрудник роли, новый или в работе). */
  can_complete?: boolean;
  /** Отметить КП выбранным (производство — в работе; продажи — и после завершения). */
  can_select_offer?: boolean;
}

export type KpVatMode = 'with_vat' | 'without_vat';

export type KpParseStatus = 'queued' | 'processing' | 'parsed' | 'failed';

/**
 * Подсказки ИИ-разбора. Условия КП (НДС, ставка, «включает материалы») задаёт
 * человек — догадка ИИ о них только показывается рядом.
 */
export interface KpParseHints {
  prices_found?: number;
  dropped_unknown?: number;
  vat_mode?: KpVatMode;
  vat_rate?: number;
  includes_materials?: boolean;
}

/** КП к запросу — условия и файл. Зеркало `KpOfferOut`. */
export interface KpOffer {
  id: string;
  supplier_name: string;
  /** ГГГГ-ММ-ДД */
  offer_date: string | null;
  vat_mode: KpVatMode;
  vat_rate: number | null;
  includes_materials: boolean;
  file_name: string | null;
  mime_type: string | null;
  size_bytes: number | null;
  has_file: boolean;
  /** ИИ-разбор файла (фаза 6): queued | processing | parsed | failed; null — файла нет. */
  parse_status: KpParseStatus | null;
  parse_error: string | null;
  parse_started_at?: string | null;
  parse_hints?: KpParseHints | null;
  created_by: number | null;
  created_by_name: string | null;
  created_at: string;
}

/** Ячейка «позиция × КП»: цена в единице КП и приведённая (без НДС, за ед. позиции). */
export interface KpCell {
  offer_id: string;
  item_id?: string | null;
  price: number | null;
  unit: string | null;
  name_in_offer: string | null;
  source: 'ai' | 'manual' | string | null;
  confidence: string | null;
  /** null — цены в ячейке нет; false — черновик. */
  confirmed: boolean | null;
  includes_materials: boolean;
  normalized_price: number | null;
  unit_status: string | null;
  /** Почему приведённой цены нет (единица не сводится). */
  reason: string | null;
}

/** Итоговая цена позиции: выбранное КП, иначе минимум подтверждённых. */
export interface KpBest {
  offer_id: string;
  supplier_name: string;
  offer_date: string | null;
  price: number;
  includes_materials: boolean;
  selected: boolean;
  offers_count: number;
}

export interface KpItemDetail extends KpItem {
  cells: KpCell[];
  min_offer_id: string | null;
  best: KpBest | null;
}

/** Сводка записи в прайс (фаза 7). */
export interface KpPricelistSummary {
  added?: number;
  updated?: number;
  skipped?: Record<string, number>;
  [key: string]: unknown;
}

export interface KpRequestDetail extends KpRequestBrief {
  source_task_id: string | null;
  source_version_id: string | null;
  report: string | null;
  pricelist_status: string | null;
  pricelist_summary: KpPricelistSummary | null;
  pricelist_error: string | null;
  pricelist_written_at: string | null;
  applied_version_id: string | null;
  items: KpItemDetail[];
  files: KpFile[];
  offers: KpOffer[];
  permissions: KpPermissions;
}

/** Условия КП из формы загрузки/правки. */
export interface KpOfferForm {
  supplier_name: string;
  /** ГГГГ-ММ-ДД или пусто */
  offer_date: string;
  /** null — человек ещё не выбрал: молча «без НДС» завысило бы цены. */
  vat_mode: KpVatMode | null;
  vat_rate: string;
  includes_materials: boolean;
}

export interface KpPriceBody {
  price: number;
  unit: string | null;
  /** null — как у КП */
  includes_materials: boolean | null;
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

/** Файл КП — те же типы, что принимает сервер (`kp_offers.OFFER_FILE_TYPES`). */
export const KP_OFFER_EXTENSIONS: readonly string[] = [
  '.pdf', '.xlsx', '.xls', '.jpg', '.jpeg', '.png',
];
export const KP_DEFAULT_VAT_RATE = 22;

// --- Цены из КП в оптимизацию (фаза 8) ----------------------------------------
// Контракт — `backend/app/schemas/kp_request.py` (KpApply*).

/** Пометка строки оптимизации «цена из КП» — поле строки `kp_ref`. */
export interface KpRef {
  request_id?: string;
  offer_id?: string;
  supplier?: string | null;
  offer_date?: string | null;
  offers_count?: number;
  includes_materials?: boolean;
  /**
   * Какую цену строки поставило КП и какой она была при применении (исходная,
   * без коэффициента). Пометка действует, только пока цена строки в `field`
   * равна `price`: правка цены снимает её.
   */
  field?: 'price_work' | 'price_material';
  price?: number;
}

export interface KpApplyRow {
  row_id: string;
  name: string | null;
  unit: string | null;
  sheet: string | null;
  source_no: string | null;
  type: string | null;
  field: string;
  old_price: number | string | null;
  new_price: number;
  request_id: string;
  item_id: string;
  offer_id: string;
  supplier: string | null;
  offer_date: string | null;
  offers_count: number;
  includes_materials: boolean;
  match: string;
}

export interface KpApplyCandidate {
  row_id: string;
  name: string | null;
  unit: string | null;
  sheet: string | null;
  source_no: string | null;
  qty: number | string | null;
  old_price: number | string | null;
  new_price: number;
}

export interface KpApplyItem {
  request_id: string;
  item_id: string;
  item_type: string;
  name: string;
  unit: string | null;
  sheet: string | null;
  source_no: string | null;
  price: number;
  supplier: string | null;
  offer_date: string | null;
  offers_count: number;
  includes_materials: boolean;
  candidates: KpApplyCandidate[];
}

export interface KpApplySkipped {
  row_id: string;
  item_id: string;
  name: string | null;
  reason: string;
}

export interface KpApplyPreview {
  version_id: string;
  rev: number;
  preview_hash: string;
  rows: KpApplyRow[];
  ambiguous: KpApplyItem[];
  not_found: KpApplyItem[];
  skipped: KpApplySkipped[];
  no_price_count: number;
  includes_materials_count: number;
}

export interface KpApplyBody {
  card_id: string;
  version_id: string;
  client_rev: number;
  preview_hash: string;
  /** Только для «Неоднозначно»: item_id → строка / строки / null (пропустить). */
  choices: Record<string, string | string[] | null>;
}

export interface KpApplyResult {
  version_id: string;
  version_number: number;
  source_version_id: string;
  applied_rows: number;
  changes_count: number;
  request_ids: string[];
}
