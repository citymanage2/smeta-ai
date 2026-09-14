import apiClient from './client';
import type {
  KpCategory, KpCell, KpCounters, KpCreatePayload, KpFile, KpOffer, KpOfferForm,
  KpPreview, KpPreviewBody, KpPriceBody, KpRequestBrief, KpRequestDetail, KpStatus,
} from '../types/kp';
import {
  KP_ATTACHMENT_EXTENSIONS, KP_MAX_FILE_MB, KP_MAX_FILES,
} from '../types/kp';

// Запросы КП у отдела производства работ (план plans/2026-09-14-zapros-kp.md).
// Сервер — `backend/app/routers/kp_requests.py`.

/** Как выделение разложится по запросам. Ничего не пишет. */
export async function previewKpRequest(body: KpPreviewBody): Promise<KpPreview> {
  const res = await apiClient.post<KpPreview>('/kp-requests/preview', body);
  return res.data;
}

/**
 * Создать по запросу на группу. Multipart: JSON-часть `payload` и файлы —
 * вложения копируются сервером в каждый созданный запрос.
 */
export async function createKpRequests(
  payload: KpCreatePayload, files: File[],
): Promise<{ requests: KpRequestBrief[] }> {
  const form = new FormData();
  form.append('payload', JSON.stringify(payload));
  for (const file of files) form.append('files', file, file.name);
  const res = await apiClient.post<{ requests: KpRequestBrief[] }>('/kp-requests', form);
  return res.data;
}

export async function listCardKpRequests(cardId: string): Promise<KpRequestBrief[]> {
  const res = await apiClient.get<KpRequestBrief[]>('/kp-requests', { params: { card_id: cardId } });
  return res.data;
}

export async function getKpRequest(requestId: string): Promise<KpRequestDetail> {
  const res = await apiClient.get<KpRequestDetail>(`/kp-requests/${requestId}`);
  return res.data;
}

export async function cancelKpRequest(requestId: string): Promise<KpRequestDetail> {
  const res = await apiClient.post<KpRequestDetail>(`/kp-requests/${requestId}/cancel`);
  return res.data;
}

export async function reopenKpRequest(requestId: string): Promise<KpRequestDetail> {
  const res = await apiClient.post<KpRequestDetail>(`/kp-requests/${requestId}/reopen`);
  return res.data;
}

export async function addKpRequestFiles(requestId: string, files: File[]): Promise<KpFile[]> {
  const form = new FormData();
  for (const file of files) form.append('files', file, file.name);
  const res = await apiClient.post<{ files: KpFile[] }>(`/kp-requests/${requestId}/files`, form);
  return res.data.files;
}

export async function deleteKpRequestFile(fileId: string): Promise<void> {
  await apiClient.delete(`/kp-request-files/${fileId}`);
}

export async function getKpCounters(): Promise<KpCounters> {
  const res = await apiClient.get<KpCounters>('/kp-requests/counters');
  return res.data;
}

// --- Рабочее место отдела производства (фаза 5) ------------------------------

/** Производству — запросы своей роли; продажам — поставленные мной. */
export async function listMyKpRequests(status?: KpStatus): Promise<KpRequestBrief[]> {
  const res = await apiClient.get<KpRequestBrief[]>('/kp-requests/mine', {
    params: status ? { status } : undefined,
  });
  return res.data;
}

export async function takeKpRequest(requestId: string): Promise<KpRequestDetail> {
  const res = await apiClient.post<KpRequestDetail>(`/kp-requests/${requestId}/take`);
  return res.data;
}

/** Пустая строка даты — «не указана». */
function dateOrNull(value: string): string | null {
  const text = value.trim();
  return text ? text : null;
}

/**
 * Загрузить КП. Multipart: условия полями формы и файл. Режим НДС обязателен —
 * сервер без него ответит 422; ставку шлём только при «с НДС».
 */
export async function createKpOffer(
  requestId: string, form: KpOfferForm, file: File | null, category: KpCategory,
): Promise<KpOffer> {
  const data = new FormData();
  if (form.vat_mode) data.append('vat_mode', form.vat_mode);
  if (form.vat_mode === 'with_vat' && form.vat_rate.trim()) data.append('vat_rate', form.vat_rate.trim());
  if (form.supplier_name.trim()) data.append('supplier_name', form.supplier_name.trim());
  const date = dateOrNull(form.offer_date);
  if (date) data.append('offer_date', date);
  data.append('includes_materials', category === 'work' && form.includes_materials ? 'true' : 'false');
  if (file) data.append('file', file, file.name);
  const res = await apiClient.post<KpOffer>(`/kp-requests/${requestId}/offers`, data);
  return res.data;
}

/** Поправить условия КП (частично: сервер применяет только переданные поля). */
export async function updateKpOffer(
  offerId: string, form: KpOfferForm, category: KpCategory,
): Promise<KpOffer> {
  const body: Record<string, unknown> = {
    supplier_name: form.supplier_name.trim(),
    offer_date: dateOrNull(form.offer_date),
  };
  if (form.vat_mode) {
    body.vat_mode = form.vat_mode;
    body.vat_rate = form.vat_mode === 'with_vat' && form.vat_rate.trim()
      ? Number(form.vat_rate.trim().replace(',', '.'))
      : null;
  }
  if (category === 'work') body.includes_materials = form.includes_materials;
  const res = await apiClient.patch<KpOffer>(`/kp-offers/${offerId}`, body);
  return res.data;
}

