# Канбан-представление проектов

**Дата:** 2026-04-29  
**Статус:** реализован  
**Research:** `thoughts/research/2026-04-29-kanban-view.md`

## Суть задачи

Добавить в страницу проекта новый режим отображения — канбан с 4 стадиями и бизнес-логикой переходов. Карточка канбана = один «поток обработки» документа (перечень → полнота → смета → оптимизация). Существующий таблично-списковый вид остаётся, добавляется переключатель «Список / Канбан».

## Архитектура решения

### Новая сущность: WorkflowCard
Карточка связывает задачи разных стадий в один поток:
- `id`, `project_id`, `name`, `stage` (current)
- `list_task_id`, `completeness_task_id`, `estimate_task_id`, `optimization_task_id`

### Drag-and-drop
`@dnd-kit/core` + `@dnd-kit/utilities` — для cross-column drag нужен только core.  
`@dnd-kit/sortable` **не устанавливать** — он для сортировки внутри одного списка. Сортировка карточек внутри колонки в MVP не поддерживается. Карточки упорядочены по дате создания, новые внизу.

### Guard conditions
Валидация при попытке перетащить карточку в другую колонку. Guard проверяет строго `status === 'completed'` — любой другой статус (pending, processing, failed, cancelled) = блокировка с разным сообщением.

| Переход | Условие | Тип |
|---|---|---|
| Перечень → Полнота | list_task.status === 'completed' | HARD block |
| * → Смета | list_task.status === 'completed' | HARD block |
| * → Смета | completeness_task отсутствует/не completed | SOFT (можно пропустить) |
| * → Оптимизация | — | Всегда разрешён (смету можно загрузить с ПК) |

**Важно:** переход в Оптимизацию не требует ни перечня, ни сметы — пользователь может прийти туда сразу и загрузить файл с ПК. Поэтому guard на list_task для Оптимизации отсутствует.

### Ключевые решения по edge cases
- **Атомарный start-task**: вместо двух отдельных запросов (createTask + linkTask) — один endpoint, который создаёт задачу и обновляет карточку в одной транзакции.
- **Pessimistic update**: карточка не двигается в UI до `200 OK` от сервера. DragOverlay показывает призрак, оригинал остаётся на месте.
- **Soft delete защита**: при GET фильтровать задачи по `deleted_at IS NULL`; если task удалён — возвращать null в response без записи в БД.

---

## Фазы

### Фаза 1: Backend — модель WorkflowCard и API [x]

**1.1 — Модель** `backend/app/models/workflow_card.py`

```
id              UUID PK default gen_random_uuid()
project_id      UUID FK(projects.id, ON DELETE CASCADE) NOT NULL
name            VARCHAR(255) NOT NULL
stage           VARCHAR(20) NOT NULL default 'list'
                CHECK (stage IN ('list','completeness','estimate','optimization'))
list_task_id            UUID FK(tasks.id, ON DELETE SET NULL) nullable
completeness_task_id    UUID FK(tasks.id, ON DELETE SET NULL) nullable
estimate_task_id        UUID FK(tasks.id, ON DELETE SET NULL) nullable
optimization_task_id    UUID FK(tasks.id, ON DELETE SET NULL) nullable
created_at      TIMESTAMPTZ default now()
updated_at      TIMESTAMPTZ default now()  ← onupdate=lambda: datetime.now(timezone.utc) ОБЯЗАТЕЛЕН
```

Замечание по FK: `ON DELETE SET NULL` на task-полях актуален только при hard delete задачи (которого сейчас нет — только soft delete). Реальная защита от soft delete реализована в Python-коде сервиса. Оставляем для будущей совместимости.

**Обязательные relationship() в модели** (без них selectinload не скомпилируется):
```python
from sqlalchemy.orm import relationship, Mapped, mapped_column
from typing import Optional

class WorkflowCard(Base):
    __tablename__ = "workflow_cards"

    # ... колонки ...

    # lazy="raise" — запрещает случайные N+1; загрузка только через selectinload
    list_task: Mapped[Optional["Task"]] = relationship(
        "Task", foreign_keys=[list_task_id], lazy="raise"
    )
    completeness_task: Mapped[Optional["Task"]] = relationship(
        "Task", foreign_keys=[completeness_task_id], lazy="raise"
    )
    estimate_task: Mapped[Optional["Task"]] = relationship(
        "Task", foreign_keys=[estimate_task_id], lazy="raise"
    )
    optimization_task: Mapped[Optional["Task"]] = relationship(
        "Task", foreign_keys=[optimization_task_id], lazy="raise"
    )
```

