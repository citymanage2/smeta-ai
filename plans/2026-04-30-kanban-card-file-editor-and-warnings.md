# Онлайн-редактор файлов и предупреждения в канбан-карточках

Дата: 2026-04-30  
Статус: планирование

---

## Challenge Log

### 1. РЕШАЕТ ЛИ ЭТО ПРОБЛЕМУ?

Acceptance criteria из задачи → покрытие:

| Критерий | Фаза плана |
|---|---|
| Исходный файл → кнопка открыть в редакторе | Фаза 2 (backend), Фаза 5 (frontend) |
| Перечень → кнопка открыть в редакторе | Фаза 2, Фаза 5 |
| Проверка полноты (если создано) → кнопка открыть | Фаза 2, Фаза 5 |
| Смета из перечня → кнопка открыть | Фаза 5 (уже есть EditModal) |
| Оптимизация → все файлы версий + скачать + переход в задачу | Фаза 5 |
| Каждый файл → дата/время | Фаза 1, Фаза 5 |
| При сохранении: следующий не запущен → автоматически берёт отредактированный файл | Фаза 3 |
| При сохранении: следующий запущен → предупреждение + баннер | Фаза 4 |
| Высота карточек → collapse/expand | Фаза 5 |
| Предупреждения и в канбане, и на странице карточки | Фаза 4, Фаза 6 |

Все критерии покрыты. План полный.

### 2. САМОЕ ЭФФЕКТИВНОЕ РЕШЕНИЕ?

**Альтернатива A: Простой xlsx-просмотрщик без версионирования**
- Плюсы: минимальная сложность, быстрая реализация
- Минусы: нет истории изменений (пользователь выбрал Б — полная версионность)
- Трудоёмкость: M

**Альтернатива Б (выбранная): EstimateVersions для всех типов задач**
- Плюсы: единый механизм, история версий, rollback, совместимость с существующим редактором
- Минусы: EstimateVersion содержит estimate-специфичные поля (overhead_pct и т.д.) — для list/completeness они будут 0/null; нужна адаптация редактора для generic-режима
- Трудоёмкость: L

**Альтернатива В: Внешний редактор (OnlyOffice/Google Sheets)**
- Плюсы: полноценный Excel-редактор
- Минусы: внешняя зависимость, авторизация, сложная интеграция, непредсказуемая цена
- Трудоёмкость: XL

Выбор Б обоснован: переиспользует существующую инфраструктуру, соответствует запросу пользователя, рабочий редактор уже написан.

### 3. ЕСТЬ ЛИ КОД РАДИ КОДА?

Каждое изменение привязано к acceptance criteria. Единственный риск — адаптация редактора под generic-режим: делаем только то, что нужно для list/completeness (не рефакторим всю страницу).

---

## Решения по ключевым вопросам

| Вопрос | Решение |
|---|---|
| Редактор для перечня/полноты | Полный EstimateVersions + адаптация editor-страницы под generic-режим |
| Редактирование исходного файла | Обновляем TaskInputFile.content + предупреждение "переформируйте перечень вручную" |
| При сохранении перечня | Перезаписываем TaskResult.result → следующая задача берёт автоматически |
| Оптимизация popup | Переход на `/tasks/:id/estimate` в новой вкладке |
| Данные о файлах в канбане | Отдельный лёгкий endpoint без binary content (добавляем `size_bytes` к TaskResult) |
| Размер карточек | Collapse/expand на уровне блоков файлов внутри каждой стадии |
| Предупреждения | В CardStageContent + в ProjectCardPage, с указанием конкретного этапа |

---

## Edge Cases

### Конкурентность и гонки
- **EC-1**: Два пользователя редактируют один файл одновременно → last-write-wins (приемлемо для внутреннего инструмента). В README editor-страницы добавить предупреждение.
- **EC-2**: Фоновая задача (processing) + попытка открыть редактор → кнопка "Открыть в редакторе" отключена при `task.status !== 'completed'`.
- **EC-3**: Смета создаётся в момент, когда перечень редактируется → race condition на TaskResult.result. Решение: атомарное обновление (отдельная транзакция при сохранении версии).

### Данные
- **EC-4**: TaskResult существует, но `file_data` пуст (0 байт) → editor-страница показывает пустую таблицу. Не ошибка.
- **EC-5**: `mime_type` не xlsx (pdf, docx) → кнопка редактора не показывается, только скачать.
- **EC-6**: Задача завершена, но result_files пуст (ошибка на стороне процессора) → показываем "файлы не готовы", не падаем.
- **EC-7**: LIST_FROM_PROJECT с несколькими input-файлами → каждый файл показывается отдельной строкой с кнопками; редактор открывается по file_index.
- **EC-8**: Очень большой файл (5000+ строк) → редактор работает медленно; ничего не блокирует, просто медленно.

