/**
 * Предложение запомнить цену: «система посчитала X — вы поставили Y».
 *
 * План: plans/2026-09-10-sverka-i-obuchenie-na-pravkah.md, Фаза 7.
 */

export interface PriceSuggestion {
  name_key: string;
  display_name: string;
  /** work | material — из того, какое поле цены правили. */
  row_type: string;
  unit: string;
  /** Медиана правок человека, а не последняя из них. */
  suggested_price: number;
  min_price: number;
  max_price: number;
  /** Что считала система до правок. null — сравнить не с чем. */
  system_price: number | null;
  /** Сколько раз правили и в скольких сметах. */
  touches: number;
  tasks: number;
  /** Откуда система брала цену: прайс, кеш прошлых задач, веб-поиск. */
  sources: string[];
  /** Цены внутри позиции разошлись больше чем в полтора раза. */
  prices_disagree: boolean;
  user_name: string | null;
  last_at: string | null;
  /** accepted | rejected — если решение уже принято. */
  decision: string | null;
}

export interface PriceDecisionPayload {
  name: string;
  row_type: string;
  unit: string;
  price?: number | null;
}
