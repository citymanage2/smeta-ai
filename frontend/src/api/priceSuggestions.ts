import apiClient from './client';
import { PriceDecisionPayload, PriceSuggestion } from '../types/priceSuggestions';

export async function getPriceSuggestions(params: {
  minTouches?: number;
  decided?: boolean;
} = {}): Promise<PriceSuggestion[]> {
  const response = await apiClient.get<PriceSuggestion[]>('/price-suggestions', {
    params: {
      min_touches: params.minTouches ?? 2,
      decided: params.decided ?? false,
    },
  });
  return response.data;
}

/** Запомнить цену: она уходит в общий прайс под «Из смет». */
export async function acceptPriceSuggestion(
  payload: PriceDecisionPayload,
): Promise<{ written: boolean }> {
  const response = await apiClient.post('/price-suggestions/accept', payload);
  return response.data;
}

/** Не запоминать. В прайс не пишется ничего. */
export async function rejectPriceSuggestion(
  payload: PriceDecisionPayload,
): Promise<{ decision: string }> {
  const response = await apiClient.post('/price-suggestions/reject', payload);
  return response.data;
}

/** Вернуть предложение в очередь: снимает прежнее решение. */
export async function undoPriceDecision(
  payload: PriceDecisionPayload,
): Promise<{ restored: boolean }> {
  const response = await apiClient.post('/price-suggestions/undo', payload);
  return response.data;
}
