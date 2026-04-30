# Performance Optimization — smeta-ai

**Дата:** 2026-04-30  
**Основание:** `thoughts/research/2026-04-30-performance-audit.md`  
**Тип:** L (архитектурные изменения, 10+ файлов)  
**Режим:** Три последовательные волны

---

## Проблемы, которые решаем

Пользователь ощущает три узких места:

1. **Медленный сайдбар** — при раскрытии проекта подтягиваются ВСЕ задачи; любое обновление любой задачи перезапрашивает весь список (`taskSyncVersion`).
2. **Тормозит редактор таблиц** — все 500+ строк в DOM; одна правка перерисовывает весь грид; 50 полных копий массива в undo-стеке.
3. ~~Медленная оптимизация сметы~~ — исключено из этого плана.

---

## Acceptance Criteria

| # | Критерий | Волна |
|---|----------|-------|
| AC-1 | Сайдбар раскрывается < 300 мс при любом кол-ве задач | 2 |
| AC-2 | Сайдбар не перезапрашивает данные при обновлении задачи в другом компоненте | 2 |
| AC-3 | Первая загрузка страницы — transfer size < 500 KB (сейчас 500+ KB) | 2 |
| AC-4 | Редактор таблицы работает плавно (no jank) при 500+ строках | 3 |
| AC-5 | Редактирование одной ячейки не перерисовывает соседние строки | 3 |
| AC-6 | Сервер принимает несколько одновременных запросов (сейчас 1 воркер) | 1 |
| AC-7 | Повторный визит к той же странице не делает новый запрос к БД в течение 30 с | 2 |

---

## Challenge Log

### 1. РЕШАЕТ ЛИ ЭТО ПРОБЛЕМУ?

Маппинг каждого acceptance criterion на конкретные задачи плана:

| AC | Задача, которая его закрывает |
|----|-------------------------------|
| AC-1 | Волна 2: TanStack Query кеш + точечная инвалидация по projectId |
| AC-2 | Волна 2: замена `taskSyncVersion` на QueryClient.invalidateQueries точечно по ID |
| AC-3 | Волна 2: React.lazy для EstimateOptimizer/Admin/PriceCatalog |
| AC-4 | Волна 3: `rowHeight={35}` + фиксированная высота контейнера → активирует встроенную виртуализацию react-data-grid |
| AC-5 | Волна 3: иммутабельное обновление строки через `patchRow` |
| AC-6 | Волна 1: uvicorn `--workers 4` (uvicorn 0.32.1 поддерживает флаг), убрать `--reload` из продакшн-команды |
| AC-7 | Волна 2: TanStack Query `staleTime: 30_000` на projects и tasks |

**Вывод:** Все 7 критериев покрыты. Пробелов нет.

---

### 2. САМОЕ ЛИ ЭФФЕКТИВНОЕ РЕШЕНИЕ?

#### Проблема сайдбара (server state management)

| Подход | Плюсы | Минусы | Усилие |
|--------|-------|--------|--------|
| **TanStack Query** (выбран) | Индустриальный стандарт; автоматическая дедупликация, stale-while-revalidate, devtools, `useMutation` + инвалидация по ключу | +13 KB bundle; требует миграции всех запросов | 3-4 дня |
| SWR | Легче (4 KB) | Нет `useMutation`, нет devtools, менее удобная инвалидация при мутациях | 2-3 дня |
| Ручной кеш в Zustand | Нет новых зависимостей | Заново решаем то, что TanStack Query уже решил — тот же `taskSyncVersion`, только переписанный | 5+ дней + будущие баги |

**Почему TanStack Query:** у нас много мутаций (создание задач, сохранение смет, перемещение карточек). `useMutation` + `invalidateQueries` — это именно тот паттерн, который нужен.

**Пагинация не нужна:** задач в проекте обычно 10-50. Медленный сайдбар вызван не количеством задач, а глобальным `taskSyncVersion`, который перезапрашивает все проекты при любом изменении. TanStack Query с точечной инвалидацией устраняет проблему без усложнения API.