**1.2 — Миграция** `backend/alembic/versions/017_add_workflow_cards.py`
- `CREATE TABLE IF NOT EXISTS workflow_cards`
- Индекс: `CREATE INDEX IF NOT EXISTS idx_workflow_cards_project_id ON workflow_cards(project_id)`
- Шаблон брать из `016_add_task_soft_delete.py`

**1.3 — Схемы Pydantic** `backend/app/schemas/workflow_card.py`

Проект использует Pydantic v2 (pydantic-settings==2.6.1). Использовать `@field_validator` с декоратором `@classmethod` — `@validator` в Pydantic v2 устарел и не работает.

```python
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal
from uuid import UUID
from datetime import datetime

class WorkflowCardCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)

    @field_validator('name', mode='before')
    @classmethod
    def strip_name(cls, v):
        v = str(v).strip()
        if not v:
            raise ValueError('name cannot be empty or whitespace')
        return v

# stage валидируется через Literal → FastAPI вернёт 422 на невалидное значение
class WorkflowCardUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    stage: Optional[Literal['list', 'completeness', 'estimate', 'optimization']] = None

# Response: task-поля могут быть None если задача soft-deleted или не создана
class WorkflowCardResponse(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    stage: str
    list_task_id: Optional[UUID]
    completeness_task_id: Optional[UUID]
    estimate_task_id: Optional[UUID]
    optimization_task_id: Optional[UUID]
    # Вложенные объекты: None если задача удалена (soft delete) или ещё не создана
    list_task: Optional[TaskBrief]
    completeness_task: Optional[TaskBrief]
    estimate_task: Optional[TaskBrief]
    optimization_task: Optional[TaskBrief]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
```

**1.4 — Роутер** `backend/app/routers/workflow_cards.py`

```
GET  /api/projects/{project_id}/workflow-cards
     → проверить что project существует (404 если нет)
     → selectinload все 4 task-поля (relationship() на модели — обязателен, см. п. 1.1)
     → selectinload загружает задачи по FK безусловно; фильтрация soft-delete — в Python-коде:
       после загрузки для каждой карточки: если task.deleted_at is not None → обнулить атрибут
       (task_obj.deleted_at check, не SQL WHERE — selectinload не поддерживает WHERE-фильтр на атрибуте)
     → сортировка: .order_by(WorkflowCard.created_at.asc()) — карточки по порядку создания
     → limit=100 (hard cap, без пагинации для MVP)

POST /api/projects/{project_id}/workflow-cards
     → проверить project существует (404)
     → валидация name через Pydantic (strip, min/max length)
     → создать карточку со stage='list'

PATCH /api/workflow-cards/{card_id: UUID}
     → UUID тип в path → FastAPI 422 на невалидный UUID
     → если передаётся *_task_id: проверить task.project_id == card.project_id (400 если нет)
     → если передаётся *_task_id: проверить task.deleted_at IS NULL (400 если удалена)
     → обновить поля

DELETE /api/workflow-cards/{card_id: UUID}
     → 404 если не найдена
     → удалить карточку; связанные задачи НЕ удаляются (остаются в БД, доступны через список задач)

POST /api/workflow-cards/{card_id: UUID}/start-task
     → АТОМАРНЫЙ endpoint
     → Принимает multipart/form-data: task_type=Form(...), source_stage=Form(None), file=UploadFile(None)
     → Зависимость: current_user: dict = Depends(get_current_user)
     → user_role = current_user.get("role", "user") — поле "role" гарантированно есть в JWT-payload (см. auth.py:26)
     → В одной транзакции:
        1. Создать Task:
           - project_id берётся из card.project_id
           - Для ESTIMATE_FROM_LIST: если source_stage == 2 → source_task_id = card.completeness_task_id,
             иначе source_task_id = card.list_task_id; user_prompt = json.dumps({
               "path": "B", "source_task_id": "...", "source_stage": 1|2
             }) — формат совпадает с существующим POST /tasks/ Path B
           - Для ESTIMATE_OPTIMIZATION без file (use_previous_stage=True в форме):
             → загрузить TaskResult(task_id=card.estimate_task_id, slot='estimate')
             → скопировать file_data в новую задачу как файл
             → если TaskResult не найден → 400 "Файл сметы недоступен"
           - Для ESTIMATE_OPTIMIZATION с file: передать загруженный файл как обычно
           - Для остальных типов: файл из multipart или источник из card
        2. Обновить соответствующее *_task_id на карточке исходя из task_type:
           LIST_FROM_GRAND / LIST_FROM_PROJECT → list_task_id
           CHECK_LIST_COMPLETENESS / CHECK_PROJECT_COMPLETENESS → completeness_task_id
           ESTIMATE_FROM_LIST → estimate_task_id
           ESTIMATE_OPTIMIZATION → optimization_task_id
     → Если любой шаг провалился → rollback, orphan-задач не остаётся
     → Вернуть обновлённый WorkflowCardResponse
```

