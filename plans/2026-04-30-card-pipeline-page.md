# Страница карточки проекта с пайплайном этапов

Дата: 2026-04-30

## Задача

Создать страницу `/projects/:projectId/cards/:cardId`, отображающую все этапы
обработки в виде вертикального пайплайна:

1. Исходный файл (из list_task)
2. Перечень (результат list_task)
3. Проверка полноты (completeness_task, опционально)
4. Смета из перечня (estimate_task)
5. Оптимизация сметы (optimization_task, опционально)

К каждому файлу — дата, размер, кнопки: скачать / открыть задачу / открыть в редакторе.  
Для estimate/optimization этапов редактор открывается в fullscreen-попапе (iframe).  
Предупреждения на этапах, если предыдущий этап был изменён вручную.

## Фазы

### [x] Фаза 1 — Backend: поле manually_edited_at
- Добавить `manually_edited_at: Optional[datetime]` в `Task` модель
- Миграция `018_add_manually_edited_at_to_tasks.py`
- Обновить `estimate_versions.py`: ставить `manually_edited_at = now()` при сохранении строк (PUT rows)

### [x] Фаза 2 — Backend: endpoint детали карточки
- Добавить схемы `InputFileDetail`, `ResultFileDetail`, `StageDetail`, `CardDetailResponse` в `schemas/workflow_card.py`
- Добавить endpoint `GET /api/workflow-cards/{card_id}/detail` в `routers/workflow_cards.py`
  - Возвращает метаданные файлов для каждого из 4 этапов

### [x] Фаза 3 — Frontend: API
- Добавить типы и функции в `api/workflowCards.ts`:
  - `getCardDetail(cardId)` → `CardDetail`
  - `downloadSlotFileById(taskId, slot)`
  - `downloadInputFileById(taskId, fileIndex)`

### [x] Фаза 4 — Frontend: EstimateEditorModal
- Создать `components/card/EstimateEditorModal.tsx`
- Fullscreen overlay с iframe, указывающим на `/tasks/:taskId/estimate?embed=1`
- Слушает `window.message { type: 'estimate-saved' }` от iframe → вызывает `onSaved`
- В `stores/estimateEditor.ts` — `saveRows` постит `estimate-saved` в `window.parent`

### [x] Фаза 5 — Frontend: ProjectCardPage
- Создать `pages/ProjectCardPage.tsx`
- Вертикальный пайплайн из 5 StageBlock
- `FileRow` — строка файла с иконками и мета-инфой
- `ManualEditWarning` — жёлтый баннер при ручных изменениях
- `OptimizationStageContent` — список версий с раскрытием архива

### [x] Фаза 6 — Маршрутизация + навигация
- Добавить маршрут `/projects/:projectId/cards/:cardId` в `App.tsx`
- Добавить кнопку `LayoutList` в заголовок `KanbanCard.tsx` → navigate к странице

## Итог

Реализовано полностью:
- Страница карточки с пайплайном 5 этапов
- Метаданные файлов (имя, размер, дата) на каждом этапе
- Скачивание файлов напрямую
- Попап задачи (TaskDetailModal) по кнопке ↗
- Fullscreen редактор сметы (iframe к EstimateOptimizer) для estimate/optimization этапов
- Предупреждения о ручных изменениях между этапами
- Отслеживание manually_edited_at при сохранении строк в редакторе
- Кнопка-иконка в заголовке Kanban-карточки для перехода на страницу