### Цепочка предупреждений
- **EC-9**: Перечень отредактирован после создания И сметы, И оптимизации → предупреждение должно появиться НА ОБОИХ этапах (смета и оптимизация).
- **EC-10**: Несколько ручных редактирований → `manually_edited_at` хранит время ПОСЛЕДНЕГО редактирования. Для сравнения с `task_created_at` следующего этапа это корректно.
- **EC-11**: Перечень отредактирован → смета переформирована → перечень отредактирован ещё раз → warning должен снова появиться на смете (время редактирования > время создания новой сметы). Проверить логику `wasEditedBefore`.

### Версионирование
- **EC-12**: Существующие LIST/COMPLETENESS задачи без EstimateVersions → при первом открытии редактора создаётся начальная версия ("V0 — Оригинал") из текущего TaskResult.result. Если TaskResult нет — кнопка редактора недоступна.
- **EC-13**: TaskResult.result перезаписан → если при сохранении версии генерируем новый xlsx и перезаписываем result — старый файл потерян. Решение: before overwrite создаём snapshot в слоте `result_backup_{timestamp}` — НЕТ, это излишне; версия в EstimateVersions и есть снапшот. Result всегда = последняя версия.
- **EC-14**: EstimateVersion.rows для list/completeness — другая структура колонок чем у сметы. Редактор (frontend) должен детектировать тип задачи и не показывать estimate-специфичные UI-элементы (overhead_pct поле, категории, proposals).

### API
- **EC-15**: `GET /workflow-cards/:id/files-meta` вызывается при разворачивании карточки — может быть вызван несколько раз быстро. Frontend должен дедуплицировать (флаг loading + кэш до следующего poll).
- **EC-16**: Файл метаданных endpoint запрашивается для карточки без optimization_stage → возвращаем null для этого поля, не ошибку.

### UI/UX
- **EC-17**: Collapse-состояние карточки — хранить в локальном state React (не в Zustand store), не ресетировать при poll-обновлении данных.
- **EC-18**: После сохранения в редакторе (postMessage `estimate-saved`) → перезагружаем файл-метаданные для этой карточки, не всего канбана.
- **EC-19**: Кнопка "Открыть в редакторе" для НЕ-xlsx файлов (если появится) → не показываем, только скачать.
- **EC-20**: Оптимизация открывается в новой вкладке (`window.open`) — убедиться что роут `/tasks/:id/estimate` существует и работает без auth-редиректа при прямом заходе.

### Обратная совместимость
- **EC-21**: `size_bytes` добавляется как новая колонка в `task_results` → существующие строки получат NULL. Добавить DEFAULT 0 или вычислить при миграции с помощью UPDATE.
- **EC-22**: EstimateVersions для LIST-задач — существующий endpoint `GET /tasks/:id/estimate/versions` вернёт версии для любого task_type. Проверить что frontend estimate-страница корректно обрабатывает generic task type.

---

## Архитектура изменений

### Новые таблицы / колонки

| Изменение | Таблица | Цель |
|---|---|---|
| Добавить `size_bytes INTEGER` | `task_results` | Легковесный endpoint без загрузки blob |
| Добавить `file_slot VARCHAR(20) DEFAULT 'result'` | `estimate_versions` | Различить версии input-файла и result-файла для одной задачи |
| Добавить `task_type VARCHAR(50)` | `estimate_versions` | Детектирование generic-режима в редакторе без join |

### Новые endpoints

| Метод | URL | Назначение |
|---|---|---|
| GET | `/workflow-cards/{card_id}/files-meta` | Метаданные файлов всех стадий без binary |
| POST | `/tasks/{task_id}/estimate/init-from-result` | Создать начальную EstimateVersion из TaskResult (для LIST/COMPLETENESS) |
| POST | `/tasks/{task_id}/estimate/init-from-input/{file_index}` | Создать начальную EstimateVersion из TaskInputFile (для исходного файла) |

### Изменения в существующих endpoints

| Endpoint | Изменение |
|---|---|
| `PUT /tasks/{task_id}/estimate/versions/{version_id}/rows` | После сохранения: если task_type ∈ LIST/COMPLETENESS types — перегенерировать xlsx и обновить TaskResult.result (или TaskInputFile.content для file_slot=input) |
| `GET /tasks/{task_id}/estimate/versions` | Фильтровать по `file_slot` (query param), чтобы разделить input и result версии |