**selectinload — обязателен:**
```python
stmt = (
    select(WorkflowCard)
    .where(WorkflowCard.project_id == project_id)
    .options(
        selectinload(WorkflowCard.list_task),
        selectinload(WorkflowCard.completeness_task),
        selectinload(WorkflowCard.estimate_task),
        selectinload(WorkflowCard.optimization_task),
    )
    .order_by(WorkflowCard.created_at.asc())
    .limit(100)
)
```

**5. Подключить роутер в `backend/app/main.py`**

**Критерии готовности Фазы 1:**
- `pytest` проходит (тесты: create, get, patch stage, patch с чужим task_id → 400, patch несуществующей карточки → 404, POST с пустым name → 422, start-task → карточка обновлена в одной транзакции)
- GET возвращает `[]` для нового проекта
- GET возвращает `null` для task-полей если задача soft-deleted
- start-task: при rollback task НЕ создаётся
- start-task ESTIMATE_OPTIMIZATION без файла: если estimate TaskResult отсутствует → 400

---

### Фаза 2: Frontend — типы, API-клиент, store [x]

**2.1 — Типы** `frontend/src/types/workflow.ts`

```typescript
export type KanbanStage = 'list' | 'completeness' | 'estimate' | 'optimization'

export type TaskStatus = 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled'

export interface TaskBrief {
  id: string
  task_type: string   // нужен для определения типа completeness (LIST_FROM_PROJECT → CHECK_PROJECT_COMPLETENESS)
  status: TaskStatus
  name: string | null
  created_at: string
}

export interface WorkflowCard {
  id: string
  project_id: string
  name: string
  stage: KanbanStage
  list_task_id: string | null
  completeness_task_id: string | null
  estimate_task_id: string | null
  optimization_task_id: string | null
  list_task: TaskBrief | null        // null если задача soft-deleted или не создана
  completeness_task: TaskBrief | null
  estimate_task: TaskBrief | null
  optimization_task: TaskBrief | null
}

// Результат проверки guard conditions
export interface GuardResult {
  allowed: boolean
  blockType: 'hard' | 'soft' | null  // hard = нельзя пройти, soft = предупреждение
  message: string
}

export interface StartTaskPayload {
  task_type: string
  file?: File          // File (браузерный объект), не FormData — API-клиент сам строит FormData
  source_stage?: 1 | 2
  use_previous_stage?: boolean  // для ESTIMATE_OPTIMIZATION: true = взять смету из estimate_task
}
```

**2.2 — API-клиент** `frontend/src/api/workflowCards.ts`

```typescript
getWorkflowCards(projectId: string): Promise<WorkflowCard[]>
createWorkflowCard(projectId: string, name: string): Promise<WorkflowCard>
updateWorkflowCard(cardId: string, patch: Partial<WorkflowCard>): Promise<WorkflowCard>
deleteWorkflowCard(cardId: string): Promise<void>
startTask(cardId: string, payload: StartTaskPayload): Promise<WorkflowCard>
// Реализация: строит multipart/form-data вручную
// const fd = new FormData()
// fd.append('task_type', payload.task_type)
// if (payload.source_stage) fd.append('source_stage', String(payload.source_stage))
// if (payload.use_previous_stage) fd.append('use_previous_stage', 'true')
// if (payload.file) fd.append('file', payload.file)
// return axios.post(`/api/workflow-cards/${cardId}/start-task`, fd)
```

**2.3 — Zustand store** `frontend/src/stores/kanban.ts`

```typescript
interface KanbanStore {
  cards: WorkflowCard[]
  loading: boolean
  movingCardId: string | null       // id карточки в процессе drag (для pessimistic update)
  submittingCardIds: Set<string>    // id карточек с активным startTask (защита от двойного клика)

  fetchCards: (projectId: string, signal?: AbortSignal) => Promise<void>
  createCard: (projectId: string, name: string) => Promise<WorkflowCard>
  moveCard: (cardId: string, toStage: KanbanStage, bypassSoft?: boolean) => Promise<GuardResult>
  // bypassSoft=true: пропустить SOFT-блок (пользователь подтвердил в диалоге)
  startTask: (cardId: string, payload: StartTaskPayload) => Promise<WorkflowCard>
  deleteCard: (cardId: string) => Promise<void>
  clearCards: () => void
}
```

**Ключевые контракты store:**

