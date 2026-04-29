# Research: Канбан-представление проектов

**Дата:** 2026-04-29  
**Задача:** Добавить канбан с 4 стадиями и бизнес-логикой переходов

---

## 1. Существующая архитектура backend

### Модели
- **Project**: id, name, description, created_at, updated_at
- **Task**: id, project_id, task_type, status (pending/processing/completed/failed/cancelled), estimation_status (unestimated/estimated/optimized/not_applicable), input_files, input_file_data, cost, deleted_at
- **TaskResult**: file_data (LargeBinary), slots: `source`, `estimate`, `optimized`, `optimized_vN`, file_name, mime_type

### Типы задач (маппинг на стадии)
| Стадия канбан    | task_type                                              |
|-----------------|-------------------------------------------------------|
| Перечень         | `LIST_FROM_GRAND`, `LIST_FROM_PROJECT`                |
| Полнота          | `CHECK_LIST_COMPLETENESS`, `CHECK_PROJECT_COMPLETENESS`|
| Смета            | `ESTIMATE_FROM_LIST`                                  |
| Оптимизация      | `ESTIMATE_OPTIMIZATION`                               |

### Важная находка
В `ESTIMATE_FROM_LIST` уже существует поле `source_stage` (1 = из перечня, 2 = после полноты) и эндпоинт `/estimate-sources`. Это прямой прецедент бизнес-логики «зависимость от предыдущего результата».

### Хранение результатов
Результаты хранятся в TaskResult через слоты. Перечень → слот `source`. Смета → слот `estimate`. Оптимизация → `optimized` / `optimized_vN`.

---

## 2. Существующая архитектура frontend

### Стек
React 18.3, TypeScript, Vite, Zustand 5, React Router 6, Axios, lucide-react

### Drag-and-drop
**Не установлено ни одной библиотеки.** dnd-kit, react-beautiful-dnd, react-dnd — отсутствуют.

### Текущий UI задач
- `Projects.tsx` — список проектов-карточек
- `ProjectDetail.tsx` — таблица задач проекта (горизонтальный список TaskBrief[])
- Стили — inline styles, никакого CSS-фреймворка

### Zustand stores
- `useAuthStore` — авторизация
- `useEstimateEditorStore` — редактор сметы
- `useTaskSync` — bump-версия для синхронизации

### Компоненты
Есть OptimizeModal (многошаговый), FileUpload, LumaSpin, SectionLoader — всё переиспользуемо для канбана.

---

## 3. Best Practice (WebSearch 2024-2025)

### Выбор drag-and-drop библиотеки
**Победитель: `@dnd-kit/core` + `@dnd-kit/utilities`**

- `react-beautiful-dnd` — **заброшена** Atlassian, нет поддержки, нет планов
- `react-dnd` — устаревшая API, сложная настройка, меньше гибкости
- `@dnd-kit` — современная, tree-shakeable, поддержка a11y, активная разработка, гибкие стратегии collision detection
- `@dnd-kit/sortable` — **не нужен**: он для сортировки внутри одного списка, не для cross-column drag. Сортировка карточек внутри колонки в MVP не поддерживается.

### Паттерн guard conditions при переходе
Лучший подход — **callback-based validation в `onDragEnd`**:
```typescript
type StageGuard = (card: WorkflowCard, from: Stage, to: Stage) => 
  { allowed: boolean; warning?: string }
```
Если `allowed: false` — стейт не обновляется, показывается toast/предупреждение. Если `allowed: true` — переход выполняется, опционально показывается soft-warning.

---

## 4. Модель данных: новая сущность WorkflowCard

Карточка канбана = единица работы по проекту (один «поток обработки» — перечень → полнота → смета → оптимизация).

```python
class WorkflowCard(Base):
    __tablename__ = "workflow_cards"
    id: UUID
    project_id: UUID  # FK → projects.id
    name: str         # название карточки, задаётся пользователем
    stage: str        # "list" | "completeness" | "estimate" | "optimization"
    list_task_id: UUID | None        # FK → tasks.id
    completeness_task_id: UUID | None
    estimate_task_id: UUID | None
    optimization_task_id: UUID | None
    created_at / updated_at: datetime
```

Каждое поле `*_task_id` ссылается на задачу соответствующей стадии. Готовность стадии = задача существует и имеет status=`completed`.

---

## Рекомендация

### Выбранное решение: `@dnd-kit` + новая модель `WorkflowCard` + guard conditions в Zustand

**Почему именно это:**

| Альтернатива | Проблема |
|---|---|
| Нативный HTML5 drag-and-drop | Нет drag-overlay, плохой a11y, сложно кастомизировать |
| `react-beautiful-dnd` | Заброшена, баги с React 18+ concurrent mode |
| Существующий стейт задач без новой модели | Нет понятия «карточка канбана» — нельзя связать задачи разных стадий в один поток |
| Дериватный стейт из существующих задач | Хрупко: задачи можно создавать в любом порядке, нет гарантии связи |

**Что нужно учесть при имплементации:**

1. **Миграция**: Новая таблица `workflow_cards` — обязательна миграция с `IF NOT EXISTS` (следующий номер после последней в alembic/versions/).
2. **Guard conditions — три уровня**: HARD block (нет перечня), SOFT warning (нет полноты, но можно пропустить), INFO (смета из перечня без полноты).
3. **Оптимизация — два источника файла**: либо `estimate_task_id` из карточки, либо загрузка нового файла с ПК (как в существующем EstimateOptimizer).
4. **Существующий ProjectDetail**: Канбан — новый tab/режим на странице проекта, не замена таблицы задач. Переключатель «Список / Канбан».
5. **Стилистика**: Inline styles как везде по проекту — не вводить CSS-модули или Tailwind.
6. **Реиспользовать**: FileUpload, LumaSpin, существующие API-эндпоинты создания задач — только добавить обёртку WorkflowCard сверху.