#### Проблема редактора (виртуализация)

| Подход | Плюсы | Минусы | Усилие |
|--------|-------|--------|--------|
| **Починить встроенную виртуализацию** (выбран) | Нет новых зависимостей; 2 строки кода; механизм полностью реализован в библиотеке | Зависим от бета-версии библиотеки | 15 минут |
| TanStack Virtual | Headless, активно поддерживается | Требует перехода на `div`-based layout; неделя работы | 5 дней |
| react-window | Простой API | Фактически заброшен | 1 день |

**Почему встроенная виртуализация:** исследование исходного кода `react-data-grid@7.0.0-beta.47` показало, что `enableVirtualization` полностью реализован и работает. Баг — одна строка в нашем коде: `blockSize: 'auto'` переопределяет дефолтный `block-size: 350px` из CSS библиотеки. Грид расширяется до полного контента, `ResizeObserver` измеряет 17 500px вместо 600px, `clientHeight` = вся таблица → все строки в диапазоне видимых.

~~Батчинг Claude API — исключён из плана по решению владельца.~~

---

### 3. ЕСТЬ ЛИ «КОД РАДИ КОДА»?

Проверка каждого изменения против AC:

- ✅ uvicorn workers → AC-6
- ✅ DB индексы → косвенно AC-1 (ускоряют запросы к задачам)
- ✅ TanStack Query → AC-2, AC-7
- ✅ React.lazy → AC-3
- ✅ Атомарные selectors Zustand → AC-2 (нет лишних ре-рендеров)
- ✅ `rowHeight={35}` + вычисляемая высота → AC-4
- ✅ Иммутабельные строки (`patchRow`) → AC-5
- ✅ Undo stack дельтами → AC-4 (RAM)
- ~~sourcemap off~~ — перенесён в «Что НЕ входит» (см. ниже)
- ~~gzip nginx~~ — не нужен (см. ниже)
- ~~Claude batch~~ — исключён

**Drive-by рефакторинг вынесен в отдельный список** в секции "Что НЕ входит в этот план".

---

## Что НЕ входит в этот план

- **NGINX gzip** — Render.com деплоит фронтенд как Static Site (CDN), который автоматически отдаёт gzip/brotli. Правка `nginx.conf` не влияет на прод (`nginx.conf` используется только в `docker-compose.yml` для локала).
- **Sourcemaps off** — перенести в отдельную задачу; не связано с AC.
- **Пагинация бэкенда** — задач в проекте 10-50, проблема решается TanStack Query без усложнения API.
- Рефакторинг `ProjectsSidebar.tsx` на `useReducer` / выделение подкомпонентов (отдельная задача)
- Замена `react-data-grid` на другую библиотеку — встроенная виртуализация достаточна
- HTTP-кеширование на бэкенде (`ETag`, `Cache-Control`) — TanStack Query решает эту задачу на клиенте
- Оптимизация `price_service.py` (40 MB матрица, батчинг Claude) — отдельный план
- Батчинг Claude API — исключён по решению владельца

---

## Edge Cases — полный список

### Волна 1

**uvicorn workers:**
- ❗ `--reload` несовместим с `--workers > 1` — uvicorn откажет. Обязательно убрать `--reload` из продакшн-команды. В `docker-compose.yml` (dev) оставить `--reload`, в `render.yaml` (прод) указать `--workers 4`.
- ❗ uvicorn 0.32.1 — флаг `--workers` поддерживается начиная с 0.20, версия подтверждена.
- ❗ In-memory кеш price_service (numpy матрица) будет в каждом из 4 воркеров = 4 × 40 MB = 160 MB. Render Starter имеет 512 MB — в пределах лимита. При необходимости снизить до 2 воркеров.

**DB индексы:**
- ❗ Создавать `CONCURRENTLY` — не блокирует таблицу при существующих данных.
- ❗ `IF NOT EXISTS` — обязательно по правилам проекта.
- ❗ `CONCURRENTLY` нельзя использовать внутри транзакции. Паттерн Alembic (использовать в теле `upgrade()`):
  ```python
  def upgrade():
      connection = op.get_bind()
      connection = connection.execution_options(isolation_level="AUTOCOMMIT")
      connection.execute(text("CREATE INDEX CONCURRENTLY IF NOT EXISTS ..."))
  ```
