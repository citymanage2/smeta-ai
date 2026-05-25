import apiClient from './client';
import { RetrainStats, ReviewItem, TrainJobStatus } from '../types/retraining';

export async function parseFiles(files: File[]): Promise<{ items: ReviewItem[]; total: number }> {
  const formData = new FormData();
  files.forEach((f) => formData.append('files', f));
  const response = await apiClient.post<{ items: ReviewItem[]; total: number }>(
    '/retraining/parse',
    formData,
  );
  return response.data;
}

export interface SavePairPayload {
  anchor_text: string;
  candidate_text: string;
  candidate_type: string;
  is_positive: boolean;
  similarity_score: number;
  source_file?: string;
}

export async function savePair(payload: SavePairPayload): Promise<void> {
  await apiClient.post('/retraining/pairs', payload);
}

export async function getStats(): Promise<RetrainStats> {
  const response = await apiClient.get<RetrainStats>('/retraining/stats');
  return response.data;
}

export async function startTraining(): Promise<{ job_id: string }> {
  const response = await apiClient.post<{ job_id: string }>('/retraining/train');
  return response.data;
}

export async function getJobStatus(jobId: string): Promise<TrainJobStatus> {
  const response = await apiClient.get<TrainJobStatus>(`/retraining/train/${jobId}`);
  return response.data;
}