`moveCard` — pessimistic update:
1. Вычислить `GuardResult` на основе текущего стейта карточки
2. Если `!allowed && blockType === 'hard'` → вернуть GuardResult, НЕ делать PATCH
3. Если `blockType === 'soft' && !bypassSoft` → вернуть GuardResult с `message`; UI показывает диалог и при подтверждении вызывает `moveCard(cardId, toStage, true)`
4. Если `allowed || (blockType === 'soft' && bypassSoft)` → установить `movingCardId = cardId`, await PATCH, обновить стор, сбросить `movingCardId`

`moveCard` guard-логика (полная матрица сообщений):
```
→ Полнота:
  list_task === null                    → hard, «Сначала создайте Перечень»
  list_task.status === 'pending'        → hard, «Перечень ещё не запущен»
  list_task.status === 'processing'     → hard, «Перечень ещё обрабатывается»
  list_task.status === 'failed'         → hard, «Перечень завершился с ошибкой — исправьте»
  list_task.status === 'cancelled'      → hard, «Перечень отменён — создайте заново»
  list_task.status === 'completed'      → allowed: true

→ Смета:
  (та же проверка list_task как выше)
  completeness_task === null            → soft, «Полнота не проверена. Создать смету на основе перечня?»
  completeness_task.status !== 'completed' → soft, «Полнота не завершена. Создать смету на основе перечня?»

→ Оптимизация:
  → allowed: true (смету можно загрузить с ПК или взять из предыдущей стадии — перечень не требуется)
```

`startTask` — блокировка дублей:
- если `cardId` в `submittingCardIds` → игнорировать вызов (double-click защита)
- добавить в Set → await API → убрать из Set (в finally, чтобы убрать даже при ошибке)

`fetchCards` — пауза во время drag:
```typescript
fetchCards: async (projectId, signal) => {
  // Не обновлять стор если карточка сейчас перетаскивается
  if (get().movingCardId !== null) return
  // ... обычная логика fetch
}
```

**Критерии готовности Фазы 2:**
- `npx tsc --noEmit` без ошибок
- `moveCard` к стадии Полнота с `list_task.status='processing'` → GuardResult `{ allowed: false, blockType: 'hard' }`
- `moveCard` к стадии Оптимизация без list_task → GuardResult `{ allowed: true }`
- `startTask` при двойном вызове → второй вызов игнорируется
- `submittingCardIds` присутствует в интерфейсе KanbanStore

---

### Фаза 3: Frontend — компонент KanbanBoard [x]

**3.1 — Установка**
```bash
cd frontend && npm install @dnd-kit/core @dnd-kit/utilities
```
`@dnd-kit/sortable` **не устанавливать** — он для сортировки внутри одного списка, не нужен для cross-column drag. Сортировка карточек внутри колонки в MVP не поддерживается.

**Архитектура dnd:**
- Карточки: `useDraggable({ id: card.id, data: { card } })`
- Колонки: `useDroppable({ id: stage })`
- Collision detection: `closestCorners` — надёжнее чем `pointerWithin` при быстром перетаскивании через узкие зазоры между колонками; `pointerWithin` промахивается при быстром движении
- `DragOverlay` рендерит призрак карточки пока drag активен
- `handleDragEnd` определяет целевую колонку из `over.id` (это и есть `stage`)

**3.2 — `KanbanBoard.tsx`** `frontend/src/components/kanban/KanbanBoard.tsx`

```typescript
// Структура:
<DndContext
  sensors={sensors}  // PointerSensor с activationConstraint: { distance: 8 }
  collisionDetection={closestCorners}  // надёжнее pointerWithin для cross-column drag
  onDragStart={handleDragStart}
  onDragEnd={handleDragEnd}
>
  {STAGES.map(stage => <KanbanColumn key={stage} ... />)}
  <DragOverlay>
    {activeCard ? <KanbanCard card={activeCard} isOverlay /> : null}
  </DragOverlay>
</DndContext>
```

`activationConstraint: { distance: 8 }` — drag срабатывает только при смещении мыши на 8px. Случайные клики на карточку не запускают drag.

`handleDragEnd`:
1. Если source === target → ничего
2. Вызвать `moveCard(cardId, targetStage)` → await GuardResult
3. Если `GuardResult.blockType === 'hard'` → показать inline-предупреждение, НЕ двигать
4. Если `GuardResult.blockType === 'soft'` → показать диалог подтверждения (Пропустить / Вернуться); при «Пропустить» → `moveCard(cardId, targetStage, true)` (bypassSoft=true)
5. Если `GuardResult.allowed` → карточка обновится через стор после ответа сервера

