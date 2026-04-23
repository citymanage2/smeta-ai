# План: Корзина для задач

**Статус:** [x] Реализован  
**Дата:** 2026-04-24  
**Задача:** Мягкое удаление задач → корзина → окончательное удаление

## Проблема

Сейчас кнопка "Удалить" в Admin.tsx уничтожает задачу навсегда (hard delete через CASCADE). Нет возможности восстановить случайно удалённую задачу.

## Цель

- Кнопка "Удалить" → перемещает задачу в корзину (soft delete)
- Раздел "Корзина" в Admin.tsx — список задач в корзине
- В корзине: "Восстановить" и "Удалить навсегда"

## Challenge Log

1. **Решает проблему?** Да — prevents accidental loss, reversible delete.
2. **Эффективнее альтернатив?** Да — soft-delete через `deleted_at` — стандарт, минимальный code change.
3. **Code for code's sake?** Нет — только что нужно для фичи.

---

## Фаза 1: Backend — модель + миграция

**[x]** 1.1 Добавить поле `deleted_at: DateTime | None` в `backend/app/models/task.py`  
**[x]** 1.2 Создать миграцию `016_add_task_soft_delete.py`  
**[x]** 1.3 Фильтр `deleted_at IS NULL` в роуте `GET /admin/tasks`  

## Фаза 2: Backend — новые эндпоинты

**[x]** 2.1 `DELETE /admin/tasks/{id}` → мягкое удаление (ставит `deleted_at = now()`)  
**[x]** 2.2 `GET /admin/tasks/trash` → список задач в корзине (`deleted_at IS NOT NULL`)  
**[x]** 2.3 `DELETE /admin/tasks/{id}/permanent` → окончательное удаление (hard delete)  
**[x]** 2.4 `POST /admin/tasks/{id}/restore` → восстановить (`deleted_at = None`)  

## Фаза 3: Frontend — API + стор

**[x]** 3.1 Добавить в `/api/admin.ts`: `getTrashTasks`, `restoreTask`, `permanentDeleteTask`  
**[x]** 3.2 Обновить тип `AdminTask` в `/types/index.ts` — добавить `deleted_at?: string | null`

## Фаза 4: Frontend — UI

**[x]** 4.1 В `Admin.tsx`: вкладка "Корзина" рядом с основным списком задач  
**[x]** 4.2 Кнопка "Удалить" → мягкое удаление, модальное: "Переместить в корзину?"  
**[x]** 4.3 В корзине: строки задач с кнопками "Восстановить" и "Удалить навсегда"  
**[x]** 4.4 Модальное подтверждение для "Удалить навсегда"

---

## Итог

**Реализован:** да, полностью  
**TypeScript:** 0 ошибок  
**Python:** синтаксис чист
