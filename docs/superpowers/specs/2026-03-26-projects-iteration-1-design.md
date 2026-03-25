# Итерация 1 — Проекты + Файловые слоты

**Дата:** 2026-03-26
**Стек:** FastAPI + SQLAlchemy async + PostgreSQL / React + TypeScript + Zustand

---

## Контекст

Существующая система: 10 типов задач, статусы processing_status (pending/processing/completed/failed/cancelled), результаты хранятся в `task_results` как LargeBinary без разделения по типу файла. Навигация — кнопки в шапке Layout.

Итерация 1 добавляет:
- Сущность Project (один-ко-многим с Task)
- Файловые слоты (source / estimate / optimized) на уровне task_results
- Поле estimation_status на Task (только для смет)
- Вкладку «Проекты» в UI с карточками и агрегацией
- Привязку задач к проекту при создании и постфактум

---

## Схема данных

### Новая таблица `projects`

| Колонка | Тип | Описание |
|---|---|---|
| id | UUID PK | gen_random_uuid() |
| name | VARCHAR(255) NOT NULL | Название проекта |
| description | TEXT nullable | Описание |
| created_at | TIMESTAMPTZ NOT NULL | |
| updated_at | TIMESTAMPTZ NOT NULL | |

### Добавляется в `tasks`

| Колонка | Тип | Описание |
|---|---|---|
| project_id | UUID nullable FK → projects.id SET NULL | Индексируется |
| estimation_status | VARCHAR(20) NOT NULL DEFAULT 'not_applicable' | unestimated / estimated / optimized / not_applicable |
| cost | NUMERIC(12,2) nullable | Автозаполняется при загрузке xlsx в слот estimate |

**Логика при создании задачи:**
- task_type входит в ESTIMATE_TASK_TYPES → estimation_status = 'unestimated'
- task_type не входит → estimation_status = 'not_applicable', cost всегда null

### Добавляется в `task_results`

| Колонка | Тип | Описание |
|---|---|---|
| slot | VARCHAR(20) NOT NULL DEFAULT 'result' | source / estimate / optimized / result |

'result' — обратная совместимость для всех существующих строк.

### Константа ESTIMATE_TASK_TYPES

```python
ESTIMATE_TASK_TYPES = {
    "SMETA_FROM_LIST",
    "SMETA_FROM_PROJECT",
    "SMETA_FROM_EDC_PROJECT",
    "SMETA_FROM_GRAND_PROJECT",
    "SCAN_TO_EXCEL",
}
# Не входят: LIST_FROM_TZ, LIST_FROM_TZ_PROJECT, LIST_FROM_PROJECT,
#             RESEARCH_PROJECT, COMPARE_PROJECT_SMETA
```

---

## Бэкенд API

### Новый роутер `/projects`

```
POST   /projects                создать проект
GET    /projects                список + агрегация (для карточек)
GET    /projects/{id}           проект + задачи + агрегация
PATCH  /projects/{id}           изменить name / description
DELETE /projects/{id}           только admin; tasks.project_id → null
```

Агрегация в одном SQL-запросе:
- COUNT по estimation_status для смет (unestimated / estimated / optimized)
- SUM(cost) WHERE estimation_status IN ('estimated', 'optimized')
- COUNT WHERE estimation_status = 'not_applicable' (прочие задачи)

### Изменения в `/tasks`

```
POST /tasks                     + поля project_id (uuid | null)
                                        project_name (string | null)
                                  если project_name → создать проект, вернуть id
PATCH /tasks/{id}/project       прикрепить / открепить задачу
                                  body: {project_id: uuid | null}
```

### Файловые слоты

```
POST   /tasks/{id}/files        загрузить файл в слот
                                  form: slot=source|estimate|optimized, file=...
                                  при slot=estimate: парсит xlsx → cost + estimation_status=estimated
                                  при slot=optimized: файл сохраняется, статус НЕ меняется
DELETE /tasks/{id}/files/{slot} удалить файл из слота
                                  при slot=estimate: cost=null, estimation_status=unestimated
PATCH  /tasks/{id}/estimation   подтвердить optimized
                                  body: {estimation_status: 'optimized'}
                                  только если в слоте optimized есть файл
```