Полинг обновления карточек (каждые 5 секунд):
```typescript
useEffect(() => {
  let intervalId: number
  let controller = new AbortController()

  const startPolling = () => {
    controller = new AbortController()
    fetchCards(projectId, controller.signal)
    intervalId = setInterval(() => {
      if (!document.hidden) {  // не делать запросы на фоне
        controller.abort()
        controller = new AbortController()
        fetchCards(projectId, controller.signal)
        // fetchCards сам проверяет movingCardId и пропускает обновление во время drag
      }
    }, 5000)
  }

  const handleVisibility = () => {
    if (document.hidden) {
      clearInterval(intervalId)
    } else {
      startPolling()
    }
  }

  document.addEventListener('visibilitychange', handleVisibility)
  startPolling()

  return () => {
    clearInterval(intervalId)
    controller.abort()
    document.removeEventListener('visibilitychange', handleVisibility)
  }
}, [projectId])
```

**3.3 — `KanbanCard.tsx`** `frontend/src/components/kanban/KanbanCard.tsx`

```typescript
const KanbanCard = React.memo(({ card, isOverlay }: Props) => {
  // ...
}, (prev, next) =>
  prev.card.id === next.card.id &&
  prev.card.stage === next.card.stage &&
  prev.card.list_task?.status === next.card.list_task?.status &&
  prev.card.completeness_task?.status === next.card.completeness_task?.status &&
  prev.card.estimate_task?.status === next.card.estimate_task?.status &&
  prev.card.optimization_task?.status === next.card.optimization_task?.status
)
```

`React.memo` с кастомным comparator — карточка перерисовывается только при реальных изменениях данных.

**Визуальные стили карточки** (inline styles, как везде в проекте):
```typescript
// Карточка
{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: '8px',
  padding: '12px', marginBottom: '8px', cursor: 'grab',
  boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }

// Drag overlay (призрак): чуть прозрачнее
{ opacity: 0.85, boxShadow: '0 4px 12px rgba(0,0,0,0.15)' }

// Колонка
{ background: '#f8fafc', borderRadius: '10px', padding: '12px',
  minWidth: '260px', flex: '1', maxWidth: '340px' }

// Заголовок колонки
{ fontWeight: 600, fontSize: '14px', color: '#475569', marginBottom: '12px',
  display: 'flex', justifyContent: 'space-between', alignItems: 'center' }

// Счётчик карточек в заголовке
{ background: '#e2e8f0', borderRadius: '12px', padding: '2px 8px',
  fontSize: '12px', color: '#64748b' }
```

Содержимое карточки:
- Название
- GripVertical-иконка (drag handle, справа, цвет `#94a3b8`)
- Статус-индикатор текущей стадии (см. Фазу 4 — 5 состояний)
- Кнопка действия (зависит от стадии и статуса задачи)

**3.4 — `KanbanColumn.tsx`** `frontend/src/components/kanban/KanbanColumn.tsx`

- `useDroppable({ id: stage })`
- Заголовок + счётчик карточек
- Кнопка `+` только в колонке `list`
- Empty state: «Нажмите + чтобы начать» если колонка пустая и это `list`; «Перетащите карточку» для остальных пустых колонок

**Критерии готовности Фазы 3:**
- Карточки отображаются в 4 колонках
- Drag-and-drop работает, DragOverlay отображает призрак
- Клик на карточку (без сдвига 8px) не запускает drag
- При переносе без перечня → предупреждение, карточка не перемещается
- Перенос в Оптимизацию без перечня → разрешён
- Полинг останавливается при переключении вкладки
- Полинг не обновляет стор во время активного drag

---

### Фаза 4: Frontend — бизнес-логика внутри карточки [x]

Кнопка действия внутри карточки и запуск задач. Все кнопки блокируются (`disabled`) при первом клике до ответа сервера.

**Универсальный рендер статуса задачи** (переиспользуется во всех стадиях):

```typescript
function TaskStatusBadge({ task }: { task: TaskBrief | null }) {
  if (!task)
    return <span style={{ color: '#94a3b8' }}>● Не запущено</span>
  switch (task.status) {
    case 'completed':  return <span style={{ color: '#15803d' }}>● Готово</span>
    case 'processing': return <span style={{ color: '#d97706' }}>● Обрабатывается <LumaSpin /></span>
    case 'pending':    return <span style={{ color: '#94a3b8' }}>● Ожидает запуска</span>
    // pending = задача создана, воркер ещё не взял
    case 'failed':     return <span style={{ color: '#dc2626' }}>● Ошибка</span>
    case 'cancelled':  return <span style={{ color: '#94a3b8' }}>● Отменено</span>
  }
}
```

LumaSpin — компонент из `frontend/src/components/LumaSpin.tsx` (уже существует).

