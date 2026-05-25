# Кнопка «Перезапустить задачу»

**Цель:** добавить возможность перезапустить любую задачу заново — с нуля, заменяя предыдущий результат.

## Фазы

- [x] **Phase 1 — Backend endpoint**
  `POST /tasks/{task_id}/restart`
  - Работает для любого типа задачи
  - Работает для любого статуса кроме `processing`
  - Сбрасывает: `status → pending`, `error_message`, `progress_message`, `progress_data`, `progress_log`
  - Сохраняет: входные файлы, тип задачи, имя, проект, `chat_history`
  - Запускает фоновую обработку через `BackgroundTasks`

- [x] **Phase 2 — Frontend API**
  `restartTask(taskId)` в `frontend/src/api/tasks.ts`

- [x] **Phase 3 — TaskDetailModal**
  Кнопка `↺ Перезапустить` появляется при статусах `failed`, `cancelled`, `completed`.
  После нажатия — возобновляет поллинг и обновляет данные.

- [x] **Phase 4 — ProjectCardPage (канбан)**
  Компонент `RestartButton` в каждом этапе (Перечень, Проверка полноты, Смета, Оптимизация).
  Показывается при `task_status === 'failed' | 'cancelled'`.
  После нажатия — перезагружает карточку.

## Итог

Реализовано целиком. Коммит: `a1b9086`.

**Изменённые файлы:**
- `backend/app/routers/tasks.py` — новый endpoint `/restart`
- `frontend/src/api/tasks.ts` — функция `restartTask()`
- `frontend/src/components/TaskDetailModal.tsx` — кнопка в модале
- `frontend/src/pages/ProjectCardPage.tsx` — кнопки в этапах канбана
