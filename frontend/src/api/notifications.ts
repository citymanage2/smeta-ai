import apiClient from './client';

export interface NotificationTask {
  id: string;
  name?: string | null;
}

export interface SystemNotification {
  id: number;
  kind: string;
  created_at: string;
  resumed_count: number;
  tasks: NotificationTask[];
}

export interface SystemNotificationsResponse {
  /** id последнего просмотренного сервером события — двигается даже когда
   *  events пуст (событие могло быть скрыто по правам). */
  cursor: number;
  events: SystemNotification[];
}

export const KIND_BALANCE_RESTORED = 'balance_restored';

export async function getSystemNotifications(
  sinceId: number,
): Promise<SystemNotificationsResponse> {
  const { data } = await apiClient.get<SystemNotificationsResponse>('/notifications/system', {
    params: { since_id: sinceId },
  });
  return data;
}