**Кнопка «Открыть результат»** — во всех стадиях вызывает `downloadSlotFile(task.id, slot)` из `frontend/src/api/projects.ts` (функция уже существует):
- Стадия Перечень: `slot = 'source'`
- Стадия Полнота: `slot = 'source'` (результат полноты пишется в тот же слот)
- Стадия Смета: `slot = 'estimate'`
- Стадия Оптимизация: `slot = 'optimized'`

---

**4.1 — Стадия «Перечень»**

Кнопка `+` в заголовке колонки открывает модалку:
- Поле «Название карточки»: `maxLength={255}`, кнопка «Создать» disabled пока `name.trim().length === 0`
- Выбор типа: «Перечень из проекта» (task_type='LIST_FROM_PROJECT') / «Перечень из Гранд-сметы» (task_type='LIST_FROM_GRAND')
- FileUpload (существующий компонент). Проверка размера файла до загрузки: `if (file.size > 50 * 1024 * 1024) → показать ошибку «Файл превышает 50 МБ»`
- При подтверждении — **два последовательных запроса**:
  1. `createCard(projectId, name)` → получить `card.id`
  2. `startTask(card.id, { task_type, file })` — привязать задачу к карточке
  - Оба запроса выполняются под одной блокировкой кнопки «Создать» (disabled до завершения обоих)
  - Если `startTask` упал после успешного `createCard` — карточка создана, `list_task === null`; внутри карточки отображается кнопка «Создать перечень» (см. ниже)

Внутри карточки в колонке «Перечень»:
- `TaskStatusBadge` для list_task
- Если `list_task === null` → кнопка «Создать перечень» (открывает ту же модалку выбора типа и файла, но без поля названия — карточка уже существует)
- Если `list_task.status === 'failed' || 'cancelled'` → кнопка «Повторить»:
  - Открывает модалку повторного выбора файла (файл нужно загрузить заново — он не сохраняется в карточке)
  - При подтверждении: `startTask(card.id, { task_type: list_task.task_type, file })` — перезаписывает `list_task_id` на новую задачу
- Если `list_task.status === 'completed'` → кнопка «Открыть результат» → `downloadSlotFile(list_task.id, 'source')`
- Если `list_task.status === 'processing' || 'pending'` → только спиннер/статус, никаких кнопок

---

**4.2 — Стадия «Полнота»**

При попытке перенести карточку без completed list_task → guard блокирует (описание в Фазе 2).

Внутри карточки:
- `TaskStatusBadge` для completeness_task
- Если `completeness_task === null` → кнопка «Проверить полноту» →
  `startTask(cardId, { task_type: card.list_task?.task_type === 'LIST_FROM_PROJECT' ? 'CHECK_PROJECT_COMPLETENESS' : 'CHECK_LIST_COMPLETENESS' })`
  // task_type определяется по типу перечня; если list_task почему-то null → использовать 'CHECK_LIST_COMPLETENESS' как дефолт
- Если `failed || cancelled` → кнопка «Повторить» → `startTask(cardId, { task_type: completeness_task.task_type })` (без файла — задача переиспользует данные из list_task через source_task_id; сервер сам найдёт источник)
- Если `completed` → зелёный статус + кнопка «Открыть результат» → `downloadSlotFile(completeness_task.id, 'source')`
- Если `processing || pending` → спиннер

---

**4.3 — Стадия «Смета»**

При переносе без completeness_task → SOFT-предупреждение с диалогом «Пропустить / Вернуться».

Внутри карточки:
- `TaskStatusBadge` для estimate_task
- Если `estimate_task === null || failed || cancelled`:
  - Radio выбор источника:
    - «На основе перечня» (активно если `list_task?.status === 'completed'`)
    - «На основе полноты» (активно только если `completeness_task?.status === 'completed'`)
  - Кнопка «Создать смету» → `startTask(cardId, { task_type: 'ESTIMATE_FROM_LIST', source_stage: 1|2 })`
  - Если ни один источник недоступен → показать предупреждение «Сначала завершите Перечень»
- Если `completed` → зелёный + кнопка «Открыть смету» → `downloadSlotFile(estimate_task.id, 'estimate')`
- Если `processing || pending` → спиннер

---

**4.4 — Стадия «Оптимизация»**

Внутри карточки:
- `TaskStatusBadge` для optimization_task
- Если `optimization_task === null || failed || cancelled`:
  - Два варианта входа:
    - **«Использовать смету из предыдущей стадии»** — кнопка активна только если `estimate_task?.status === 'completed'`; при нажатии → `startTask(cardId, { task_type: 'ESTIMATE_OPTIMIZATION', use_previous_stage: true })` (сервер сам загружает файл из estimate_task слота 'estimate')
    - **«Загрузить смету с ПК»** — FileUpload; проверка `file.size > 50MB → ошибка`; при загрузке → `startTask(cardId, { task_type: 'ESTIMATE_OPTIMIZATION', file })`
  - Если `estimate_task` отсутствует или не completed → первый вариант disabled с tooltip «Сначала создайте смету на стадии Смета»
  - При «Повторить» (failed/cancelled): показать те же два варианта выбора заново
