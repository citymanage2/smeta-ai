# Research: Задачи в корзине остаются в сайдбаре

## Задача
Когда удаляешь задачу из левого сайдбара — задача перемещается в корзину, но из сайдбара удаляется только когда удаляешь из корзины (permanent delete).

## Текущая архитектура

### Backend
- Soft delete: `DELETE /admin/tasks/{id}` → устанавливает `task.deleted_at = now()`
- Permanent delete: `DELETE /admin/tasks/{id}/permanent` → `db.delete(task)`
- `getUnassignedTasks()` (projects.py): НЕТ фильтра по `deleted_at` — возвращает все задачи, включая soft-deleted
- `getProject()` (projects.py): НЕТ фильтра по `deleted_at` — аналогично
- `listProjects()` aggregation: НЕТ фильтра → считает deleted задачи в счётчиках проекта
- `_aggregate()`: НЕТ фильтра → тоже считает deleted задачи

### Frontend
- `TaskBrief` тип: нет поля `deleted_at`
- Сайдбар: после soft delete вызывает `bumpTaskSync()` → reload → задача снова появляется (backend не фильтрует)
- Но `deleted_at` не передаётся → нет возможности визуально различить задачи

### Вывод о текущем состоянии
Технически backend уже возвращает soft-deleted задачи в sidebar API. Но:
1. `TaskBrief` не содержит `deleted_at` → frontend не знает о статусе
2. Нет визуального индикатора "в корзине"
3. Aggregation считает deleted задачи в счётчиках проекта

## Выбранное решение

### Подход: передать deleted_at в TaskBrief + локальное обновление состояния

**Backend:**
1. Добавить `deleted_at: Optional[str] = None` в `TaskBrief` schema
2. Включить `Task.deleted_at` в SELECT в `list_unassigned_tasks` и `get_project`
3. Добавить `Task.deleted_at.is_(None)` фильтр в `_aggregate()` и join в `list_projects`
   → счётчики проектов не считают deleted задачи

**Frontend:**
1. Добавить `deleted_at?: string | null` в `TaskBrief` интерфейс
2. После soft delete из sidebar: обновить локальное состояние (добавить `deleted_at = now`) без `bumpTaskSync()`
3. Показывать задачи с `deleted_at` в сайдбаре с визуальным индикатором (зачёркнутый текст, серый цвет, нет кнопок действий)
4. Задача исчезает из sidebar только при permanent delete (существующий `bumpTaskSync()` в Admin.tsx)

## Файлы для изменения
- `backend/app/routers/projects.py` — TaskBrief schema + queries
- `frontend/src/types/index.ts` — TaskBrief interface
- `frontend/src/components/ProjectsSidebar.tsx` — handleDeleteTask + renderTaskItem
