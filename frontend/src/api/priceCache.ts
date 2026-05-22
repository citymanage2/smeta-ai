import apiClient from './client';

export interface CacheItem {
  id: string;
  name: string;
  unit: string | null;
  price: number;
  sources: string | null;
  updated_at: string;
  expires_in_days: number;
}

export interface CacheResponse {
  items: CacheItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface CacheParams {
  search?: string;
  page?: number;
  page_size?: number;
}

export async function getCacheWorks(params: CacheParams): Promise<CacheResponse> {
  const r = await apiClient.get<CacheResponse>('/admin/price-cache/works', { params });
  return r.data;
}

export async function getCacheMaterials(params: CacheParams): Promise<CacheResponse> {
  const r = await apiClient.get<CacheResponse>('/admin/price-cache/materials', { params });
  return r.data;
}

export async function updateCacheWork(
  id: string,
  data: { name?: string; unit?: string; price?: number; sources?: string },
): Promise<CacheItem> {
  const r = await apiClient.patch<CacheItem>(`/admin/price-cache/works/${id}`, data);
  return r.data;
}

export async function updateCacheMaterial(
  id: string,
  data: { name?: string; unit?: string; price?: number; sources?: string },
): Promise<CacheItem> {
  const r = await apiClient.patch<CacheItem>(`/admin/price-cache/materials/${id}`, data);
  return r.data;
}

export async function deleteCacheWork(id: string): Promise<void> {
  await apiClient.delete(`/admin/price-cache/works/${id}`);
}

export async function deleteCacheMaterial(id: string): Promise<void> {
  await apiClient.delete(`/admin/price-cache/materials/${id}`);
}