### Изменения в task_processor.py

| Задача | Изменение |
|---|---|
| LIST_FROM_PROJECT, LIST_FROM_GRAND | После сохранения результата — создать EstimateVersion(file_slot='result', task_type='LIST_FROM_*') с распарсенными строками xlsx |
| CHECK_LIST_COMPLETENESS, CHECK_PROJECT_COMPLETENESS | То же для file_slot='result' |
| ESTIMATE_FROM_LIST | Без изменений (уже создаёт EstimateVersions) |
| ESTIMATE_OPTIMIZATION | Без изменений |

### Изменения в frontend

| Файл | Изменение |
|---|---|
| `frontend/src/components/kanban/CardStageContent.tsx` | Добавить: collapse/expand, file-metadata fetch, кнопки редактора, даты, предупреждения ManualEditWarning |
| `frontend/src/pages/tasks/EstimatePage.tsx` (или аналог) | Добавить generic-режим: скрывать overhead%, proposals, категории для LIST/COMPLETENESS task types |
| `frontend/src/pages/ProjectCardPage.tsx` | Обновить ManualEditWarning: указывать конкретный этап + дату для всех типов задач (уже частично есть) |
| `frontend/src/api/workflowCards.ts` | Добавить `getCardFilesMeta(cardId)` |

---

## Фазы реализации

### Фаза 1 — Backend: миграция и lightweight endpoint
**Цель**: дать фронтенду метаданные файлов без загрузки binary

**Задачи:**
1. Создать миграцию `alembic/versions/0NN_add_size_bytes_to_task_results.py`
   - Добавить `size_bytes INTEGER NOT NULL DEFAULT 0` в `task_results`
   - UPDATE существующих строк: `UPDATE task_results SET size_bytes = octet_length(file_data)`
   - Добавить `file_slot VARCHAR(20) NOT NULL DEFAULT 'result'` в `estimate_versions`
   - Добавить `task_type VARCHAR(50)` (nullable) в `estimate_versions`

2. Обновить модель `TaskResult` — добавить поле `size_bytes`
3. Обновить модель `EstimateVersion` — добавить `file_slot`, `task_type`
4. Обновить все места где создаётся `TaskResult` — передавать `size_bytes=len(file_data)`
5. Создать endpoint `GET /workflow-cards/{card_id}/files-meta` в `workflow_cards.py`
   - Логика идентична `get_card_detail` но без загрузки binary (читает `size_bytes` из колонки)
   - Response schema: `CardFilesMetaResponse` (аналог `CardDetailResponse` без binary)

**Файлы:**
- `backend/alembic/versions/0NN_add_size_bytes_file_slot_to_results_versions.py` (новый)
- `backend/app/models/result.py`
- `backend/app/models/estimate_version.py`
- `backend/app/routers/workflow_cards.py`
- `backend/app/schemas/workflow_card.py`
- `backend/app/services/task_processor.py` (все места `TaskResult(...)`)

**Статус:** `[x]`

---

### Фаза 2 — Backend: EstimateVersions для LIST и COMPLETENESS задач
**Цель**: LIST и COMPLETENESS задачи после завершения создают EstimateVersion, что позволяет открывать их в редакторе

**Задачи:**
1. Написать хелпер `_parse_xlsx_to_generic_rows(file_bytes: bytes) -> list[dict]`
   - Читает xlsx через openpyxl
   - Структура стандартизирована, парсим generic «как есть»: первая строка = заголовки, остальные = данные
   - Возвращает строки в формате: `{"row_id": str(uuid), "cells": {"Колонка1": val, ...}}`
   - Edge cases: пустые строки → пропускаем; merged cells → берём верхнюю левую; None-значения → ""; числа → float; даты → ISO-строка

2. В `task_processor.py`: после сохранения TaskResult.result для LIST и COMPLETENESS типов задач — вызвать хелпер и создать начальную EstimateVersion:
   ```
   EstimateVersion(
     task_id=task_id,
     version_number=0,
     version_label="original",
     version_display_name="V0 — Оригинал",
     rows=parsed_rows,
     file_slot="result",
     task_type=task.task_type,
   )
   ```

