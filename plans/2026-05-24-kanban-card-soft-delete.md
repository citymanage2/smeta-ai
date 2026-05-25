# Plan: Soft Delete карточек канбана с восстановлением из корзины

**Дата:** 2026-05-24  
**Статус:** [x] Реализован целиком

## Цель

При удалении карточки в канбане — карточка и её задачи перемещаются в корзину. Из корзины можно восстановить карточку обратно в проект на ту же стадию (колонку), откуда была удалена.

## Фазы

### Phase 1: Backend [x]

- [x] Добавить `deleted_at: Optional[datetime]` в `WorkflowCard` model
- [x] Создать миграцию `027_add_deleted_at_to_workflow_cards.py`
- [x] Обновить `DELETE /workflow-cards/{card_id}` → soft delete карточки + задач
- [x] Добавить `GET /workflow-cards/trash` → список soft-deleted карточек с project_name
- [x] Добавить `POST /workflow-cards/{card_id}/restore` → восстановление карточки и задач
- [x] Добавить `DELETE /workflow-cards/{card_id}/permanent` → жёсткое удаление из корзины
- [x] Обновить `GET /projects/{project_id}/workflow-cards` → фильтр `deleted_at IS NULL`
- [x] Обновить `_load_card_with_tasks` → параметр `include_deleted`

### Phase 2: Frontend [x]

- [x] Добавить типы `TrashCardItem`, `TrashCardsResponse` в `workflowCards.ts`
- [x] Добавить API функции: `getTrashCards`, `restoreCard`, `permanentDeleteCard`
- [x] Добавить вкладку «Карточки» в `Trash.tsx` с восстановлением и удалением
- [x] Обновить текст модалки в `KanbanCard.tsx` (убрать «безвозвратно»)

## Итог

Реализован целиком. Commit: `3dddab4`.

**Как было:** удаление карточки — жёсткое, безвозвратное.  
**Как стало:** мягкое удаление (soft delete), карточка и задачи восстанавливаются из корзины в исходную стадию канбана.
