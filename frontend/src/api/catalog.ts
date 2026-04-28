import apiClient from './client';

export interface CatalogItem {
  id: number;
  kind: 'work' | 'material';
  name: string;
  unit: string | null;
  price: number | null;
  prices: Record<string, number> | null;
  updated_at: string;
}

export interface CatalogResponse {
  items: CatalogItem[];
  total: number;
}

export interface CatalogParams {
  tab?: 'all' | 'works' | 'materials';
  search?: string;
  sort?: 'name_asc' | 'name_desc' | 'price_asc' | 'price_desc' | 'date_asc' | 'date_desc';
  page?: number;
  page_size?: number;
}

export async function getCatalog(params: CatalogParams): Promise<CatalogResponse> {
  const response = await apiClient.get<CatalogResponse>('/prices/catalog', { params });
  return response.data;
}

export async function createWork(data: { name: string; unit?: string; prices?: Record<string, number> }): Promise<CatalogItem> {
  const response = await apiClient.post<CatalogItem>('/prices/catalog/works', data);
  return response.data;
}

export async function createMaterial(data: { name: string; unit?: string; price?: number }): Promise<CatalogItem> {
  const response = await apiClient.post<CatalogItem>('/prices/catalog/materials', data);
  return response.data;
}

export async function updateWork(id: number, data: { name?: string; unit?: string; prices?: Record<string, number> }): Promise<CatalogItem> {
  const response = await apiClient.put<CatalogItem>(`/prices/catalog/works/${id}`, data);
  return response.data;
}

export async function updateMaterial(id: number, data: { name?: string; unit?: string; price?: number }): Promise<CatalogItem> {
  const response = await apiClient.put<CatalogItem>(`/prices/catalog/materials/${id}`, data);
  return response.data;
}

export async function deleteWork(id: number): Promise<void> {
  await apiClient.delete(`/prices/catalog/works/${id}`);
}

export async function deleteMaterial(id: number): Promise<void> {
  await apiClient.delete(`/prices/catalog/materials/${id}`);
}

export async function exportCatalog(tab: 'all' | 'works' | 'materials', search?: string): Promise<void> {
  const params: Record<string, string> = { tab };
  if (search) params.search = search;
  const response = await apiClient.get('/prices/catalog/export', { params, responseType: 'blob' });
  const url = URL.createObjectURL(response.data);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'catalog_export.xlsx';
  a.click();
  URL.revokeObjectURL(url);
}

export async function downloadTemplate(type: 'works' | 'materials'): Promise<void> {
  const response = await apiClient.get('/prices/catalog/template', { params: { type }, responseType: 'blob' });
  const url = URL.createObjectURL(response.data);
  const a = document.createElement('a');
  a.href = url;
  a.download = `template_${type}.xlsx`;
  a.click();
  URL.revokeObjectURL(url);
}
