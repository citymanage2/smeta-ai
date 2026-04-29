# Research: Корзина для задач

## Текущее состояние

### Backend
- Модель `Task` — нет полей soft-delete (`deleted_at`, `is_deleted`)
- Нет `DELETE /tasks/{id}` эндпоинта — есть только `POST /tasks/{id}/cancel`
- Единственный эндпоинт удаления: `DELETE /admin/tasks/{id}` — hard delete через CASCADE
- Последняя миграция: **015_add_task_input_files.py**
- Связанные таблицы (task_results, task_history, task_input_files, estimate_versions) — все с `ondelete="CASCADE"`
- Паттерн soft-delete не используется ни в одной модели

### Frontend
- `Admin.tsx` — кнопка "Удалить" → модальное подтверждение → `deleteTask(id)` → `DELETE /admin/tasks/{id}`
- `ProjectDetail.tsx` — задачи в проекте (нет кнопки удаления)
- `/api/admin.ts` → `deleteTask()` — API удаления
- Страница корзины: отсутствует
- Роут `/trash`: отсутствует

## Выбранное решение: Soft-Delete через поле `deleted_at`

### Почему этот подход лучший
- **Стандарт индустрии** — PostgreSQL + SQLAlchemy soft-delete через nullable timestamp
- **Reversible** — данные сохраняются, восстановление тривиально
- **Минимальный риск** — не ломает существующие CASCADE для связанных таблиц (они нужны только при hard delete)
- **Производительность** — один индекс `WHERE deleted_at IS NULL` покрывает все обычные запросы

### Альтернативы (отклонены)
- **Отдельная таблица `deleted_tasks`** — сложно, нужен перенос всех связанных данных
- **Поле `is_deleted: bool`** — хуже, не даёт информацию о времени удаления, сложнее автоочистка

## Что нужно сделать

### Backend
1. Поле `deleted_at: DateTime | None` в модели Task
2. Миграция 016
3. Эндпоинты:
   - `DELETE /admin/tasks/{id}` → **мягкое** удаление (ставит `deleted_at`)
   - `GET /admin/tasks/trash` → список задач в корзине
   - `DELETE /admin/tasks/{id}/permanent` → **окончательное** удаление (hard delete)
   - `POST /admin/tasks/{id}/restore` → восстановить из корзины
4. Фильтр `deleted_at IS NULL` во всех существующих GET-запросах задач

### Frontend
- Кнопка "Удалить" → теперь мягкое удаление (переход в корзину)
- Вкладка/секция "Корзина" в Admin.tsx
- В корзине: кнопки "Восстановить" и "Удалить навсегда"