- ❗ Индекс на `status` в tasks: B-tree индекс эффективен только при фильтрации по конкретному значению. Проверить планы запросов через `EXPLAIN ANALYZE` после.

### Волна 2

**TanStack Query:**
- ❗ Миграция постепенная: если один эндпоинт перешёл на `useQuery`, а другой всё ещё обновляет Zustand вручную, данные могут расходиться. Порядок миграции: начать с `/projects` (список), затем `/projects/{id}`, затем убрать `taskSyncVersion`. Не смешивать оба подхода в одном компоненте.
- ❗ `staleTime: 30_000` означает, что после создания задачи пользователь 30 секунд может видеть устаревший список. Решение: после каждой мутации (createTask, updateTask) вызывать `queryClient.invalidateQueries(['tasks', projectId])` явно.
- ❗ При потере соединения TanStack Query не делает refetch. Нужен `networkMode: 'always'` или `online` в зависимости от поведения внутренней сети.
- ❗ Конкурентный refetch: пользователь открыл два таба — QueryClient разные, данные не синхронизированы. Для внутреннего инструмента — приемлемо, не решаем.
- ❗ `gcTime` по умолчанию 5 мин. Если пользователь переходит между страницами быстро — данные в кеше. Это корректное поведение.

**Code splitting:**
- ❗ `React.lazy` + `Suspense`: если загрузка чанка упала (сетевая ошибка), `Suspense` покажет `fallback` бесконечно. Обернуть в `ErrorBoundary` с кнопкой "Обновить страницу". Проверить наличие `ErrorBoundary` в проекте перед задачей.
- ❗ Тяжёлые кандидаты для splitting: `EstimateOptimizer` (самая тяжёлая), `Admin`, `PriceCatalog`. `Login`, `TaskCreate`, `TaskStatus`, `Projects` — оставить синхронными.

**Zustand атомарные selectors:**
- ❗ `useShallow` из `zustand/react/shallow` нужен при деструктуризации нескольких значений. Без него при любом изменении стора — ре-рендер, даже если нужные поля не изменились.
- ❗ Применять ко всем Zustand-сторам: `kanban.ts`, UI-сторы. Kanban.ts включён в эту волну.

### Волна 3

**Виртуализация в EstimateGrid (встроенная react-data-grid):**
- ❗ `rowHeight={35}` — фиксированная высота строки. Если пользователь вставит многострочный текст в ячейку, строка будет обрезать содержимое. Политика: `overflow: hidden; text-overflow: ellipsis` на ячейках — уже есть в EstimateGrid.css, проверить.
- ❗ Высота контейнера: `Math.max(Math.min(35 * displayedRows.length + 37, 600), 300)` — минимум 300px (сохраняет текущее поведение), максимум 600px. `displayedRows` — локальная переменная компонента, доступна в scope рядом с `<DataGrid>`.
- ❗ При переключении таба высота перевычисляется — это ожидаемое поведение, анимации нет.
- ❗ `selectedRowIds` хранит ID, не индексы — работает корректно при виртуализации.
- ❗ Если смета пустая (0 строк) — `Math.max(37, 300) = 300px` — показывается хедер с пустым пространством. Корректно.

**Иммутабельное обновление строк:**
- ❗ `patchRow(id, changes)` обновляет одну строку: `activeRows.map(r => r.id === id ? {...r, ...changes} : r)` — нетронутые строки сохраняют ту же ссылку. DataGrid видит изменение только у одной строки.
- ❗ `React.memo` на строках **не применять** — `renderRow` в EstimateGrid использует `useCallback([], [])` и рендерит строки через react-data-grid напрямую. Реальный эффект даёт только иммутабельное обновление ссылок, не memo-обёртки.

