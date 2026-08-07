import apiClient from './client';
import { Correction, CorrectionsStats } from '../types/corrections';

export async function getCorrectionsStats(): Promise<CorrectionsStats> {
  const response = await apiClient.get<CorrectionsStats>('/corrections/stats');
  return response.data;
}

export async function getCorrections(params: {
  limit?: number;
  firstTouchOnly?: boolean;
  documentKind?: string;
}): Promise<Correction[]> {
  const response = await apiClient.get<Correction[]>('/corrections', {
    params: {
      limit: params.limit ?? 50,
      first_touch_only: params.firstTouchOnly ?? true,
      document_kind: params.documentKind || undefined,
    },
  });
  return response.data;
}