3. Создать endpoint `POST /tasks/{task_id}/estimate/init-from-result`
   - Если EstimateVersions уже есть для этой задачи (file_slot=result) → возвращает 200 без действий (idempotent)
   - Если нет → парсит TaskResult.result и создаёт V0
   - Используется фронтендом при первом открытии редактора для задач без версий

4. Создать endpoint `POST /tasks/{task_id}/estimate/init-from-input?file_index=0`
   - То же, но из TaskInputFile[file_index]
   - file_slot="input"
   - Возвращает version_id для последующего открытия редактора

5. Обновить `PUT /tasks/{task_id}/estimate/versions/{version_id}/rows`:
   - После сохранения: если version.file_slot == "result" И task_type ∈ LIST/COMPLETENESS types
     → перегенерировать xlsx из обновлённых rows (reverse of _parse_xlsx_to_generic_rows)
     → обновить TaskResult.result (или создать если нет) + обновить size_bytes
     → установить `task.manually_edited_at = now()`
   - Если version.file_slot == "input"
     → перегенерировать xlsx → обновить TaskInputFile[file_index].content
     → установить `task.manually_edited_at = now()`

6. Написать хелпер `_rows_to_xlsx(rows: list[dict]) -> bytes`
   - Обратный к `_parse_xlsx_to_generic_rows`
   - Создаёт xlsx через openpyxl из generic rows

7. Обновить `GET /tasks/{task_id}/estimate/versions` — добавить query param `?file_slot=result` (default) чтобы фронтенд мог запросить версии input-файла отдельно от result

**Важно**: `_parse_xlsx_to_generic_rows` и `_rows_to_xlsx` — НЕ пытаться сопоставить с estimate-колонками. Хранить колонки как есть из xlsx.

**Файлы:**
- `backend/app/services/task_processor.py`
- `backend/app/routers/estimate_versions.py`
- `backend/app/utils/xlsx_generic.py` (новый — хелперы parse/generate)

**Статус:** `[x]`

---

### Фаза 3 — Backend: предупреждения и флаги ручного редактирования
**Цель**: корректно выставлять `manually_edited_at` и возвращать его в API

**Задачи:**
1. ✅ Убедиться что `manually_edited_at` выставляется при сохранении версии для ВСЕХ типов задач — `save_rows` покрывает LIST/COMPLETENESS; добавлено в `save_expenses` и `apply_proposals` для ESTIMATE

2. ✅ `GET /workflow-cards/{card_id}/files-meta` — включает `manually_edited_at` через `_build_stage_meta` (строка 287 workflow_cards.py)

3. ✅ `StageDetail` имеет `manually_edited_at: Optional[str]` (строка 79 schemas/workflow_card.py)

4. Логика определения "устаревших" этапов — чисто фронтенд (уже реализована в ProjectCardPage.tsx через `wasEditedBefore`). Реализовать ту же логику в CardStageContent (→ Фаза 5).

**Файлы:**
- `backend/app/routers/workflow_cards.py` (проверено)
- `backend/app/routers/estimate_versions.py` (добавлен manually_edited_at в save_expenses и apply_proposals)

**Статус:** `[x]`

---

### Фаза 4 — Frontend: адаптация EstimatePage для generic-режима
**Цель**: editor-страница `/tasks/:id/estimate` корректно работает для LIST/COMPLETENESS задач

**Задачи:**
1. В EstimatePage (или где загружается редактор): при загрузке задачи определять task_type
2. Если task_type ∈ LIST/COMPLETENESS types → generic-режим:
   - Скрыть секцию overhead%/transport%/contingency% 
   - Скрыть вкладки "Работы" / "Материалы" (только "Все")
   - Скрыть proposals-панель (оптимизация)
   - Показать generic-колонки из EstimateVersion.rows[i].cells (вместо фиксированных смета-колонок)
3. Если task_type ∈ ESTIMATE types → текущее поведение без изменений
4. URL-параметр `?embed=1` — обеспечить что скрывает навигацию (уже делается)
5. URL-параметр `?file_slot=input` — редактор загружает версии file_slot=input (для исходного файла)

**Найти файл EstimatePage:** вероятно `frontend/src/pages/tasks/EstimatePage.tsx` или аналог — уточнить при реализации.

**Файлы:**
- `frontend/src/pages/tasks/EstimatePage.tsx` (или аналог)
- `frontend/src/stores/estimateEditor.ts` (добавить file_slot в loadVersions)
- `frontend/src/api/estimateVersions.ts` (добавить file_slot query param)

**Статус:** `[x]`

---