**Undo stack дельтами:**
- ❗ Правка одной ячейки через `updateRows` передаёт весь `rows` массив. Для вычисления дельты: `newRows.filter((r, i) => r !== activeRows[i])` — даёт изменённые строки (порядок строк react-data-grid не меняет при правке ячейки).
- ❗ Удаление строк: дельта `RowDeleteDelta` хранит **полные объекты** удалённых строк. При восстановлении вставлять по `afterId` (ID строки, после которой вставлять).
- ❗ После `reset()` (смена версии) — стек очищается. `setActiveVersion` уже обнуляет `undoStack: [], redoStack: []` — проверить что новый код сохраняет это.


---

## Фазы реализации

### Фаза 1 — Волна 1: Инфраструктура `[ ]`

**Цель:** Быстрые win-ы без изменения бизнес-логики. Нулевой риск регрессий.  
**Оценка:** 1–2 часа.  
**Acceptance criteria:** AC-6.

#### 1.1 Uvicorn workers в продакшене `[ ]`
- Файл: `render.yaml`
- Команда запуска: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 4`
- `docker-compose.yml` (dev): оставить `--reload` без изменений
- **Проверка:** логи Render.com показывают 4 процесса uvicorn.
- **Edge case:** убрать `--reload` из продакшн-команды — несовместимо с `--workers`.
- **Edge case:** 4 воркера × ~40 MB (numpy матрица) = ~160 MB. Render Starter 512 MB — в пределах лимита.

#### 1.2 DB индексы `[ ]`
- Создать миграцию `backend/alembic/versions/019_add_performance_indexes.py`
- Шаблон: смотреть `013_add_composite_index_tasks_project_estimation.py`
- Добавить (с паттерном AUTOCOMMIT для CONCURRENTLY):
  ```python
  from alembic import op
  from sqlalchemy import text

  def upgrade():
      connection = op.get_bind()
      connection = connection.execution_options(isolation_level="AUTOCOMMIT")
      connection.execute(text(
          "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_task_results_task_id_slot "
          "ON task_results (task_id, slot)"
      ))
      connection.execute(text(
          "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_tasks_status "
          "ON tasks (status) WHERE deleted_at IS NULL"
      ))
      connection.execute(text(
          "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_tasks_task_type "
          "ON tasks (task_type) WHERE deleted_at IS NULL"
      ))

  def downgrade():
      connection = op.get_bind()
      connection = connection.execution_options(isolation_level="AUTOCOMMIT")
      connection.execute(text("DROP INDEX CONCURRENTLY IF EXISTS ix_task_results_task_id_slot"))
      connection.execute(text("DROP INDEX CONCURRENTLY IF EXISTS ix_tasks_status"))
      connection.execute(text("DROP INDEX CONCURRENTLY IF EXISTS ix_tasks_task_type"))
  ```
- **Проверка:** `EXPLAIN ANALYZE SELECT * FROM tasks WHERE status = 'processing'` → `Index Scan` вместо `Seq Scan`.

---

### Фаза 2 — Волна 2: Архитектура фронтенда `[ ]`

**Цель:** Устранить архитектурную причину медленного сайдбара — server state в Zustand.  
**Оценка:** 4–6 дней.  
**Acceptance criteria:** AC-1, AC-2, AC-3, AC-7.

#### 2.1 Установка TanStack Query `[ ]`
- `npm install @tanstack/react-query @tanstack/react-query-devtools`
- Обернуть `<App />` в `<QueryClientProvider client={queryClient}>` в `main.tsx`
- `QueryClient` с глобальными defaults: `staleTime: 30_000, gcTime: 300_000, retry: 1`
- Devtools подключить только в dev-режиме (`import.meta.env.DEV`)

#### 2.2 Миграция `/projects` на TanStack Query `[ ]`
- Создать `frontend/src/queries/projects.ts` с хуками:
  - `useProjects()` — `useQuery(['projects'], fetchProjects, { staleTime: 30_000 })`
  - `useProject(id)` — `useQuery(['project', id], () => fetchProject(id))`
- Удалить или изолировать соответствующий код из Zustand-стора (не удалять полностью до финала миграции)
- Компоненты: `Projects.tsx`, `ProjectsSidebar.tsx` (проектная часть)
- **Примечание:** простой `useQuery`, не `useInfiniteQuery` — проектов десятки, пагинация не нужна.

#### 2.3 Замена taskSyncVersion `[ ]`
- Файл: `frontend/src/stores/taskSync.ts`
- Убрать глобальный `version` счётчик из всех компонентов
- Вместо `bump()` после мутации → `queryClient.invalidateQueries(['tasks', projectId])`
- Компоненты, которые слушают `taskSyncVersion`: `ProjectsSidebar.tsx:43`, `Admin.tsx:249`, `Trash.tsx:30` — заменить на invalidation
- **Проверка:** создать задачу → сайдбар обновляется без полного перезапроса всех проектов

#### 2.4 Code splitting (React.lazy) `[ ]`
- Файл: `frontend/src/App.tsx`
- Добавить lazy imports для тяжёлых страниц:
  ```ts
  const EstimateOptimizer = React.lazy(() => import('./pages/EstimateOptimizer'));
  const Admin = React.lazy(() => import('./pages/Admin'));
  const PriceCatalog = React.lazy(() => import('./pages/PriceCatalog'));
  ```
- Обернуть в `<Suspense fallback={<PageSkeleton />}>` + `ErrorBoundary` (проверить наличие в проекте перед задачей)
- Оставить синхронными: `Login`, `TaskCreate`, `TaskStatus`, `Projects`
- **Проверка:** `npm run build` → каждая lazy страница — отдельный chunk в `dist/assets/`

#### 2.5 Zustand — атомарные selectors `[ ]`
- Сторы: `kanban.ts`, UI-сторы
- Заменить деструктуризацию `const { a, b } = useStore(s => ({a: s.a, b: s.b}))` на:
  ```ts
  import { useShallow } from 'zustand/react/shallow';
  const { a, b } = useStore(useShallow(s => ({ a: s.a, b: s.b })));
  ```
- **Проверка:** React DevTools Profiler — компоненты не перерисовываются при несвязанных изменениях стора

---

### Фаза 3 — Волна 3: Редактор таблиц `[ ]`

**Цель:** Устранить тормоза в EstimateGrid.  
**Оценка:** 1–2 дня.  
**Acceptance criteria:** AC-4, AC-5.

#### 3.1 Активация виртуализации в EstimateGrid `[ ]`

**Контекст исследования:** `enableVirtualization` в `react-data-grid@7.0.0-beta.47` полностью реализован. Баг — одна строка в нашем коде. `blockSize: 'auto'` в `style` переопределяет дефолтный `block-size: 350px` из CSS библиотеки. Грид расширяется до полного контента → `ResizeObserver` измеряет полную высоту (~17 500px для 500 строк) → `clientHeight` = вся таблица → виртуализация рендерит все строки.

- Файл: `frontend/src/components/estimate/EstimateGrid.tsx`
- **Изменение 1:** добавить проп `rowHeight={35}` к `<DataGrid>`
- **Изменение 2:** заменить `style={{ blockSize: 'auto', minHeight: 300, maxHeight: 600 }}` на:
  ```tsx
  style={{ blockSize: Math.max(Math.min(35 * displayedRows.length + 37, 600), 300) }}
  ```
  - Минимум 300px (сохраняет текущее поведение при малом кол-ве строк)
  - Максимум 600px → виртуализация активируется при 16+ строках
  - `+37` = высота хедера
- **Нет новых зависимостей. Нет изменений разметки.**
- **Проверка:** открыть смету с 500+ строками → DevTools → Elements → считать `<div role="row">` в DOM: должно быть ≤ 25 (overscan 4 с каждой стороны + видимые)

#### 3.2 Иммутабельное обновление строк `[ ]`
- Файл: `frontend/src/stores/estimateEditor.ts`
- Добавить хелпер `patchRow(id, changes)`:
  ```ts
  patchRow: (id: string, changes: Partial<EstimateRow>) => {
    const { activeRows, undoStack } = get();
    const newRows = activeRows.map(r => r.id === id ? { ...r, ...changes } : r);
    set({ activeRows: newRows, undoStack: [...undoStack.slice(-(MAX_HISTORY - 1)), activeRows], redoStack: [], isDirty: true });
  }
  ```
- Нетронутые строки сохраняют ту же ссылку → DataGrid видит изменение только у одной строки
- **React.memo на строках — не применять** (renderRow уже стабилен через useCallback, реальный эффект даёт только иммутабельность ссылок)
- **Проверка:** React Profiler → при изменении одной ячейки «highlighted» только одна строка

#### 3.3 Undo stack — дельты вместо полных копий `[ ]`

**Контекст:** текущий `deleteRows` уже корректно сохраняет весь `activeRows` перед удалением. При переходе на дельты удалённые строки хранятся в дельте явно, поведение идентично.

- Файл: `frontend/src/stores/estimateEditor.ts`
- Текущий тип: `undoStack: EstimateRow[][]` → новый тип:
  ```ts
  type RowEditDelta   = { type: 'edit';   id: string; before: Partial<EstimateRow>; after: Partial<EstimateRow> };
  type RowDeleteDelta = { type: 'delete'; rows: EstimateRow[] };
  type RowInsertDelta = { type: 'insert'; rows: EstimateRow[]; afterId: string | null };
  type UndoEntry = RowEditDelta[] | RowDeleteDelta | RowInsertDelta;
  ```
- `updateRows` (правка ячейки): вычислить diff `newRows.filter((r, i) => r !== activeRows[i])`, сохранить `RowEditDelta[]`
- `deleteRows`: `delta = { type: 'delete', rows: activeRows.filter(r => toDelete.has(r.id)) }`
- `undo()` для delete: восстановить строки по `afterId`
- `redo()` для delete: удалить строки по ID
- **Проверка:** 50 правок на 1000-строчной смете → heap snapshot < 10 MB для undo стека (vs 200 MB сейчас)


---

## Порядок деплоя

1. Волна 1 (инфраструктура) → деплой → проверить AC-6 (воркеры в логах)
2. Волна 2 (фронтенд) → деплой пофиче через feature branches → проверить AC-1, AC-2, AC-7
3. Волна 3 (редактор) → деплой → проверить AC-4, AC-5

Каждая волна — отдельный PR. Не сливать до прохождения gates.

---

## Deterministic Gates

### После каждой фазы (обязательно):
```bash
# Frontend
cd frontend && npx tsc --noEmit
cd frontend && npm run lint
cd frontend && npm test

