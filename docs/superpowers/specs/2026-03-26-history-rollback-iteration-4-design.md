# Итерация 4 — История изменений и откат

**Дата:** 2026-03-26
**Стек:** FastAPI + SQLAlchemy + Alembic / React + TypeScript

---

## Контекст

Итерации 1–3 добавили проекты, задачи, экспорт смет и модуль оптимизации (`/optimize/analyze`, `/optimize/run`). Итерация 4 добавляет аудит-лог всех изменений сметы с возможностью отката к любому предыдущему состоянию.

---

## Архитектура

### Подход: отдельная таблица `task_history`

Новая модель `TaskHistory` с Alembic-миграцией 005. История пишется при каждом завершении оптимизации. Откат — двухшаговый endpoint с подтверждением при наличии зависимых записей.

---

## Backend

### Новая модель `TaskHistory`

**Файл:** `backend/app/models/history.py`

```python
class TaskHistory(Base):
    __tablename__ = "task_history"

    id: Mapped[str]              # UUID, PK
    task_id: Mapped[str]         # FK → tasks.id, CASCADE DELETE
    operation_type: Mapped[str]  # "optimization" | "analog" | "manual_edit" | "revert"
    slot: Mapped[str]            # "optimized" | "estimate" | ...
    description: Mapped[str]     # человекочитаемое описание операции
    previous_value: Mapped[dict] # JSON: {"file_name": str, "file_data_b64": str, "estimation_status": str}
    new_value: Mapped[dict]      # JSON: то же
    created_at: Mapped[datetime]
```

`previous_value` и `new_value` хранят полные байты файла в base64, что позволяет физически восстановить предыдущую версию.

**Обновить `backend/app/models/__init__.py`** — добавить экспорт `TaskHistory`.

### Миграция 005

**Файл:** `backend/alembic/versions/005_task_history.py`

- Создаёт таблицу `task_history` со всеми колонками
- Добавляет индекс на `(task_id, created_at)`
- `previous_value` и `new_value` — тип `JSON` (JSONB в PostgreSQL, TEXT в SQLite)

### Запись истории

История пишется в двух местах:

**1. `backend/app/routers/tasks.py` — `_run_optimization_background`**

После успешного сохранения `TaskResult` со слотом `optimized`:
```python
history = TaskHistory(
    id=str(uuid4()),
    task_id=task_id,
    operation_type="optimization",
    slot="optimized",
    description=f"Оптимизация: найдено {found_count}/{total} аналогов, экономия {savings_pct:.1f}%",
    previous_value={"file_name": prev_file_name, "file_data_b64": prev_b64, "estimation_status": prev_status},
    new_value={"file_name": "optimized.xlsx", "file_data_b64": new_b64, "estimation_status": "optimized"},
)
session.add(history)
```

Перед оптимизацией нужно прочитать текущий `TaskResult` слота `optimized` (если существует) для `previous_value`. Если слота ещё нет — `previous_value = {}`.

**2. `backend/app/services/task_processor.py` — `_handle_optimize_smeta`**

Аналогично после сохранения `TaskResult` с `slot="optimized"`.

### Новые endpoints

#### `GET /tasks/{task_id}/history`

**Auth:** `get_current_user`

**Поведение:**
1. Проверяет существование задачи — 404 если нет
2. Возвращает список `TaskHistory` по `task_id`, отсортированных по `created_at` DESC
3. Не включает `file_data_b64` в ответ (тяжёлые данные только при откате)

**Ответ:**
```json
[
  {
    "id": "uuid",
    "operation_type": "optimization",
    "slot": "optimized",
    "description": "Оптимизация: найдено 8 из 12 аналогов, экономия 14.2%",
    "created_at": "2026-03-26T14:32:00"
  }
]
```

---

#### `POST /tasks/{task_id}/history/{entry_id}/revert`

**Auth:** `get_current_user`

**Body:** `{"confirm": false}`

**Логика:**

1. Проверяет существование задачи и записи истории — 404 если нет
2. Ищет записи истории созданные **после** `entry_id` для той же задачи

**Если `confirm=false`:**
- Если нет более поздних записей — сразу выполняет откат (см. ниже) и возвращает `{"reverted": true}`
- Если есть более поздние записи — возвращает предупреждение:
  ```json
  {
    "warning": true,
    "dependent_entries": [
      {"id": "uuid", "description": "...", "created_at": "..."}
    ]
  }
  ```

**Если `confirm=true`:**
- Выполняет каскадный откат:
  1. Декодирует `entry.previous_value.file_data_b64` из base64
  2. Если `previous_value` непустой — создаёт новый `TaskResult` с файлом и слотом `entry.slot`
  3. Обновляет `task.estimation_status = entry.previous_value.estimation_status`
  4. Удаляет из `task_history` все записи с `created_at >= entry.created_at`
  5. Добавляет новую запись `operation_type="revert"` с описанием `f"Откат к состоянию до: {entry.description}"`
