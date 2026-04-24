# Plan: Задача остаётся в сайдбаре после удаления в корзину

## Статус: [x] Реализовано

## Проблема
При удалении задачи из левого сайдбара задача исчезает из него сразу.
Желаемое поведение: задача перемещается в корзину и остаётся в сайдбаре (с визуальным маркером «в корзине»). Из сайдбара пропадает только при окончательном удалении из корзины.

## Фазы

### [x] Фаза 1: Backend — добавить deleted_at в TaskBrief
- `projects.py` → `TaskBrief` schema: `deleted_at: Optional[str] = None`
- `list_unassigned_tasks`: добавить `Task.deleted_at` в SELECT, вернуть в ответе
- `get_project`: добавить `Task.deleted_at` в SELECT, вернуть в ответе
- `_aggregate()`: добавить фильтр `Task.deleted_at.is_(None)` (не считать deleted в счётчиках)
- `list_projects` JOIN: добавить условие `Task.deleted_at.is_(None)` в outerjoin

### [x] Фаза 2: Frontend типы
- `types/index.ts` → `TaskBrief`: добавить `deleted_at?: string | null`

### [x] Фаза 3: Frontend сайдбар
- `handleDeleteTask`: после soft delete обновить локальное состояние (`deleted_at = now`)
  без вызова `bumpTaskSync()`
- `renderTaskItem`: если задача с `deleted_at`, показать серым + зачёркнутый текст + нет кнопок Pencil/Trash2
- Фильтр `HIDDEN_TASK_TYPES` применяется только к активным задачам

## Граничные случаи
- Задача в проекте: обновление `projectTasks[projectId]` локально
- Задача без проекта: обновление `unassignedTasks` локально
- Reload страницы: backend вернёт `deleted_at` в ответе → sidebar правильно отобразит маркер
- Permanent delete из Admin/Trash: `bumpTaskSync()` → sidebar перезагрузится → задача исчезнет

## Итог
[x] Реализовано целиком