### Фаза 5 — Frontend: CardStageContent — collapse/expand + даты + кнопки редактора + предупреждения
**Цель**: основные UI-изменения в канбан-карточках

**Задачи:**

#### 5.1 — API хелпер
- Добавить в `frontend/src/api/workflowCards.ts` функцию `getCardFilesMeta(cardId)`
- Response type: `CardFilesMeta` (соответствует backend schema из Фазы 1)

#### 5.2 — Состояние в CardStageContent
- Добавить локальный state: `filesMeta: CardFilesMeta | null`, `metaLoading: boolean`
- Добавить `expanded: boolean` для каждого блока файлов (начальное значение = true только если есть файлы)
- Загружать `filesMeta` при монтировании карточки (один раз) + обновлять по postMessage `estimate-saved`
- Дедупликация: флаг `metaFetching` чтобы не делать параллельных запросов

#### 5.3 — Collapse/expand UI
- Для каждой стадии: кнопка-заголовок с chevron (аналогично `OptimizationStageContent` в ProjectCardPage.tsx)
- По умолчанию свёрнуто если stадия "ещё не запущена" (нет задачи)
- По умолчанию развёрнуто если есть файлы или предупреждения

#### 5.4 — FileRow внутри CardStageContent
- Скопировать паттерн `FileRow` из ProjectCardPage.tsx (адаптировать для меньшего размера)
- Показывать: имя файла (truncated), размер, дата, кнопки [скачать] [редактор] [задача]
- Кнопка редактора: только для xlsx + только при `task.status === 'completed'`

#### 5.5 — EstimateEditorModal в CardStageContent
- Импортировать `EstimateEditorModal`
- State: `editorModal: {taskId: string, title: string, fileSlot?: string} | null`
- При сохранении (postMessage): перезагрузить filesMeta для этой карточки

#### 5.6 — Кнопки для каждого этапа

**Исходный файл (в ListStage):**
```
filesMeta.source_stage.input_files.forEach(f => FileRow с:
  - скачать → downloadInputFileById(task_id, f.index)
  - редактор → EditorModal с URL /tasks/:id/estimate?embed=1&file_slot=input&file_index=f.index
)
```

**Перечень (в ListStage, когда task.status === 'completed'):**
```
filesMeta.source_stage.result_files.forEach(f => FileRow с:
  - скачать → downloadSlotFileById(task_id, f.slot)
  - редактор → EditorModal /tasks/:id/estimate?embed=1&file_slot=result
)
```

**Проверка полноты (в CompletenessStage):**
```
filesMeta.completeness_stage?.result_files.forEach(f => FileRow ...)
```

**Смета из перечня (в EstimateStage):**
```
filesMeta.estimate_stage?.result_files.forEach(f => FileRow ...)
редактор → EditorModal как сейчас (уже работает)
```

**Оптимизация (в OptimizationStage):**
- Текущая версия: FileRow + кнопка "Открыть смету" → `window.open('/tasks/:id/estimate', '_blank')`
- Архив версий: collapsible список всех `result_files` где slot начинается с "optimized"
- Каждая версия: FileRow с [скачать] [открыть задачу]

#### 5.7 — ManualEditWarning в CardStageContent
```typescript
function wasEditedBefore(editedAt: string | null, nextStageCreatedAt: string | null): boolean {
  if (!editedAt || !nextStageCreatedAt) return false
  return new Date(editedAt) > new Date(nextStageCreatedAt)
}
```
Показывать `ManualEditWarning` (скопировать из ProjectCardPage.tsx) в каждой стадии где предыдущая отредактирована вручную после создания текущей.

**Файлы:**
- `frontend/src/components/kanban/CardStageContent.tsx` (основной файл изменений)
- `frontend/src/api/workflowCards.ts`
- `frontend/src/types/workflow.ts` (добавить типы CardFilesMeta)

**Статус:** `[x]`

---

### Фаза 6 — Frontend: ProjectCardPage — обновление предупреждений
**Цель**: предупреждения на странице карточки покрывают все типы задач, включают конкретный этап

**Задачи:**
1. ✅ ManualEditWarning в Stage 2 (Перечень) — показывается когда source_stage.manually_edited_at установлен (безусловно)
2. ✅ Дата в FileRow для input-файлов — max(task_created_at, manually_edited_at)
3. ✅ 6 парных wasEditedBefore: src→comp, src→est, src→opt, comp→est, comp→opt, est→opt; каждое предупреждение на правильном этапе
4. ✅ Удалён isEstimateType() guard — редактор открывается для всех типов задач (LIST/COMPLETENESS тоже)
5. ✅ Редактор для исходного файла в Stage 1 — добавлен для всех типов с fileSlot='input', fileIndex
6. ✅ editorModal расширен fileSlot/fileIndex; EstimateEditorModal получает параметры

