# План: Канбан-карточка «Перечень» — файлы, прогресс, модал задачи

## Цель
Улучшить карточку канбана стадии «Перечень»: показывать прикреплённые файлы, управлять ими, отображать прогресс выполнения задачи с кнопкой-стрелочкой, открывающей всплывающее окно задачи.

## Acceptance Criteria
- [ ] На карточке видны прикреплённые файлы (имя, формат, размер) и метка «из проекта» / «из Гранд-сметы»
- [ ] Кнопки «Удалить файл» (per-file) и «Добавить файл» на карточке (доступны когда задача не в processing)
- [ ] При `status === 'processing'`: одна строка с текущим этапом (progress_message)
- [ ] Рядом с прогрессом — кнопка-стрелочка с тултипом «Посмотреть задачу»
- [ ] Стрелочка открывает модальное окно с деталями задачи (name, type, status, progress, files, результаты)
- [ ] Модал закрывается по ×, клику на overlay, Escape

## Фазы

### Phase 1: Backend [x]
**Файлы:** `backend/app/schemas/workflow_card.py`, `backend/app/routers/workflow_cards.py`, `backend/app/routers/tasks.py`

Задачи:
- [ ] Добавить `input_files: list[dict]` и `progress_message: str | None` в `TaskBrief` schema
- [ ] Обновить `_task_brief()` — включить эти поля из Task модели
- [ ] Добавить `DELETE /tasks/{task_id}/input-file/{file_index}` endpoint
- [ ] Добавить `POST /tasks/{task_id}/input-files` endpoint

### Phase 2: Frontend types + API [x]
**Файлы:** `frontend/src/types/workflow.ts`, `frontend/src/api/tasks.ts`

Задачи:
- [ ] Добавить `input_files` и `progress_message` в `TaskBrief` type
- [ ] Добавить `deleteInputFile(taskId, fileIndex)` в `tasks.ts`
- [ ] Добавить `addInputFile(taskId, file)` в `tasks.ts`

### Phase 3: Frontend — ListStage на карточке [x]
**Файл:** `frontend/src/components/kanban/CardStageContent.tsx`

Задачи:
- [ ] Показывать input_files из task.input_files (когда task !== null)
- [ ] Метка «из проекта» / «из Гранд-сметы» из task_type
- [ ] Кнопки «✕» удалить файл (когда не processing) — вызов deleteInputFile + обновление карточки
- [ ] Кнопка «+ Добавить файл» (когда не processing) — file input + addInputFile + обновление
- [ ] Progress строка: когда processing, показывать task.progress_message ?? «Обрабатывается…»
- [ ] Кнопка-стрелочка рядом с прогрессом (или статусом) → открывает TaskDetailModal
- [ ] KanbanCard.tsx: пробросить через memo сравнение progress_message (или убрать строгое сравнение)

### Phase 4: Frontend — TaskDetailModal [x]
**Файл:** `frontend/src/components/TaskDetailModal.tsx` (новый)

Задачи:
- [ ] Компонент с props: `{ taskId: string; isOpen: boolean; onClose: () => void }`
- [ ] Внутри: `getTaskStatus` + `getTaskResults` + polling каждые 5 сек когда processing
- [ ] Отображение: имя задачи, тип (TASK_TYPE_LABELS), статус badge, progress_message, время создания
- [ ] Секция «Исходные файлы» — download buttons (downloadInputFile)
- [ ] Секция «Результаты» — download buttons (downloadResult / downloadSlotFile)
- [ ] Закрытие по ×, overlay click, Escape
- [ ] Overlay стиль как в других модалах проекта

## Итог
Статус: реализован полностью. TypeScript 0 ошибок, build успешен.
