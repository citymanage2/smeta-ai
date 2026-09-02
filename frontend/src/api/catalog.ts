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

// ---------------------------------------------------------------------------
// Диагностика сопоставления с прайсом. «Прайс: найдено 16 из 1220» выглядит
// одинаково для трёх разных причин — пустой каталог, отсутствие векторов и
// слишком высокий порог похожести. Этот запрос показывает, какая именно.
// ---------------------------------------------------------------------------

export interface MatchCandidate {
  name: string;
  score: number;
  unit: string | null;
  price: number | null;
  would_match: boolean;
}

export interface MatchPreview {
  threshold: number;
  catalog_size: number;
  vectors_ready: boolean;
  matched: boolean;
  candidates: MatchCandidate[];
  hint: string;
}

export async function matchPreview(name: string, kind: 'work' | 'material'): Promise<MatchPreview> {
  const res = await apiClient.post<MatchPreview>('/prices/match-preview', { name, kind });
  return res.data;
}

// ---------------------------------------------------------------------------
// Эталонный прайс: цены из файла становятся единственно верными
//
// План `plans/2026-09-02-etalonnyy-prays-iz-smety.md`. Два вызова вместо одного:
// сначала «покажи, что исчезнет», потом «применяй». Между ними человек ставит
// галочки на дублях — сам сервер ничего не удаляет по догадке.
// ---------------------------------------------------------------------------

export interface ReferenceItem {
  kind: 'work' | 'material';
  name: string;
  unit: string | null;
  price: number;
}

export interface ReferenceRemovedPrice {
  contractor: string | null;
  price: number;
}

export interface ReferencePlanEntry {
  kind: 'work' | 'material';
  name: string;
  unit: string | null;
  price: number;
  action: 'add' | 'reprice' | 'blocked';
  match: { id: number; name: string; unit: string | null } | null;
  removed: ReferenceRemovedPrice[];
  reason: string | null;
}

export interface ReferenceDuplicate {
  source: 'price' | 'cache';
  kind: 'work' | 'material';
  id: string;
  name: string;
  unit: string | null;
  price: number | null;
  score: number;
  for_name: string;
}

export interface ReferencePreview {
  items: ReferenceItem[];
  plan: ReferencePlanEntry[];
  skipped: Record<string, number>;
  summary: Record<string, number>;
  duplicates: { vectors_ready: boolean; candidates: ReferenceDuplicate[] };
}

export interface ReferenceApplyResult {
  added: number;
  updated: number;
  blocked: number;
  removed: number;
  message: string;
}

export async function referencePreview(
  file: File,
  kind?: 'work' | 'material',
): Promise<ReferencePreview> {
  const form = new FormData();
  form.append('file', file);
  if (kind) form.append('kind', kind);
  const res = await apiClient.post<ReferencePreview>('/prices/reference/preview', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return res.data;
}

export async function referenceApply(
  items: ReferenceItem[],
  remove: { source: 'price' | 'cache'; kind: 'work' | 'material'; id: string }[],
): Promise<ReferenceApplyResult> {
  const res = await apiClient.post<ReferenceApplyResult>('/prices/reference/apply', {
    items,
    remove,
  });
  return res.data;
}
