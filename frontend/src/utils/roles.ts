// Роли сотрудников и что из них следует для интерфейса.
//
// Зеркало `backend/app/utils/permissions.py`. Отдел производства работ
// (снабжение и работа с подрядчиками) видит только запросы КП своей роли:
// всё прочее API ему закрыто на сервере, а интерфейс не показывает разделов,
// которые всё равно ответили бы 403. Модуль без импортов — его можно звать
// из стора, маршрутов и меню, не таща за собой API-клиент.

export const ROLE_SUPPLY = 'supply_manager';
export const ROLE_CONTRACTOR = 'contractor_manager';

export const PRODUCTION_ROLES: readonly string[] = [ROLE_SUPPLY, ROLE_CONTRACTOR];

export function isProductionRole(role: string | null | undefined): boolean {
  return !!role && PRODUCTION_ROLES.includes(role);
}

// Рабочее место отдела производства — «Мои задачи КП».
export const KP_INBOX_PATH = '/kp';

// Куда приземлить после входа: продажам — «Входящий», производству — КП.
export function landingPathForRole(role: string | null | undefined): string {
  return isProductionRole(role) ? KP_INBOX_PATH : '/system';
}