Существующий GET /tasks/{id}/results не меняется — фронтенд фильтрует по полю slot.

### Утилита парсинга xlsx

`app/utils/xlsx_cost_parser.py`

```python
def extract_total_cost(file_bytes: bytes) -> Decimal | None:
    """
    Ищет строку где первая ячейка содержит 'итого' или 'всего'
    (регистронезависимо, после strip).
    Возвращает последнее числовое значение в этой строке.
    Если найдено несколько таких строк — берёт последнюю.
    Если ничего не найдено — возвращает None.
    """
```

**Граничные случаи:**
- xlsx повреждён → cost=null, estimation_status=unestimated, ответ 200 + предупреждение
- строка «итого» есть, числа нет → cost=null, estimation_status=unestimated
- файл не xlsx → 400 Bad Request
- слот уже занят → старый TaskResult удаляется, новый записывается

### Права доступа

- GET /projects, GET /projects/{id} — любой авторизованный пользователь
- POST/PATCH /projects — любой авторизованный
- DELETE /projects/{id} — только admin
- Все /tasks/{id}/files, /tasks/{id}/project — get_current_user

### Миграция 004

```sql
1. CREATE TABLE projects (...)
2. ALTER TABLE tasks ADD COLUMN project_id UUID REFERENCES projects(id) ON DELETE SET NULL
3. ALTER TABLE tasks ADD COLUMN estimation_status VARCHAR(20) NOT NULL DEFAULT 'not_applicable'
4. ALTER TABLE tasks ADD COLUMN cost NUMERIC(12,2)
5. CREATE INDEX ix_tasks_project_id ON tasks(project_id)
6. ALTER TABLE task_results ADD COLUMN slot VARCHAR(20) NOT NULL DEFAULT 'result'
7. UPDATE tasks SET estimation_status = 'not_applicable'  -- бэкфилл
```

---

## Фронтенд

### Новые роуты

```
/projects              → Projects.tsx
/projects/:projectId   → ProjectDetail.tsx
```

### Новые файлы

```
src/api/projects.ts         CRUD-функции
src/pages/Projects.tsx      список карточек
src/pages/ProjectDetail.tsx страница проекта + список задач
```

### Изменения в существующих файлах

```
src/types/index.ts      + Project, ProjectCard (с агрегацией)
                        + EstimationStatus тип
                        + ESTIMATE_TASK_TYPES константа
                        + slot поле в TaskResult

src/components/Layout.tsx  + кнопка «Проекты» в шапку

src/pages/TaskCreate.tsx   + блок «Добавить в проект» внизу формы:
                             radio: не добавлять / существующий / новый
                             существующий → <select> с проектами
                             новый → <input> название

src/pages/TaskStatus.tsx   + три файловых слота (только ESTIMATE_TASK_TYPES)
                           + estimation_status badge
                           + кнопка «Прикрепить к проекту»
```

### Структура карточки проекта

```
Название проекта
Описание...

Сметы:
[красный] 2 не рассчитано
[жёлтый]  3 рассчитано    18 450 000 ₽
[зелёный] 1 оптимизировано

Прочие задачи: 4
```

### Файловые слоты в TaskStatus (только для ESTIMATE_TASK_TYPES)

```
Исходный файл     [Загрузить .xlsx]  или  [filename.xlsx ↓] [✕]
Расчёт            [Загрузить .xlsx]  или  [filename.xlsx ↓] [✕]
Оптимизированный  [Загрузить .xlsx]  или  [filename.xlsx ↓] [✕] [Подтвердить]
```

Кнопка «Подтвердить» появляется только когда файл в слоте optimized загружен.
При нажатии вызывает PATCH /tasks/{id}/estimation → estimation_status = 'optimized'.

---

## Не входит в Итерацию 1

- Модуль оптимизации (Итерация 3)
- Подбор аналогов (Итерация 3)
- История изменений (Итерация 4)
- Экспорт проекта в xlsx/PDF (Итерация 2)
