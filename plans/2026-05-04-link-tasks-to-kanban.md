# Автоматическая привязка задач из списка к канбану

**Дата:** 2026-05-04
**Статус:** реализовано

## Задача

Задачи, создаваемые через форму «Новая задача» (POST /tasks), не появлялись в канбане —
у них не было WorkflowCard. Задачи из канбана создавались через отдельный endpoint
и всегда получали карточку.

Цель: любая задача с project_id должна автоматически появляться в канбане.
Плюс — одноразовая миграция уже существующих задач без карточки.

## Фазы

- [x] **Фаза 1: Маппинги в constants.py**
  Добавить `TASK_TYPE_TO_FIELD` и `TASK_TYPE_TO_STAGE` в `backend/app/constants.py`,
  переиспользовать в `workflow_cards.py` вместо дублирующего `_TASK_TYPE_TO_FIELD`.

- [x] **Фаза 2: Авто-создание карточки в POST /tasks**
  После привязки `project_id` в `backend/app/routers/tasks.py` создавать `WorkflowCard`
  и прикреплять задачу к нужному полю (по `TASK_TYPE_TO_FIELD`).
  Название карточки = `task.name`, иначе `TASK_TYPE_LABELS[task_type]`.

- [x] **Фаза 3: Миграционный скрипт**
  `backend/scripts/migrate_tasks_to_kanban.py` — идемпотентный скрипт,
  создаёт WorkflowCard для всех задач с project_id без карточки.

## Запуск миграции на проде

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://... python scripts/migrate_tasks_to_kanban.py
```

## Итог

Реализовано полностью. Новые задачи из списка сразу появляются в канбане.
Для существующих задач — запустить скрипт миграции один раз.