- Возвращает `{"reverted": true}`

---

## Статус задачи

`operation_type` — новые значения:

| Значение | Описание |
|---|---|
| `optimization` | Запуск оптимизации через /optimize/run или OPTIMIZE_SMETA |
| `analog` | Применение аналога (заглушка для будущих итераций) |
| `manual_edit` | Ручное редактирование (заглушка для будущих итераций) |
| `revert` | Откат к предыдущему состоянию |

---

## Frontend

### Новые типы (`frontend/src/types/index.ts`)

```typescript
export interface HistoryEntry {
  id: string;
  operation_type: "optimization" | "analog" | "manual_edit" | "revert";
  slot: string;
  description: string;
  created_at: string;
}

export interface RevertResponse {
  reverted?: boolean;
  warning?: boolean;
  dependent_entries?: Pick<HistoryEntry, "id" | "description" | "created_at">[];
}
```

### Новые функции (`frontend/src/api/tasks.ts`)

```typescript
export async function getTaskHistory(taskId: string): Promise<HistoryEntry[]> {
  const res = await apiClient.get(`/tasks/${taskId}/history`);
  return res.data;
}

export async function revertHistory(
  taskId: string,
  entryId: string,
  confirm: boolean
): Promise<RevertResponse> {
  const res = await apiClient.post(`/tasks/${taskId}/history/${entryId}/revert`, { confirm });
  return res.data;
}
```

### Новый компонент `HistoryModal.tsx`

**Файл:** `frontend/src/components/HistoryModal.tsx`

**Props:** `{ taskId: string; onClose: () => void }`

**Состояния:**
- `loading` — загрузка списка истории
- `entries: HistoryEntry[]` — список записей
- `revertingId: string | null` — ID откатываемой записи
- `dependentEntries: HistoryEntry[]` — список зависимых изменений для подтверждения
- `reverting` — спиннер при выполнении отката

**Иконки по типу операции:**
- `optimization` → 🔧
- `revert` → ⏮
- `analog` → 🔄
- `manual_edit` → ✏️

**Структура UI:**

```
[x] История задачи
──────────────────────────────────────────
  🔧 Оптимизация             26 мар, 14:32
     Найдено 8 из 12 аналогов, экономия 14%
     [Откатить]

  ⏮ Откат                   26 мар, 15:01
     Откат к состоянию до: Оптимизация...
──────────────────────────────────────────
Нет истории изменений        (если пусто)
```

**При нажатии «Откатить»:**
1. Вызов `revertHistory(taskId, entryId, false)`
2. Если `warning=true` — показываем панель с предупреждением и списком зависимых изменений, кнопки «Отмена» и «Подтвердить откат»
3. «Подтвердить откат» → `revertHistory(taskId, entryId, true)` → спиннер → перезагружаем список истории → вызываем `onClose()` (обновление ProjectDetail)
4. Если `reverted=true` сразу (нет зависимых) — перезагружаем список истории, вызываем `onClose()`

### Изменения в `ProjectDetail.tsx`

Добавляем кнопку «История» рядом с «Оптимизировать» для задач с `estimation_status` в `["estimated", "optimized"]`:

```tsx
const [historyTaskId, setHistoryTaskId] = useState<string | null>(null);

// В строке задачи:
{["estimated", "optimized"].includes(task.estimation_status) && (
  <button onClick={() => setHistoryTaskId(task.id)}>
    История
  </button>
)}

// После списка задач:
{historyTaskId && (
  <HistoryModal
    taskId={historyTaskId}
    onClose={() => {
      setHistoryTaskId(null);
      fetchProject();
    }}
  />
)}
```

---

## Обработка ошибок

| Ситуация | Поведение |
|---|---|
| Задача не найдена | 404 |
| Запись истории не найдена | 404 |
| `previous_value` пустой (первая оптимизация) | Откат восстанавливает статус, не трогает файл |
| Ошибка декодирования base64 | 500 с сообщением |
| История пустая | Модал показывает «Нет истории изменений» |

---

## Тесты

### `backend/tests/test_task_history.py`

1. `test_history_written_on_optimize_run` — после `/optimize/run` в таблице появляется запись
2. `test_get_history_returns_entries` — `GET /tasks/{id}/history` возвращает список
3. `test_get_history_task_not_found` — 404 для несуществующей задачи
4. `test_revert_no_dependents_executes_immediately` — без зависимых записей откат выполняется сразу
5. `test_revert_with_dependents_returns_warning` — с зависимыми возвращает предупреждение
6. `test_revert_confirm_cascades` — `confirm=true` удаляет зависимые записи и добавляет revert-запись
7. `test_revert_entry_not_found` — 404 для несуществующей записи

---

## Не входит в Итерацию 4

- Запись истории для analog и manual_edit (только enum-значения в БД)
- Сравнение двух версий xlsx side-by-side
- Экспорт лога изменений в PDF
- Пагинация списка истории