export async function deleteKpOffer(offerId: string): Promise<void> {
  await apiClient.delete(`/kp-offers/${offerId}`);
}

/** Ручная цена позиции в КП — сразу подтверждена. */
export async function setKpOfferPrice(offerId: string, itemId: string, body: KpPriceBody): Promise<KpCell> {
  const res = await apiClient.put<KpCell>(`/kp-offers/${offerId}/prices/${itemId}`, body);
  return res.data;
}

export async function confirmKpOfferPrice(offerId: string, itemId: string): Promise<KpCell> {
  const res = await apiClient.post<KpCell>(`/kp-offers/${offerId}/prices/${itemId}/confirm`);
  return res.data;
}

export async function deleteKpOfferPrice(offerId: string, itemId: string): Promise<void> {
  await apiClient.delete(`/kp-offers/${offerId}/prices/${itemId}`);
}

/** Отметить КП выбранным у позиции; `null` — снять выбор. */
export async function selectKpOffer(itemId: string, offerId: string | null): Promise<KpRequestDetail> {
  const res = await apiClient.put<KpRequestDetail>(
    `/kp-request-items/${itemId}/selected-offer`, { offer_id: offerId },
  );
  return res.data;
}

export async function completeKpRequest(requestId: string, report: string): Promise<KpRequestDetail> {
  const res = await apiClient.post<KpRequestDetail>(`/kp-requests/${requestId}/complete`, { report });
  return res.data;
}

/** Повторить запись цен в прайс после сбоя (ручка — фаза 7). */
export async function retryKpPricelist(requestId: string): Promise<KpRequestDetail> {
  const res = await apiClient.post<KpRequestDetail>(`/kp-requests/${requestId}/pricelist/retry`);
  return res.data;
}

function downloadUrl(path: string): string {
  const token = localStorage.getItem('token') ?? '';
  const baseUrl = import.meta.env.VITE_API_BASE_URL || 'https://smeta-ai-backend.onrender.com';
  return `${baseUrl}${path}?token=${encodeURIComponent(token)}`;
}

/**
 * Ссылка на скачивание вложения. Токен — в `?token=`: браузер открывает
 * ссылку сам и заголовок не пошлёт. Ключ S3 наружу не отдаётся, роль проверяет
 * сервер.
 */
export function kpFileDownloadUrl(fileId: string): string {
  return downloadUrl(`/kp-request-files/${fileId}/download`);
}

/** Ссылка на файл КП — так же, через роутер с проверкой роли. */
export function kpOfferDownloadUrl(offerId: string): string {
  return downloadUrl(`/kp-offers/${offerId}/download`);
}

/** Текст ошибки сервера для человека: русский `detail` — как есть. */
export function kpErrorText(error: unknown, fallback: string): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === 'string' && /[а-яёА-ЯЁ]/.test(detail)) return detail;
  return fallback;
}

/**
 * Проверить вложения до отправки — те же правила, что на сервере: тип по
 * расширению, размер, число. Сервер проверяет всё равно; здесь — чтобы человек
 * узнал о лишнем файле до того, как дождётся загрузки 50 МБ.
 */
export function checkKpAttachments(
  files: File[], existing: number,
): { accepted: File[]; rejected: Array<{ name: string; reason: string }> } {
  const accepted: File[] = [];
  const rejected: Array<{ name: string; reason: string }> = [];
  for (const file of files) {
    const dot = file.name.lastIndexOf('.');
    const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : '';
    if (!KP_ATTACHMENT_EXTENSIONS.includes(ext)) {
      rejected.push({
        name: file.name,
        reason: 'тип файла не поддерживается (PDF, XLSX, XLS, DOC, DOCX, JPG, PNG)',
      });
    } else if (file.size > KP_MAX_FILE_MB * 1024 * 1024) {
      rejected.push({ name: file.name, reason: `файл больше ${KP_MAX_FILE_MB} МБ` });
    } else if (existing + accepted.length >= KP_MAX_FILES) {
      rejected.push({ name: file.name, reason: `к запросу можно приложить не больше ${KP_MAX_FILES} файлов` });
    } else {
      accepted.push(file);
    }
  }
  return { accepted, rejected };
}

/** id сотрудника из токена — только для подсказок интерфейса, права решает сервер. */
export function currentUserIdFromToken(): number | null {
  try {
    const token = localStorage.getItem('token') ?? '';
    const part = token.split('.')[1];
    if (!part) return null;
    const json = JSON.parse(atob(part.replace(/-/g, '+').replace(/_/g, '/')));
    const sub = String(json?.sub ?? '');
    return /^\d+$/.test(sub) ? Number(sub) : null;
  } catch {
    return null;
  }
}
