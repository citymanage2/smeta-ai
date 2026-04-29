# Research: Kanban Card — File Display, Progress, Task Modal

## Что нашли

### Архитектура карточки (стадия "Перечень")
- `KanbanCard.tsx` → `CardStageContent.tsx` → `ListStage` компонент
- `ListStage` читает `card.list_task: TaskBrief | null`
- `TaskBrief` сейчас: `{id, task_type, status, name, created_at}`
- **Не хватает**: `input_files`, `progress_message`

### Хранение файлов
- При создании задачи: файл идёт в `task_input_files` таблицу (TaskInputFile модель)
- Метаданные: `task.input_files` — JSON массив `{name, mime_type, size_bytes}`
- Скачать: `GET /tasks/{id}/input-file/{index}` — уже есть
- Удалить: **нет**, нужно добавить `DELETE /tasks/{id}/input-file/{index}`
- Добавить: **нет**, нужно добавить `POST /tasks/{id}/input-files`

### Прогресс
- `Task.progress_message` есть в БД (String(500))
- В `TaskBrief` НЕ включён — нужно добавить
- Канбан уже поллит каждые 5 сек — как только добавим поле в schema, всё заработает

### Модальные окна в проекте
- Паттерн: `position: fixed`, `inset: 0`, `rgba(0,0,0,0.3)` overlay, закрытие по клику на overlay
- Примеры: `OptimizeModal.tsx`, `HistoryModal.tsx`, `CreateCardModal.tsx`
- Размеры: `560px–700px`, `maxWidth: 95vw`, `maxHeight: 85vh`, `overflow-y: auto`

### TaskStatus страница
- `TaskStatus.tsx` — огромный файл (~1700 строк), сложный с кучей состояния
- Не стоит пытаться сделать его переиспользуемым — лучше новый `TaskDetailModal`
- Ключевые поля для показа: name, task_type, status, progress_message, input_files, results

## Решение

### Рекомендуется: 4-фазный план

**Phase 1: Backend**
1. Добавить `input_files: list[dict]` и `progress_message: str | None` в `TaskBrief` schema
2. Обновить `_task_brief()` в `workflow_cards.py` — `task.input_files` уже есть в модели
3. Добавить `DELETE /tasks/{id}/input-file/{index}` — удаляет из `task_input_files` + обновляет `task.input_files` JSON
4. Добавить `POST /tasks/{id}/input-files` — добавляет файл

**Phase 2: Frontend types + API**
1. Расширить `TaskBrief` в `workflow.ts`
2. Добавить `deleteInputFile`, `addInputFile` в `tasks.ts`

**Phase 3: Frontend — ListStage**
1. Показывать `input_files` из `task.input_files` на карточке (когда task !== null)
2. Кнопки "Удалить" (только когда не processing)
3. Кнопка "Добавить файл" (только когда не processing)  
4. Метка "из проекта" / "из Гранд-сметы" по `task_type`
5. Прогресс: когда `status === 'processing'`, показывать `task.progress_message` одной строкой
6. Кнопка-стрелочка рядом с прогрессом → открывает TaskDetailModal

**Phase 4: Frontend — TaskDetailModal**
- Новый `TaskDetailModal.tsx` компонент
- Получает `taskId: string`, открывается через `isOpen: boolean`
- Внутри: `getTaskStatus` + `getTaskResults`
- Показывает: name, type, status badge, progress_message, input_files, result files (download)
- Закрытие по ×, по клику на overlay, по Escape

## Что НЕ делаем
- Не рефакторим `TaskStatus.tsx` — слишком рискованно
- Файлы не удаляем/добавляем когда `status === 'processing'` — логично и безопасно
- Не добавляем полный функционал редактирования сметы в модал