# Backend
cd backend && pytest --tb=short -q
cd backend && ruff check .
```

### После Волны 2 (дополнительно):
```bash
cd frontend && npm run build
npx vite-bundle-visualizer  # сравнить initial bundle до и после
```

### После Волны 3 (дополнительно):
- Открыть смету с 500+ строками, проверить DevTools: ≤ 25 DOM-нод строк
- Heap snapshot undo стека после 50 правок: < 10 MB

---

## Статус

| Фаза | Статус | Дата завершения |
|------|--------|-----------------|
| 1.1 Uvicorn workers | `[ ]` | — |
| 1.2 DB индексы | `[ ]` | — |
| 2.1 TanStack Query setup | `[ ]` | — |
| 2.2 Миграция /projects | `[ ]` | — |
| 2.3 Замена taskSyncVersion | `[ ]` | — |
| 2.4 Code splitting | `[ ]` | — |
| 2.5 Zustand selectors | `[ ]` | — |
| 3.1 Активация виртуализации (2 строки) | `[ ]` | — |
| 3.2 Иммутабельные строки (patchRow) | `[ ]` | — |
| 3.3 Undo stack дельты | `[ ]` | — |

---

## Итог

Реализован: нет (план создан, скорректирован после стресс-теста)  
Осталось: 10 задач  
Следующий шаг: выполнить Фазу 1 (Волна 1) — 1–2 часа, нулевой риск, немедленный эффект на бэкенд.