- Если `completed` → зелёный + «Открыть результат» → `downloadSlotFile(optimization_task.id, 'optimized')`
- Если `processing || pending` → спиннер

**Критерии готовности Фазы 4:**
- Полный happy path: создать карточку → запустить перечень → дождаться completed → перенести в Полнота → проверить полноту → перенести в Смета → создать смету → перенести в Оптимизация → оптимизировать
- При `list_task.status === 'failed'` → кнопка «Повторить» видна; повторный запуск открывает модалку выбора файла
- При переходе в Оптимизацию без перечня — разрешено, карточка перемещается
- Двойной клик на кнопку действия → только один запрос (второй игнорируется)
- Файл > 50 МБ → ошибка до загрузки
- Имя карточки с пробелами → кнопка «Создать» недоступна
- «Открыть результат» → файл скачивается через downloadSlotFile с правильным слотом

---

### Фаза 5: Интеграция в ProjectDetail и переключатель вида [x]

**5.1 — Переключатель**

В `frontend/src/pages/ProjectDetail.tsx`:
```typescript
const [viewMode, setViewMode] = useState<'list' | 'kanban'>('list')
```
- Две кнопки «Список» / «Канбан» в шапке страницы, inline style (как существующие элементы управления)
- Активная кнопка — выделена визуально (border: '1px solid #93c5fd', background: '#eff6ff', color: '#2563eb')
- Неактивная — border: '1px solid #e2e8f0', background: '#fff', color: '#64748b'

**5.2 — Условный рендер**
```typescript
{viewMode === 'kanban'
  ? <KanbanBoard projectId={project.id} />
  : /* существующий список задач — не трогать */}
```

**5.3 — Сброс стора при смене проекта**
В `KanbanBoard` useEffect — сбрасывать стор при изменении `projectId`:
```typescript
useEffect(() => {
  clearCards()
  // затем начать fetchCards + polling (код из Фазы 3)
}, [projectId])
```
Без этого — при переходе между проектами мелькают карточки от предыдущего.

**5.4 — Независимость от существующего списка задач**
- Существующие задачи, созданные до этой фичи, не имеют WorkflowCard — они остаются только в списочном виде.
- Канбан и список — полностью независимые views, никакого общего стейта.

**Критерии готовности Фазы 5:**
- Переключатель работает без перезагрузки страницы
- При переходе на другой проект — карточки предыдущего проекта не мелькают
- Существующий список задач работает как прежде (регрессия)
- `npx tsc --noEmit` без ошибок
- `npm run lint` без ошибок
- Полинг останавливается при скрытии вкладки, возобновляется при возврате

---

## Edge Cases — разобрано заранее, решения встроены в фазы

### A. Гонки и конкурентность

| # | Проблема | Решение | Где реализовано |
|---|---|---|---|
| A1 | Double-drag race: два PATCH летят параллельно | Pessimistic update: UI двигает карточку только после 200 OK | Фаза 2 (store), Фаза 3 (DragOverlay) |
| A2 | Double-click «Создать задачу» → orphan task | `submittingCardIds: Set<string>` в store; второй вызов игнорируется | Фаза 2 (store), Фаза 4 (кнопка disabled) |
| A3 | Guard не обрабатывает `processing/failed/cancelled` | Guard проверяет строго `=== 'completed'`; разные сообщения для каждого статуса | Фаза 2 (guard матрица) |
| A4 | `createTask` OK + `linkTask` fail → orphan task | Атомарный endpoint `start-task`: createTask + linkTask в одной транзакции | Фаза 1 (endpoint), Фаза 2 (API) |
| A5 | Polling обновляет стор во время drag → карточка прыгает | `fetchCards` проверяет `movingCardId !== null` и пропускает обновление | Фаза 2 (store), Фаза 3 (polling) |

### B. Soft delete рассинхрон

| # | Проблема | Решение | Где реализовано |
|---|---|---|---|
| B1 | Задача удалена через корзину, `*_task_id` ссылается | `selectinload` загружает задачу; Python-код проверяет `task.deleted_at is not None` → обнуляет поле в response | Фаза 1 (GET endpoint) |
| B2 | `stage='estimate'`, но `estimate_task` удалена | В KanbanCard: `if stage === 'estimate' && !estimate_task → «Создать смету»` | Фаза 4 (статусы) |

### C. Валидация входных данных

