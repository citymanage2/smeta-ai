// Журнал корректировок: «система посчитала X — человек поставил Y».
// План: plans/2026-08-07-obuchenie-na-korrektirovkah.md, Фаза 3.

export interface FieldStat {
  field: string;
  document_kind: string;
  count: number;
}

export interface PositionStat {
  row_name: string;
  document_kind: string;
  count: number;
}

export interface KindStat {
  document_kind: string;
  count: number;
}

export interface CorrectionsStats {
  total: number;
  // Первые касания ячеек — только они говорят об ошибке системы.
  first_touch: number;
  price_edits: number;
  rows_added: number;
  rows_removed: number;
  top_fields: FieldStat[];
  top_positions: PositionStat[];
  by_kind: KindStat[];
}

export interface Correction {
  id: string;
  task_id: string;
  document_kind: string;
  row_name: string;
  row_type: string | null;
  unit: string | null;
  field: string;
  previous_value: string | null;
  new_value: string | null;
  is_first_touch: boolean;
  price_source: string | null;
  user_name: string | null;
  created_at: string;
}
