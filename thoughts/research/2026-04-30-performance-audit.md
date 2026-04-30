# Performance Audit: smeta-ai — апрель 2026

**Режим:** read-only исследование  
**Метод:** 4 параллельных агента (фронтенд, бэкенд, конфиг/зависимости, WebSearch)  
**Проблемы, которые пользователь ощущает:**
- Медленный сайдбар (список проектов и задач)
- Медленные задачи оптимизации сметы
- Тормозит онлайн-редактор таблиц

---

## Часть 1 — Фронтенд

### 1.1 Сайдбар (ProjectsSidebar.tsx)

**HIGH — Нет пагинации и виртуализации**  
[ProjectsSidebar.tsx:516-544](frontend/src/components/ProjectsSidebar.tsx#L516-L544) — весь список задач всех развёрнутых проектов рендерится сразу. При 100+ задачах — UI замерзает.

**HIGH — Все задачи загружаются при раскрытии**  
[ProjectsSidebar.tsx:111-124](frontend/src/components/ProjectsSidebar.tsx#L111-L124) — `toggleSection()` вызывает `getProject(id)`, который тянет ВСЕ задачи проекта без limit/offset. Сетевой водопад при открытии сайдбара.

**HIGH — taskSyncVersion как глобальная шина событий**  
[ProjectsSidebar.tsx:43](frontend/src/components/ProjectsSidebar.tsx#L43) — любое обновление любой задачи в системе вызывает полный перезапрос всех проектов и всех задач в сайдбаре. Архитектурная проблема: [taskSync.ts](frontend/src/stores/taskSync.ts) — счётчик-версия запускает каскадный refetch.

**MEDIUM-HIGH — Hover-кнопки пересоздаются на каждый рендер**  
[ProjectsSidebar.tsx:733-795](frontend/src/components/ProjectsSidebar.tsx#L733-L795) — `ActionBtn` и `ArrowNavBtn` определены локально в компоненте, не мемоизированы. `ActionBtn` содержит собственный `useState` (hover), что вызывает ре-рендер родителя.

**MEDIUM — 12+ useState в одном компоненте**  
[ProjectsSidebar.tsx:45-62](frontend/src/components/ProjectsSidebar.tsx#L45-L62) — любой из них обновляется → полный ре-рендер.

---

### 1.2 Редактор таблиц / задачи оптимизации

**HIGH — Нет виртуализации строк**  
[EstimateGrid.tsx:457](frontend/src/components/estimate/EstimateGrid.tsx#L457) — `maxHeight: 600` задан, `enableVirtualization` включён, но без явного `rowHeight` виртуализация не активируется. При 500+ строках — все 500 DOM-нод в дереве.

**HIGH — Одно редактирование ячейки перерисовывает всю сетку**  
[EstimateOptimizer.tsx:81-86](frontend/src/pages/EstimateOptimizer.tsx#L81-L86) — `activeRows: EstimateRow[]` (массив 1000+ строк) обновляется целиком при каждом изменении. Нет иммутабельной точечной замены строки, нет мемоизации на уровне строки.

**HIGH — N+1 при загрузке версий**  
[EstimateOptimizer.tsx:54-63](frontend/src/pages/EstimateOptimizer.tsx#L54-L63) — сначала `loadVersions(taskId)`, потом `getVersion(taskId, active.id)` последовательно. Два сетевых round-trip там, где достаточно одного.

**MEDIUM-HIGH — Cell editor пересоздаёт ref на каждый рендер**  
[EstimateGrid.tsx:29-85](frontend/src/components/estimate/EstimateGrid.tsx#L29-L85) — `NumberEditor`, `ConfirmTextEditor` пересоздают `inputRef` при взаимодействии. Следствие: потеря фокуса на больших гридах.

**MEDIUM — Undo-стек: до 50 полных копий массива строк**  
[estimateEditor.ts:9,22-24](frontend/src/stores/estimateEditor.ts#L9) — `MAX_HISTORY = 50`, каждая запись = полная копия `EstimateRow[]`. При 1000 строках — 50–200 MB RAM.

---

### 1.3 Zustand — архитектурная проблема

**HIGH — Kanban-стор без селекторов**  
[kanban.ts:25](frontend/src/stores/kanban.ts#L25) — компоненты подписываются на весь стор: `const { cards, loading, fetchCards, moveCard } = useKanbanStore()`. Обновление одной карточки → ре-рендер ВСЕХ компонентов с этим стором.

**Корень проблемы:** серверные данные (проекты, задачи, версии смет) хранятся в Zustand вручную. Нет дедупликации запросов, нет stale-while-revalidate, нет автоматической инвалидации. Это правильный стор для UI-состояния, но неправильный инструмент для серверного состояния.

---

### 1.4 Роутер — нет разбивки бандла

**HIGH — Все страницы импортируются синхронно**  
[App.tsx:5-16](frontend/src/App.tsx#L5-L16) — `import TaskCreate from './pages/TaskCreate'` и т.д. без `React.lazy()`. Начальный бандл включает весь код всех страниц. По оценке агента — 500KB+.

---

## Часть 2 — Бэкенд

### 2.1 Эндпоинты без пагинации

**HIGH — `GET /projects` возвращает все проекты**  
[projects.py:144-199](backend/app/routers/projects.py#L144-L199) — `(await db.execute(stmt)).all()` без limit. При росте базы — линейная деградация.

**MEDIUM — `GET /projects/{id}` возвращает все задачи проекта**  
[projects.py:230-283](backend/app/routers/projects.py#L230-L283) — нет пагинации на список задач. Проект с 1000 задач → огромный JSON-ответ, который фронтенд всё равно рендерит весь.

**MEDIUM — `GET /tasks/unassigned` — нет limit**  
[projects.py:202-227](backend/app/routers/projects.py#L202-L227) — возвращает ВСЕ неназначенные задачи.

---

### 2.2 Оптимизация сметы — самое медленное место

**HIGH — Батч-размер 4, вызовы последовательные**  
[tasks.py:1185, 1301-1347](backend/app/routers/tasks.py#L1185) — `OPTIMIZATION_BATCH_SIZE = 4`, каждый элемент вызывает `find_work_price()` → отдельный Claude API call. При 5 секундах на вызов: 4 элемента = 20+ секунд.

**HIGH — 1 предмет = 1 Claude API call с web search**  
[price_service.py:135-207](backend/app/services/price_service.py#L135) — `_web_search_work_price()` вызывается для каждого ненайденного предмета индивидуально. 100 предметов = 100 Claude вызовов. Вместо 1 батч-вызова на 100 предметов.

**HIGH — Price service грузит весь прайс-каталог в память**  
[price_service.py:210-288](backend/app/services/price_service.py#L210) — `select(PriceWork)` без limit, затем numpy-матрица embedding'ов. 10k предметов × 1024-dim float32 = 40 MB только на эмбеддинги. Растёт линейно с каталогом.

---

### 2.3 Индексы

**MEDIUM — Нет составного индекса (task_id, slot) на task_results**  
[result.py:8-28](backend/app/models/result.py#L8) — частый запрос `WHERE task_id=? AND slot=?` не может использовать один индекс по `task_id`.

**MEDIUM — Нет индексов на status, task_type, created_at**  
[task.py](backend/app/models/task.py) — эти поля часто используются в фильтрах, но не индексированы. Только `(project_id, estimation_status)` и `deleted_at`.

---

### 2.4 Нет HTTP-кеширования

Ни один GET-эндпоинт не выставляет `Cache-Control`, `ETag` или `Last-Modified`. Каждый рефреш страницы = полный набор запросов к БД.

---

## Часть 3 — Конфигурация и инфраструктура

### КРИТИЧНО: NGINX без gzip

[nginx.conf](frontend/nginx.conf) — нет `gzip on`, нет `gzip_types`. Весь JavaScript и CSS передаются несжатыми. Это самый быстрый выигрыш из всей аудиторской программы: 5 минут правки → 60-80% сокращение объёма передаваемых данных.

### Sourcemaps в продакшене

[vite.config.ts:7](frontend/vite.config.ts#L7) — `sourcemap: true` в сборке. Map-файлы раскрывают исходный код и утяжеляют бандл. Только для dev.

### Uvicorn — один воркер

[docker-compose.yml:32](docker-compose.yml#L32) — `uvicorn ... --reload` без `--workers`. Один процесс не может параллельно обрабатывать несколько запросов. Флаг `--reload` — только для разработки.

### Vite без разбивки чанков

[vite.config.ts](frontend/vite.config.ts) — нет `build.rollupOptions.output.manualChunks`. Иконки lucide-react собираются по одной в отдельные JS-файлы (видно в dist/assets/).

---

## Часть 4 — Best Practices (WebSearch, 2025)

### TanStack Query — стандарт для server state

11.98M downloads/неделю. Решает корень проблемы: server state не должен жить в Zustand.

```ts
const { data: projects } = useQuery({
  queryKey: ['projects'],
  queryFn: fetchProjects,
  staleTime: 30_000,   // из кеша без запроса 30 сек
  gcTime: 5 * 60_000,  // в памяти 5 минут
});
```

Автоматическая дедупликация: 3 компонента вызвали один и тот же запрос → ушёл 1 HTTP-запрос.

### TanStack Virtual — виртуализация строк (2025)

Headless, поддерживает row + column виртуализацию, активно поддерживается. react-window фактически не развивается. react-virtuoso — хорош для dynamic row heights но меньше контроля над DOM.

### Zustand — правильный способ

```ts
// ПЛОХО — новый объект на каждом рендере
const { tasks, setTasks } = useStore(s => ({ tasks: s.tasks, setTasks: s.setTasks }));

// ХОРОШО — атомарные селекторы
const tasks = useStore(s => s.tasks);
const setTasks = useStore(s => s.setTasks);

// Для нескольких значений — useShallow
import { useShallow } from 'zustand/react/shallow';
const { tasks, filter } = useStore(useShallow(s => ({ tasks: s.tasks, filter: s.filter })));
```

### FastAPI — lazy="raise" + явные eager loads

```python
# На модели: запрещает случайный lazy load в async-контексте
tasks: Mapped[list["Task"]] = relationship(lazy="raise")

# В запросе: явно указывать загрузку
stmt = select(Project).options(selectinload(Project.tasks))
```

### Code splitting — route-level, только тяжёлые страницы

```ts
const EstimateOptimizer = React.lazy(() => import('./pages/EstimateOptimizer'));

<Suspense fallback={<PageSkeleton />}>
  <Route path="/optimize/:id" element={<EstimateOptimizer />} />
</Suspense>
```

---

## Сводная таблица по приоритету

| # | Проблема | Файл | Усилие | Эффект |
|---|----------|------|--------|--------|
| 1 | NGINX без gzip | nginx.conf | 5 мин | -70% трафик, быстрее первый paint |
| 2 | Нет TanStack Query (server state в Zustand) | App.tsx + stores | 2-3 дня | Кеш, дедупликация, нет лишних рефетчей |
| 3 | Нет пагинации на /projects, /projects/{id} | projects.py | 1-2 ч | Линейная деградация → константа |
| 4 | taskSyncVersion — каскадный refetch | taskSync.ts | 1 день | Сайдбар не перезагружается при каждом обновлении |
| 5 | Виртуализация строк в EstimateGrid | EstimateGrid.tsx | 3-4 ч | 500 строк → 20 DOM-нод |
| 6 | Code splitting (React.lazy) | App.tsx | 2-3 ч | -30% initial bundle |
| 7 | Zustand — атомарные селекторы | kanban.ts + stores | 1 день | Нет лишних ре-рендеров |
| 8 | 1 предмет = 1 Claude call → батчинг | price_service.py | 1-2 дня | 100 вызовов → 5-10 |
| 9 | Uvicorn — несколько воркеров | docker-compose.yml | 10 мин | Параллельная обработка запросов |
| 10 | Sourcemaps в продакшене | vite.config.ts | 1 мин | Меньше бандл, безопаснее |
| 11 | Составной индекс (task_id, slot) | result.py + миграция | 30 мин | -20% время запросов к результатам |
| 12 | Индексы status, task_type, created_at | task.py + миграция | 30 мин | -10-30% время запросов |
| 13 | Batching size оптимизации (4→16) | tasks.py | 15 мин | 4x пропускная способность батча |

---

## Рекомендация

### Выбранное решение: трёхволновая оптимизация

Не одно решение, а три последовательные волны по принципу «максимальный эффект за минимальные усилия».

---

### Волна 1 — Инфраструктура (1-2 часа, без правки бизнес-логики)

**Сделать сразу:**
1. **Gzip в nginx.conf** — 5 минут, -70% трафик. Не требует изменений кода.
2. **Sourcemaps отключить** — 1 минута.
3. **Uvicorn workers: 4** — 10 минут, параллельная обработка запросов.
4. **Индексы в БД** — 30 минут + миграция. Добавить `(task_id, slot)` на task_results, `status` и `task_type` на tasks.

Эта волна даёт немедленный эффект без риска регрессий.

---

### Волна 2 — Архитектурный фикс фронтенда (1 неделя)

**TanStack Query вместо ручного server-state в Zustand.**

Это главное решение. Почему именно оно:

**vs. «Добавить ручной кеш в Zustand»** — Zustand создан для UI-состояния (что открыто, что выбрано, фильтры). Держать в нём серверные данные означает вручную реализовывать то, что TanStack Query уже решил: дедупликация, stale-while-revalidate, фоновые обновления, инвалидация при мутациях. Результат — тот же taskSyncVersion, только переписанный.

**vs. SWR** — TanStack Query весит 13KB против 4KB у SWR, но для внутреннего инструмента с мутациями (создание задач, сохранение смет) разница несущественна. TanStack Query имеет встроенные devtools, `useMutation` с автоматической инвалидацией, infinite queries для пагинации — SWR базово поддерживает это, но менее удобно.

**Что это решает одним изменением:**
- Сайдбар перестаёт refetch при каждом обновлении задачи (staleTime)
- Дедупликация: если сайдбар и страница проекта оба хотят проект — уходит 1 запрос
- taskSyncVersion и ручные `loadData()` становятся ненужными
- Zustand остаётся только для UI-состояния (раскрытые секции, выбранные строки, фильтры)

**Параллельно:**
- Пагинация на `/projects` и `/projects/{id}` — cursor-based, infinite query на фронте
- React.lazy для тяжёлых страниц (EstimateOptimizer, AdminPanel)
- Атомарные селекторы в оставшихся Zustand-сторах

---

### Волна 3 — Табличный редактор и оптимизация (3-5 дней)

**TanStack Table + TanStack Virtual для EstimateGrid.**

Текущий `react-data-grid@7.0.0-beta.47` (бета!) заменяется или виртуализация настраивается точечно. TanStack Virtual — стандарт 2025 (12M downloads/неделю), headless, поддерживает одновременную виртуализацию строк и столбцов.

**Что нужно учесть при реализации:**
- TanStack Virtual в `<table>` (не `<div>`) имеет edge-кейсы с CSS — использовать div-based layout
- Обновление одной строки должно меняться иммутабельно: `rows.map(r => r.id === id ? { ...r, ...changes } : r)`, а не splice/push
- Undo-стек нужно ограничить дельтами, не полными копиями (Issue: 50-200 MB RAM при MAX_HISTORY=50 на большой смете)

**Claude API батчинг для оптимизации:**
- Вместо 1 call на 1 предмет → батч-запрос на 20-50 предметов в одном prompt
- Снизит время оптимизации с минут до секунд при том же качестве

---

### Что учесть при имплементации

1. **TanStack Query вводить постепенно** — начать с одного эндпоинта (например, `/projects`), убедиться что работает, потом расширять. Не переписывать всё сразу.
2. **Пагинацию вводить с версионированием API** — если фронтенд ожидает полный массив, а бэкенд вдруг отдаёт paginated response, будет регрессия.
3. **Виртуализацию проверять с реальными данными** — пустая таблица не раскроет проблемы с rowHeight и scrollTo.
4. **Gzip включить первым** — нулевой риск, мгновенный эффект на всё приложение.
5. **Bundle analyzer запустить до и после** — `npx vite-bundle-analyzer` покажет реальный размер и эффект code splitting.