| # | Проблема | Решение | Где реализовано |
|---|---|---|---|
| C1 | `name=""` или `name="   "` | Backend: `@field_validator strip + min_length=1` (Pydantic v2); Frontend: кнопка disabled | Фаза 1 (схемы), Фаза 4 (UI) |
| C2 | `name` = 10 000 символов | `max_length=255` в Pydantic; `maxLength={255}` на input | Фаза 1 (схемы), Фаза 4 (UI) |
| C3 | `PATCH {stage: "hack"}` | `Literal['list','completeness','estimate','optimization']` → 422 | Фаза 1 (схемы) |
| C4 | `*_task_id` из другого проекта | Backend: `task.project_id == card.project_id` → 400 | Фаза 1 (PATCH endpoint) |
| C5 | `project_id` не существует | `await db.get(Project, project_id)` → 404 | Фаза 1 (POST endpoint) |
| C6 | Невалидный UUID в path | FastAPI UUID тип → 422 автоматически | Фаза 1 (роутер) |

### D. Производительность

| # | Проблема | Решение | Где реализовано |
|---|---|---|---|
| D1 | N+1: 50 карточек → 200+ SELECT | `selectinload` всех 4 task-полей; 5 запросов вместо 200+ | Фаза 1 (GET) |
| D2 | Полинг на фоне: 10 вкладок = 10× нагрузка | `visibilitychange` → пауза полинга при `document.hidden` | Фаза 3 (KanbanBoard) |
| D3 | setState на размонтированном компоненте | AbortController + cleanup в useEffect | Фаза 3 (KanbanBoard) |
| D4 | DnD перерисовывает 50+ карточек при drag | `React.memo` с кастомным comparator по статусам | Фаза 3 (KanbanCard) |
| D5 | 100+ карточек без ограничений | `limit=100` hard cap в GET | Фаза 1 (GET) |

### E. Неожиданное поведение пользователя

| # | Проблема | Решение | Где реализовано |
|---|---|---|---|
| E1 | Drag до 8px → случайный DnD при клике | `activationConstraint: { distance: 8 }` в PointerSensor | Фаза 3 (KanbanBoard) |
| E2 | Два окна браузера | Полинг каждые 5 сек — known limitation | Фаза 3 |
| E3 | Файл > 50 МБ | Проверка `file.size` до загрузки на frontend | Фаза 4 (4.1, 4.4) |
| E4 | Переключение проектов → старые карточки мелькают | `clearCards()` при изменении projectId | Фаза 5 |
| E5 | «Повторить» — файл не сохранён в карточке | Открывать модалку повторного выбора файла для задач с файлом | Фаза 4 (4.1, 4.4) |

### F. Обратная совместимость

| # | Проблема | Решение |
|---|---|---|
| F1 | Старые задачи не в WorkflowCard | Не трогать; списочный вид и канбан — независимые views |
| F2 | Удаление проекта | `ON DELETE CASCADE` на `project_id`; задачи при удалении карточки не трогаются |
| F3 | Нет user_id на WorkflowCard | Осознанное решение; внутренний инструмент |

### G. Статусы задач

| Статус | Отображение | Доступные действия | Guard при переходе |
|---|---|---|---|
| `null` (нет задачи) | ● Не запущено (серый) | Кнопка «Запустить» / «Создать» | HARD block (нет completed) |
| `pending` | ● Ожидает запуска (серый) | — | HARD block |
| `processing` | ● Обрабатывается + спиннер (оранжевый) | — | HARD block |
| `completed` | ● Готово (зелёный) | «Открыть результат» | Переход разрешён |
| `failed` | ● Ошибка (красный) | «Повторить» (с файлом — модалка, без файла — прямой вызов) | HARD block |
| `cancelled` | ● Отменено (серый) | «Повторить» | HARD block |

---

## Итог

| Фаза | Что делается | Зависимости |
|---|---|---|
| 1 | Backend: модель + миграция + API (атомарный start-task, selectinload, валидации) | — |
| 2 | Frontend: типы + API-клиент + store (pessimistic update, guard-матрица, submittingSet, polling pause) | Фаза 1 |
| 3 | Frontend: визуал канбана + dnd-kit (closestCorners, activationConstraint, React.memo, visibilitychange, AbortController) | Фаза 2 |
| 4 | Frontend: бизнес-логика стадий (все статусы, retry с файлом, downloadSlotFile, file size check, atomic startTask) | Фаза 3 |
| 5 | Интеграция в ProjectDetail (переключатель, clearCards на смену проекта, регрессия списка) | Фаза 4 |

**Реализован целиком:** [x]  
**Что осталось:** —  
**Коммит:** `5d15433` — feat: канбан-представление проектов — полная реализация (5 фаз)
