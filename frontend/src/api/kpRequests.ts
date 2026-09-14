import apiClient from './client';
import type {
  KpCounters, KpCreatePayload, KpFile, KpPreview, KpPreviewBody,
  KpRequestBrief, KpRequestDetail,
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

/**
 * Ссылка на скачивание вложения. Токен — в `?token=`: браузер открывает
 * ссылку сам и заголовок не пошлёт. Ключ S3 наружу не отдаётся, роль проверяет
 * сервер.
 */
export function kpFileDownloadUrl(fileId: string): string {
  const token = localStorage.getItem('token') ?? '';
  const baseUrl = import.meta.env.VITE_API_BASE_URL || 'https://smeta-ai-backend.onrender.com';
  return `${baseUrl}/kp-request-files/${fileId}/download?token=${encodeURIComponent(token)}`;
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