**Файлы:**
- `frontend/src/pages/ProjectCardPage.tsx`

**Статус:** `[x]`

---

### Фаза 7 — Миграция БД
*(уже включена в Фазу 1, вынесена отдельно для порядка)*

Файл: `backend/alembic/versions/019_add_size_bytes_file_slot_task_type.py`

```python
# Псевдокод:
op.add_column('task_results', sa.Column('size_bytes', sa.Integer(), nullable=False, server_default='0'))
op.execute("UPDATE task_results SET size_bytes = octet_length(file_data)")

op.add_column('estimate_versions', sa.Column('file_slot', sa.String(20), nullable=False, server_default='result'))
op.add_column('estimate_versions', sa.Column('task_type', sa.String(50), nullable=True))
```

**Статус:** `[x]`

---

## Правильная последовательность реализации

**Порядок выполнения:** 7 → 1 → 2 → 3 → 4 → 5 → 6

```
Шаг 1: Фаза 7 — Миграция БД
        (добавить size_bytes, file_slot, task_type)
        ↓
Шаг 2: Фаза 1 — Backend: lightweight endpoint files-meta
        (модели + endpoint /workflow-cards/:id/files-meta)
        ↓
Шаг 3: Фаза 2 — Backend: EstimateVersions для LIST/COMPLETENESS
        (парсер xlsx, auto-создание версий, init endpoints, сохранение обратно в result)
        ↓
Шаг 4: Фаза 3 — Backend: manually_edited_at для всех типов
        (проверка и фиксация флага для LIST/COMPLETENESS пути)
        ↓
        ┌─────────────────────────────────────┐
        ↓                                     ↓                          ↓
Шаг 5a: Фаза 4           Шаг 5б: Фаза 5           Шаг 5в: Фаза 6
Frontend: editor          Frontend:                  Frontend:
generic-режим             CardStageContent           ProjectCardPage
(можно параллельно)       (основной UI)              (предупреждения)
        └─────────────────────────────────────┘
```

**Блокирующие зависимости:**
- Фаза 1 блокирует Фазу 5 (нет данных о файлах для UI)
- Фаза 2 блокирует Фазу 4 (нет версий для generic-редактора)
- Фаза 3 блокирует Фазы 5 и 6 (нет флагов редактирования)
- Фазы 4, 5, 6 независимы между собой — можно делать параллельно

---

## Риски и открытые вопросы

| Риск | Вероятность | Митигация |
|---|---|---|
| `_parse_xlsx_to_generic_rows` — структура нестандартная | Снято | Пользователь подтвердил: структура стандартизирована, парсим generic flat |
| Editor-страница сложно адаптируется под generic-режим (много специфичного кода) | Средняя | Если слишком сложно — сделать отдельный маршрут `/tasks/:id/xlsx-view?embed=1` для просмотра без полного редактора |
| `size_bytes` UPDATE при миграции долгий на большой БД | Низкая (внутренний инструмент) | Приемлемо |
| Collapse/expand сбрасывается при poll → пользователь раздражён | Средняя | Хранить expanded state в ref, не в store; не ресетировать при poll |
| URL-параметр `?file_slot=input` для редактора — нужен роутинг в EstimatePage | Средняя | Чтение query params + условная логика loadVersions |

---

## Итоговый блок

Реализован целиком: `[x]`  
Все фазы завершены.

---

## История сессий

- 2026-04-30: план создан (режим bulletproof, planning only)
- 2026-04-30: фаза 4 выполнена — generic-режим и embed-режим в EstimateOptimizer
- 2026-04-30: фаза 5 выполнена — CardStageContent с filesMeta, FileRow, ManualEditWarning, EditorModal; EstimateEditorModal поддерживает fileSlot/fileIndex; getCardFilesMeta в workflowCards.ts
- 2026-04-30: фаза 6 выполнена — ProjectCardPage: 6 парных wasEditedBefore, предупреждения на правильных этапах, редактор для всех типов задач, isEstimateType удалён, дата input-файлов исправлена
- 2026-04-30: аудит — добавлен CollapsibleSection для summary-блоков в CompletenessStage и EstimateStage (критерий 5.3 — collapse/expand); по умолчанию свёрнуто, раскрывается при наличии ManualEditWarning
