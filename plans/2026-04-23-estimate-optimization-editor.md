# Онлайн-редактор сметы + модуль оптимизации тендерного предложения

**Дата:** 2026-04-23  
**Статус:** В работе — этап планирования  

---

## Статус планирования

### Завершено
- [x] Исследование кодовой базы (модели, роуты, компоненты, store, миграции)
- [x] Исследование Excel-библиотек для React → выбор `react-data-grid`
- [x] Технические решения согласованы
- [x] Вопросы по реализации согласованы (НДС 22%, доп.расходы, парсинг, версии)
- [x] Структура фаз 1–5 написана
- [x] Методология Шага 1 — согласована → `specs/2026-04-23-step1-completeness-methodology.md`

### Осталось согласовать (методологии)
- [x] **Шаг 2** — Проверка на лишние позиции → `specs/2026-04-23-step2-redundancy-methodology.md`
- [x] **Шаг 3** — Оптимизация по технологиям → `specs/2026-04-23-step3-technology-methodology.md`
- [x] **Шаг 4** — Оптимизация по материалам → `specs/2026-04-23-step4-materials-methodology.md`

### Осталось обновить в плане
- [x] Фаза 6 — привести в соответствие с согласованными методологиями (промпты обновлены)

### Блокирует реализацию
Фаза 6 (модуль оптимизации) заблокирована до завершения пункта «Осталось согласовать». Фазы 1–5 можно реализовывать уже сейчас.

---

## Методологии

| Шаг | Файл | Статус |
|-----|------|--------|
| Шаг 1 — Полнота и объёмы | `smeta-ai/specs/2026-04-23-step1-completeness-methodology.md` | ✅ Согласовано |
| Шаг 2 — Лишние позиции | `smeta-ai/specs/2026-04-23-step2-redundancy-methodology.md` | ✅ Согласовано |
| Шаг 3 — Оптимизация технологий | `smeta-ai/specs/2026-04-23-step3-technology-methodology.md` | ✅ Согласовано |
| Шаг 4 — Оптимизация материалов | `smeta-ai/specs/2026-04-23-step4-materials-methodology.md` | ✅ Согласовано |
| Ручная оптимизация (6.6) | `smeta-ai/specs/2026-04-23-step-custom-optimization-methodology.md` | ✅ Согласовано |

---

## Что строим

Новый тип задачи `ESTIMATE_OPTIMIZATION`:
1. Пользователь загружает **нашу смету себестоимости** (Excel) и опционально **файлы заказчика**
2. Смета открывается в **онлайн-редакторе** прямо в интерфейсе
3. Последовательно запускаются 4 шага AI-оптимизации — каждый создаёт новую версию
4. Все версии сравниваются в едином сравнительном виде

---

## Технические решения (итог исследования)

### Grid-библиотека: `react-data-grid`
- Лицензия: MIT (бесплатно для коммерческого использования)
- Бандл: ~14.8 кБ gzip
- Inline-редактирование, copy-paste, навигация по клавишам — из коробки
- Frozen columns (чекбокс слева) через `frozen: true`
- Row + column виртуализация для 200–500 строк
- TypeScript first

**Отклонены:**
- AG Grid Community — copy-paste только в Enterprise (~$1000/dev/год)
- Handsontable — коммерческая лицензия
- TanStack Table — headless, 2–4 дня ручной реализации Excel-механики
- Univer — избыточен, тяжёлый бандл, для нашей задачи лишнее
- Luckysheet — заброшен авторами

### Версии сметы: новая таблица `estimate_versions`
Хранит JSONB-строки для каждой версии. Позволяет переключаться между версиями без перепарсинга файлов.

---

## Структура данных

### Строка сметы (EstimateRow)
```typescript
interface EstimateRow {
  id: string;           // uuid для стабильных ключей грида
  lineage_id: string;  // стабильный идентификатор сквозь версии; при создании = id
  num: number;          // №
  type: 'work' | 'material' | 'section';  // Тип
  name: string;         // Наименование
  unit: string;         // Ед. изм.
  qty: number | null;   // Кол-во
  price_work: number | null;      // Цена работы, руб
  price_material: number | null;  // Цена материала, руб
  cost: number | null;            // Стоимость (авторасчёт: qty * (price_work + price_material))
  selected: boolean;              // Чекбокс выбора
  abc_group?: 'A' | 'B' | 'C';   // ABC-группа (для оптимизации)
  optimization_note?: string;     // Пометка об оптимизации
}
```

> **Механизм lineage_id:**
> - При парсинге оригинальной сметы: `lineage_id = id` (совпадает с uuid строки)
> - При создании новой AI-версии: Claude возвращает строки с `lineage_id` исходной строки для изменённых/сохранённых позиций, и новый UUID для добавленных
> - Удалённые строки просто отсутствуют в новой версии
> - `EstimateComparison` выравнивает строки по `lineage_id`, а не по `num`
> - Строки без пары в другой версии — `[+]` добавлена / `[−]` удалена

### Версия сметы (EstimateVersion)
```python
# backend/app/models/estimate_version.py
class EstimateVersion(Base):
    __tablename__ = "estimate_versions"
    id: UUID
    task_id: UUID (FK tasks.id, CASCADE DELETE)
    version_number: int          # 0=исходная, 1=после шага1, 2=после шага2, ...
    version_label: str           # Строго одно из: "original" | "client" | "completeness_checked" | "no_redundant" | "tech_optimized" | "material_optimized" | "custom"
    # Расшифровка:
    #   original           — исходная смета, загруженная пользователем
    #   client             — смета заказчика (если загружена)
    #   completeness_checked — результат Шага 1 (полнота и объёмы)
    #   no_redundant       — результат Шага 2 (убраны лишние позиции)
    #   tech_optimized     — результат Шага 3 (оптимизация технологий)
    #   material_optimized — результат Шага 4 (оптимизация материалов)
    #   custom             — ручная оптимизация выбранных строк (Шаг 6.6)
    # Кнопки OptimizationToolbar разблокируются именно по этим строкам — важно использовать точное написание
    version_display_name: str    # "Исходная смета" | "Смета заказчика" | "Оптимизация 1" ...
    rows: JSONB                  # List[EstimateRow]
    overhead_pct: Numeric(5,2)   # Накладные расходы, %
    transport_pct: Numeric(5,2)  # Транспортные расходы, %
    contingency_pct: Numeric(5,2) # Непредвиденные расходы, %
    expenses_overridden: bool    # True = версия использует свои %, не глобальные
    optimization_proposals: JSONB # Список предложений оптимизации (для шагов 2-4)
    is_rolled_back: bool          # True = версия откатана, скрыта в UI, но не удалена из БД
    created_at: DateTime
```

### Предложение оптимизации (OptimizationProposal)
```typescript
interface OptimizationProposal {
  id: string;
  row_id: string;                     // id строки, которую меняем
  proposal_type: 'add' | 'remove' | 'replace_tech' | 'replace_material' | 'price_search';
  description: string;                // что именно меняется
  explanation: string;                // пояснение на языке менеджера, почему безопасно
  economy_rub: number | null;         // экономия в рублях (null для price_search)
  confidence: 'high' | 'medium' | 'low';  // уверенность AI
  source?: string;                    // источник (для price_search)
  new_value?: Partial<EstimateRow>;   // новые значения строки
}
```

> В промпте каждого шага оптимизации обязательно: «Оцени уверенность своего предложения: high / medium / low. Если не уверен в коде ГЭСН — не называй его, напиши описание работы». Предложения с confidence=low отображаются в секции «Требует проверки специалиста» в OptimizationProposalsPanel.

---

## Фазы реализации

### Фаза 1 — Модель данных и миграция [x]

**Задачи:**
- [x] Создать `backend/app/models/estimate_version.py` с моделью `EstimateVersion`
- [x] Создать `backend/alembic/versions/014_add_estimate_versions.py` (IF NOT EXISTS)
- [x] Добавить `EstimateVersion` в `backend/app/models/__init__.py`
- [x] Создать Pydantic-схемы в `backend/app/schemas/estimate_version.py`:
  - `EstimateRowSchema` — включает поле:
    ```python
    lineage_id: str  # UUID; при создании = id, сохраняется через версии
    ```
  - `EstimateVersionCreate`
  - `EstimateVersionResponse`
  - `OptimizationProposalSchema`

**Миграция 014 (шаблон):**
```python
revision = "014"
down_revision = "013"

from sqlalchemy import inspect as sa_inspect

def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    return name in inspector.get_table_names()

def upgrade():
    if not _table_exists("estimate_versions"):
        op.create_table(
            "estimate_versions",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("task_id", sa.UUID(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("version_label", sa.String(50), nullable=False),
            sa.Column("version_display_name", sa.String(200), nullable=False),
            sa.Column("rows", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("overhead_pct", sa.Numeric(5, 2), nullable=False, server_default="0"),
            sa.Column("transport_pct", sa.Numeric(5, 2), nullable=False, server_default="0"),
            sa.Column("contingency_pct", sa.Numeric(5, 2), nullable=False, server_default="0"),
            sa.Column("expenses_overridden", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("optimization_proposals", sa.JSON(), nullable=True),
            sa.Column("is_rolled_back", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_estimate_versions_task_id", "estimate_versions", ["task_id"])
```

> Паттерн взят из миграции 005_task_history.py — это актуальный способ проверки таблицы для SQLAlchemy 2.0.

**Точки интеграции:**
- `backend/app/models/__init__.py` — импорт новой модели
- Alembic автоматически применит при деплое

---

### Фаза 2 — Backend: парсинг Excel и API [x]

#### 2.1 Парсинг Excel сметы [x]

Создать `backend/app/services/estimate_parser.py`:

**Функция `parse_estimate_excel(file_bytes: bytes) -> list[EstimateRow]`:**
- Открывает xlsx через openpyxl с обязательным параметром `data_only=True` — без него ячейки с формулами (например `=D5*F5`) вернут текст формулы вместо числа, и вся смета окажется пустой
- Пример вызова: `wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)`
- Ищет строку-заголовок (содержит "наименование" или "наименов" или "name" case-insensitive)
- Детектирует колонки по ключевым словам в заголовке:
  - №/num → `num`
  - Тип/вид → `type` (если нет — определяем эвристикой: строка с ценой работы = работа, с ценой матер. = материал)
  - Наименование → `name`
  - Ед./unit → `unit`
  - Кол/qty/количество → `qty`
  - Цена работ/труд/labor → `price_work`
  - Цена матер/material → `price_material`
  - Стоимость/сумма/итого → игнорируем (считаем сами)
- Пропускает секционные строки (нет qty и цен, только текст) — тип `section`
- Генерирует `uuid4` для каждого `id`
- Для каждой строки: `id = uuid4()`, `lineage_id = id` (при первичном парсинге они всегда равны)
- Возвращает список `EstimateRow`

**Эвристика типа строки (если колонки "Тип" нет):**
- Если `price_work > 0` и `price_material == 0` → `work`
- Если `price_material > 0` и `price_work == 0` → `material`
- Если оба > 0 → `work` (труд + свой материал)
- Если оба == 0 или null → `section`

#### 2.2 Новый task_type [x]

В `backend/app/constants.py`:
```python
ESTIMATE_TASK_TYPES: set[str] = {"ESTIMATE_FROM_LIST", "ESTIMATE_OPTIMIZATION"}
```

В `backend/app/services/task_processor.py`:
- Добавить ветку `elif task_type == "ESTIMATE_OPTIMIZATION":` в `process_task()`
- При создании задачи: парсим загруженный Excel → создаём `EstimateVersion` с `version_label="original"`
- Если загружен файл заказчика → парсим → создаём `EstimateVersion` с `version_label="client"`

#### 2.3 API endpoints [x]

Создать `backend/app/routers/estimate_versions.py`:

```
GET    /tasks/{task_id}/estimate/versions
       → список всех версий (без rows для скорости)

GET    /tasks/{task_id}/estimate/versions/{version_id}
       → полная версия включая rows

PUT    /tasks/{task_id}/estimate/versions/{version_id}/rows
       body: { rows: EstimateRow[] }
       → сохранить отредактированные строки

PUT    /tasks/{task_id}/estimate/versions/{version_id}/expenses
       body: { overhead_pct, transport_pct, contingency_pct }
       → сохранить доп. расходы только для этой версии

POST   /tasks/{task_id}/estimate/optimize/completeness
       → запустить шаг 1 (проверка полноты ГСН)
       → немедленный ответ: { "status": "running" }
       → прогресс через task.progress_data (polling GET /tasks/{task_id})

POST   /tasks/{task_id}/estimate/optimize/redundancy
       → запустить шаг 2 (проверка лишних позиций)
       → немедленный ответ: { "status": "running" }

POST   /tasks/{task_id}/estimate/optimize/technology
       → запустить шаг 3 (оптимизация технологий)
       → немедленный ответ: { "status": "running" }

POST   /tasks/{task_id}/estimate/optimize/materials
       → запустить шаг 4 (оптимизация материалов)
       → немедленный ответ: { "status": "running" }

POST   /tasks/{task_id}/estimate/optimize/custom
       body: { version_id: string, row_ids: string[] }
       → ручная оптимизация выбранных строк (синхронный, строк мало)
       → ответ: { proposals: OptimizationProposal[] }

POST   /tasks/{task_id}/estimate/apply-proposals
       body: { version_id, accepted_proposal_ids: string[] }
       → применить выбранные предложения, создать новую версию
```

#### Механизм прогресса шагов оптимизации

Все шаги (1–4) запускаются как **BackgroundTask** — сервер отвечает немедленно.

> **ВАЖНО — сессия базы данных в фоновых функциях:**
> Фоновая функция выполняется уже после того, как запрос завершён, и соединение с базой из запроса уже закрыто. Поэтому фоновая функция должна открывать **собственное** соединение с базой — так же, как это сделано в `_run_task_in_background` в `backend/app/routers/tasks.py`. Нельзя передавать `db` из параметров роута в фоновую функцию — это сломается при первом обращении к базе.
Прогресс пишется в существующие поля модели `Task`:

```python
# После каждого чанка:
task.progress_message = "Анализ технологий: 3 из 7 позиций"
task.progress_data = {
    "opt_step": "technology",         # шаг оптимизации
    "chunks_done": 3,
    "chunks_total": 7,
    "partial_proposals": [...],       # накопленные предложения
}
await db.commit()

# После завершения:
task.progress_message = None
task.progress_data = {
    "opt_step": "technology",
    "status": "done",
    "proposals": [...],               # все предложения
}
```

Фронтенд: при состоянии кнопки `running` — polling `GET /tasks/{task_id}` каждую секунду.
Читает `progress_data.chunks_done` / `chunks_total` → показывает «Анализ: 3 из 7 позиций».
Когда `progress_data.status == "done"` → показывает панель предложений, polling останавливается.

> **Фронтенд — уточнения к polling:**
> - Polling раз в 3 секунды (не раз в секунду)
> - При сетевой ошибке — exponential backoff: 3с → 6с → 12с → 30с
> - При восстановлении соединения (`navigator.onLine` event) — немедленный запрос
> - Пока идёт оптимизация — баннер в гриде содержит: «[прогресс из progress_message]. Анализ выполняется в фоне — вы можете закрыть страницу, результаты сохранятся.»
> - Кнопка «Отменить» в баннере (с диалогом подтверждения) — для ситуации «запустил не тот шаг»

Подключить роутер в `backend/app/main.py`.

**Точки интеграции:**
- `backend/app/main.py` — `app.include_router(estimate_versions_router)`
- `backend/app/constants.py` — добавить в ESTIMATE_TASK_TYPES
- `backend/app/services/task_processor.py` — новая ветка task_type

---

### Фаза 3 — Frontend: загрузка файлов и роутинг [x]

#### 3.1 Установка react-data-grid [x]

```bash
npm install react-data-grid
```

Типы встроены начиная с react-data-grid v7 — `@types/react-data-grid` устанавливать не нужно, вызовет конфликт.

В `frontend/vite.config.ts` убедиться что CSS импорт работает:
```ts
// react-data-grid требует импорт CSS в компоненте:
// import 'react-data-grid/lib/styles.css';
```

#### 3.2 Новый тип задачи в UI [x]

В `frontend/src/types/index.ts`:
```typescript
// Добавить в TASK_TYPE_LABELS:
'ESTIMATE_OPTIMIZATION': 'Оптимизация сметы',

// Добавить в ESTIMATE_TASK_TYPES:
ESTIMATE_TASK_TYPES.add('ESTIMATE_OPTIMIZATION');
```

В `frontend/src/components/TaskTypeSelector.tsx`:
- Добавить карточку для `ESTIMATE_OPTIMIZATION`
- Описание: "Загрузите смету себестоимости для оптимизации тендерного предложения"

#### 3.3 Обновление TaskCreate.tsx [x]

В `frontend/src/pages/TaskCreate.tsx` добавить ветку для `ESTIMATE_OPTIMIZATION`:

**Поле 1** (обязательное): "Наша смета себестоимости" — один xlsx файл → слот `estimate`

**Поле 2** (необязательное): "Файлы от заказчика" — с выбором типа файла перед загрузкой:
```
Выберите вид файла:  ○ Смета  ○ Проект  ○ ТЗ  ○ Другое
[Загрузить файл]
```
- Тип "Смета" → парсируем как EstimateRow[] → создаём версию `version_label="client"`, `version_display_name="Смета заказчика"`
- Тип "Проект" / "ТЗ" / "Другое" → сохраняем как файл в слот `source` (для контекста AI, без парсинга)
- Тип выбора сохраняется в поле `client_file_type` задачи (добавить в `user_prompt` как JSON-метаданные, миграция не нужна — `user_prompt` уже есть)
- Можно загрузить несколько файлов разного типа (добавить ещё одно поле)

**Отдельные `FileUpload`** компоненты для каждого поля с чёткими подписями.

#### 3.4 Новый роут и страница [x]

В `frontend/src/App.tsx`:
```tsx
<Route path="/tasks/:taskId/estimate" element={<ProtectedRoute><EstimateOptimizer /></ProtectedRoute>} />
```

После создания задачи типа `ESTIMATE_OPTIMIZATION` редирект на `/tasks/:taskId/estimate` вместо обычного статуса.

#### 3.5 API-методы [x]

Создать или дополнить `frontend/src/api/estimateVersions.ts`:
```typescript
getVersions(taskId: string): Promise<EstimateVersionSummary[]>
getVersion(taskId: string, versionId: string): Promise<EstimateVersionFull>
saveRows(taskId: string, versionId: string, rows: EstimateRow[]): Promise<void>
saveExpenses(taskId: string, versionId: string, expenses: Expenses): Promise<void>
runOptimization(taskId: string, step: OptimizationStep): Promise<{ status: 'running' }>
runCustomOptimization(taskId: string, versionId: string, rowIds: string[]): Promise<{ proposals: OptimizationProposal[] }>
applyProposals(taskId: string, versionId: string, acceptedIds: string[]): Promise<EstimateVersionFull>
// Прогресс читается через getTask(taskId) — поля progress_message и progress_data
```

---

### Фаза 4 — Редактор сметы (EstimateGrid) [x]

#### 4.1 Страница EstimateOptimizer [x]

Создать `frontend/src/pages/EstimateOptimizer.tsx`:

```
Структура страницы:
┌─────────────────────────────────────────────────────┐
│ [OptimizationToolbar] — кнопки шагов оптимизации    │
├─────────────────────────────────────────────────────┤
│ [VersionTabs] — заказчик | исходная | v1 | v2 | ... │
├─────────────────────────────────────────────────────┤
│ [EstimateGrid]                                       │
│   Вкладки: [Полный] [Работы] [Материалы]            │
│   ┌──┬───────┬──────────────┬────┬───┬────┬────┬──┐ │
│   │☐ │  №   │ Наименование │ Ед │ Кол│Цр  │Цм  │ ∑│ │
│   └──┴───────┴──────────────┴────┴───┴────┴────┴──┘ │
│   [строки...]                                        │
│   ─────────────────────────────────────────────────  │
│   [AdditionalExpenses] накл/трансп/непредвид         │
│   [EstimateSummary] итоги                            │
└─────────────────────────────────────────────────────┘
```

#### 4.2 EstimateGrid компонент [x]

Создать `frontend/src/components/estimate/EstimateGrid.tsx`:

```typescript
// Колонки для вкладки "Полный перечень"
const ALL_COLUMNS: Column<EstimateRow>[] = [
  { key: 'selected', name: '', width: 40, frozen: true, renderCell: CheckboxCell, renderHeaderCell: SelectAllCheckbox },
  { key: 'num', name: '№', width: 50, frozen: true },
  { key: 'type', name: 'Тип', width: 90, renderCell: TypeBadge },
  { key: 'name', name: 'Наименование', width: 320, renderEditCell: TextEditor },
  { key: 'unit', name: 'Ед. изм.', width: 80, renderEditCell: TextEditor },
  { key: 'qty', name: 'Кол-во', width: 80, renderEditCell: NumberEditor },
  { key: 'price_work', name: 'Цена работы, руб', width: 130, renderEditCell: NumberEditor },
  { key: 'price_material', name: 'Цена материала, руб', width: 150, renderEditCell: NumberEditor },
  { key: 'cost', name: 'Стоимость, руб', width: 130, renderCell: CostCell },  // только чтение, авторасчёт
];

// Вкладка "Работы" — убираем price_material
// Вкладка "Материалы" — убираем price_work
```

**Расчёт cost (только в коде, без API):**
```typescript
const cost = (row.qty ?? 0) * ((row.price_work ?? 0) + (row.price_material ?? 0));
```

**Чекбокс:** `frozen: true`, клик меняет `selected` в локальном стейте. При переключении вкладок сохраняем `selectedIds: Set<string>` в Zustand-сторе.

**Авторасчёт при редактировании:** `onRowsChange` пересчитывает `cost` для изменённой строки, обновляет локальный стейт. Debounced (500ms) сохранение на сервер через `saveRows`.

**Блокировка во время оптимизации:** если `optimizationStep === 'running'` — грид переходит в `readonly` режим (`editable: false` для всех колонок). Пользователь видит баннер «Анализ выполняется, редактирование недоступно». После завершения шага грид разблокируется автоматически.

> **Порядок при запуске оптимизации:**
> 1. При нажатии кнопки оптимизации — немедленно сбросить debounce и синхронно вызвать `saveRows()`
> 2. Кнопка показывает состояние "Сохранение..." пока save в процессе
> 3. Только после получения ответа `200 OK` от saveRows — отправить POST на endpoint оптимизации и перевести грид в readonly

**Счётчик незаполненных цен:**
- Над гридом — персистентная строка: "⚠ 3 позиции требуют заполнения цены" (если есть такие строки)
- Клик на счётчик — прокрутка к первой незаполненной строке, она мигает
- Строка считается незаполненной если: тип `work` или `material`, и `price_work == null || price_material == null`, и строка была добавлена AI (поле `optimization_note != null`)

**Логика кнопки "Зафиксировать версию":**
- Кнопка всегда активна
- Если есть незаполненные строки — при нажатии показывается диалог подтверждения:
  «Версия содержит позиции без цены: [список названий строк]. Они будут зафиксированы с нулевой стоимостью. Продолжить?»
- Пользователь может нажать "Продолжить" или "Вернуться и заполнить"

**Ручная фиксация версии:** В заголовке грида (над таблицей) — кнопка «Сохранить как версию». Доступна всегда, независимо от AI-шагов. Создаёт новую версию с `version_label="custom"` и `version_display_name="Ручная правка [время]"`. Используется опытным сметчиком для фиксации промежуточного состояния без оптимизации.

#### 4.3 AdditionalExpenses компонент [x]

Создать `frontend/src/components/estimate/AdditionalExpenses.tsx`:

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Накладные расходы      [____]%  = 125 400 руб                            │
│ Транспортные расходы   [____]%  = 62 700 руб                             │
│ Непредвиденные расходы [____]%  = 31 350 руб                             │
│                                                                          │
│  [Сохранить]                                                             │
└──────────────────────────────────────────────────────────────────────────┘
```

**Логика доп. расходов:**
- "Сохранить" → обновляет `overhead_pct/transport_pct/contingency_pct` только для текущей версии
- Авторасчёт в реальном времени при изменении % (только в коде)

**API:**
```
PUT /tasks/{task_id}/estimate/versions/{id}/expenses  ← только в этой версии
```

#### 4.4 EstimateSummary компонент [x]

Создать `frontend/src/components/estimate/EstimateSummary.tsx`:

```
Работы:          1 254 000 руб
Материалы:         627 000 руб
─────────────────────────────
Итого (базис):   1 881 000 руб
Накладные (10%):   188 100 руб
Транспорт (5%):     94 050 руб
Непредвиден. (3%):  56 430 руб
─────────────────────────────
Итого:           2 219 580 руб
НДС 22%:           488 527 руб
─────────────────────────────
ИТОГО с НДС:     2 708 107 руб
```

Все расчёты — только `useMemo` от rows и expense percentages. Без API.

НДС = **22%** (подтверждено).

---

### Фаза 5 — Версионность и сравнение [x]

#### 5.1 VersionTabs компонент [x]

Создать `frontend/src/components/estimate/VersionTabs.tsx`:

```
Вкладки (появляются по мере создания версий):
[Смета заказчика] [Исходная смета] [Оптимизация 1] [Оптимизация 2] [Оптимизация 3] [Сравнение]
```

- Вкладки "Смета заказчика" — только если загружен файл заказчика
- Вкладки оптимизации — только если версия уже создана
- Активная вкладка → загружаем соответствующую версию через `getVersion()`
- Любую версию можно редактировать. Изменения сохраняются в той версии, которая активна в данный момент. Следующий шаг AI-оптимизации использует самую последнюю незаблокированную (is_rolled_back=false) версию — это явно показывается в OptimizationToolbar: «Следующий шаг запустится на основе: [название версии]»

**Контекстное меню версии:**
Каждая вкладка версии имеет кнопку "⋯" (три точки), при клике — меню:
- "Переименовать версию"
- "Откатиться к этой версии" (если версия не последняя)

При выборе "Откатиться": диалог подтверждения — «Все версии после "[название]" будут скрыты. Они сохранятся в истории, но не будут отображаться. Продолжить?». Кнопка отката недоступна во время выполнения AI-шага (уже описано выше).

**Ограничение вкладок:** показывается максимум 5 вкладок. Если версий больше — последняя вкладка превращается в «Ещё... (N)» — dropdown со списком остальных версий. Вкладка «Сравнение» всегда закреплена последней.

**Откат версий через TaskHistory:**

В проекте уже есть `TaskHistory` (`backend/app/models/history.py`) с endpoint `POST /tasks/{task_id}/history/{entry_id}/revert`.

> **ВАЖНО — нельзя откатывать во время работы AI:**
> Пока идёт один из шагов оптимизации (шаги 1–4), кнопка отката заблокирована в UI. Это нужно потому, что AI-анализ работает в фоне и пишет результаты в базу. Если позволить откатиться прямо в этот момент, результаты AI-анализа запишутся поверх отката и смета окажется в непредсказуемом состоянии. Разблокировать кнопку отката только после того, как шаг завершился (или завершился с ошибкой).

При фиксации каждой версии сметы → пишем запись в `TaskHistory`:
```python
TaskHistory(
    task_id=task_id,
    operation_type="estimate_version",
    slot=f"version_{version.version_number}",
    description=f"Зафиксирована {version.version_display_name}",
    previous_value={},                          # нет предыдущего состояния
    new_value={"version_id": str(version.id)},  # ссылка на версию
)
```

Откат = удаление версии из `estimate_versions` по `version_id` из `new_value`. Версии не физически удаляются из estimate_versions до отката — только помечаются `is_rolled_back: bool` (добавить поле в модель). Это позволяет сохранить историю даже после отката.

#### 5.2 EstimateComparison компонент [x]

Создать `frontend/src/components/estimate/EstimateComparison.tsx`:

**Верхняя часть — итоги по версиям:**
```
                     Заказчик    Исходная    Опт.1       Опт.2
Работы:           2 500 000   1 254 000   1 100 000     980 000
Материалы:          800 000     627 000     580 000     540 000
Итого (базис):    3 300 000   1 881 000   1 680 000   1 520 000
ИТОГО с НДС:      3 960 000   2 257 200   2 016 000   1 824 000
Экономия к исх.:           —           —     −241 200    −433 200
% к смете заказчика:         —           —     −12.0%      −19.2%
```

> Строка "% к смете заказчика" отображается только если загружена версия с `version_label="client"`. Расчёт: `(итого_с_НДС_версии - итого_с_НДС_заказчика) / итого_с_НДС_заказчика * 100`.

**Доступность:** Цветовая кодировка (зелёный = дешевле, красный = дороже) дублируется стрелками и знаком: «↓ −18 400 руб» (зелёный) и «↑ +5 200 руб» (красный). Число со знаком показывает разницу к исходной версии.

**Таблица построчно:**
```
№ | Тип | Наименование | Ед | Кол | Цена заказчика | Цена исходная | Цена опт.1 | Цена опт.2
```

- Пользователь выбирает checkbox какие версии показывать (из доступных)
- Если цена версии отличается от исходной — выделяем цветом (зелёный = дешевле, красный = дороже)
- Строки у которых все версии одинаковые — не выделяем

**Как совмещать строки из разных версий:**

Строки выравниваются по полю `lineage_id` (не по `num`).

Алгоритм:
1. Собрать все уникальные `lineage_id` из всех сравниваемых версий
2. Для каждого `lineage_id` — взять строку из каждой версии (или прочерк если отсутствует)
3. Сортировать по порядку появления в исходной версии (version_label="original")
4. Новые строки (присутствуют только в более поздней версии) — добавляются в конец с иконкой `[+]` и светло-зелёным фоном строки
5. Удалённые строки (присутствуют в ранней версии, отсутствуют в поздней) — показываются с иконкой `[−]` и светло-красным фоном строки

Tooltip на иконках: `[+]` — «Эта позиция добавлена в [название версии]», `[−]` — «Эта позиция исключена в [название версии]».

В итоговой строке "Экономия к исх." сноска: «Включает все позиции, в т.ч. добавленные и исключённые».

**Стейт:**
```typescript
const [selectedVersionIds, setSelectedVersionIds] = useState<string[]>([]);
```

---

### Фаза 6 — Модуль оптимизации [x]

#### 6.1 OptimizationToolbar компонент [x]

Создать `frontend/src/components/estimate/OptimizationToolbar.tsx`:

Кнопки появляются последовательно, каждая разблокируется после завершения предыдущего шага:

```
[✓ Проверить лишнее (что можно убрать)] → [✓ Проверить полноту по ГСН (всё ли учтено)] → [Оптимизация технологий (как сделать дешевле)] → [Оптимизация материалов (замена поставщиков)]
```

Логика разблокировки (по наличию версий):
- Кнопка 1 всегда активна после загрузки файла
- Кнопка 2 → после того как версия `"completeness_checked"` существует
- Кнопка 3 → после `"no_redundant"`
- Кнопка 4 → после `"tech_optimized"`

Состояние кнопки: `idle` | `running` (spinner) | `done` (галочка)

#### 6.2 Шаг 1 — Проверка полноты и соответствия объёмов [x]

> Методология согласована: `smeta-ai/specs/2026-04-23-step1-completeness-methodology.md`

**Три подшага с отдельными кнопками:**

```
[1.1 Сверка с заказчиком]  →  [1.2 Проверка объёмов]  →  [1.3 Проверка по ГЭСН]
```

- 1.1 неактивна без файла заказчика: кнопка видна, серая. Под кнопкой постоянная подпись: «Загрузите смету или ТЗ заказчика при создании задачи». Кнопка 1.2 всегда активна.
- Кнопки разблокируются последовательно
- Результаты накапливаются в панели под тулбаром
- Пользователь принимает предложения по одному — кнопки "Добавить" или "Пометить"
- Кнопка "Зафиксировать как Версию 1" / "Обновить Версию 1" — появляется после первого запущенного подшага
  - При ховере на «Обновить Версию 1» — tooltip: «Версия 1 уже создана в [время]. Нажатие обновит её строки без создания дубликата.»
  - Рядом с кнопкой индикатор состояния: «Версия 1 — создана в 14:32»
- Откат через `TaskHistory`
- `extra_in_ours` из подшага 1.1 → автоматически в список подозрительных Шага 2

**Что происходит при нажатии "Добавить" (предложение: отсутствующая позиция):**

AI нашёл, что какая-то позиция из сметы заказчика отсутствует в нашей смете. Пользователь нажимает "Добавить". Происходит следующее:
1. В конце списка строк сметы появляется новая строка с названием, единицей измерения и количеством, которые взяты из предложения AI
2. Поля цены (цена работы и цена материала) остаются пустыми — их должен заполнить пользователь вручную
3. Строка подсвечивается жёлтым цветом и получает пометку "⚠ Требует заполнения цены" — чтобы пользователь не забыл про неё
4. Пока у строки нет цены, она учитывается в итоге как ноль, но остаётся видна в таблице

**Что происходит при нажатии "Пометить как подозрительную" (предложение: лишняя позиция):**

AI нашёл, что у нас есть позиция, которой нет у заказчика. Пользователь нажимает "Пометить". Происходит следующее:
1. Строка получает пометку `optimization_note = "подозрительная"` и отображается с серым фоном в таблице
2. Строка автоматически добавляется в список подозрительных для Шага 2 (проверка лишних позиций) — не нужно добавлять вручную
3. Строка не удаляется из сметы — только помечается. Удаление — это решение Шага 2, не Шага 1

**Промпты, форматы ответов, UX-детали:** см. `specs/2026-04-23-step1-completeness-methodology.md`

#### 6.3 Шаг 2 — Проверка на лишние позиции [x]

> Методология согласована: `smeta-ai/specs/2026-04-23-step2-redundancy-methodology.md`

**Промпты, форматы ответов, UX-детали:** см. `specs/2026-04-23-step2-redundancy-methodology.md`

#### 6.4 Шаг 3 — Оптимизация по технологиям [x]

> Методология согласована: `smeta-ai/specs/2026-04-23-step3-technology-methodology.md`

**Промпты, форматы ответов, UX-детали:** см. `specs/2026-04-23-step3-technology-methodology.md`

#### 6.5 Шаг 4 — Оптимизация по материалам [x]

> Методология согласована: `smeta-ai/specs/2026-04-23-step4-materials-methodology.md`

**Промпты, форматы ответов, UX-детали:** см. `specs/2026-04-23-step4-materials-methodology.md`

> **Важно для всех шагов оптимизации (6.2–6.5):**
>
> В промпте каждого шага Claude должен получить строки с их `lineage_id` и вернуть результат в формате, где каждая строка содержит `lineage_id`:
> - Для сохранённых/изменённых строк — `lineage_id` из исходной строки
> - Для новых строк — новый UUID (сгенерировать на стороне бэкенда после получения ответа)
> - Удалённые строки просто не включаются в ответ
>
> Бэкенд после получения ответа Claude:
> 1. Для каждой строки без `lineage_id` — сгенерировать новый `uuid4()` и установить как `lineage_id`
> 2. Создать новую `EstimateVersion` с обновлёнными строками

#### 6.6 Ручной выбор позиций + "Предложить варианты" [x]

> Методология согласована: `smeta-ai/specs/2026-04-23-step-custom-optimization-methodology.md`

В EstimateGrid:
- При наличии отмеченных чекбоксами строк → показывается кнопка "Предложить варианты оптимизации (N строк)"
- Клик → отправляет выбранные row IDs на `POST /optimize/custom` (синхронный, без чанкинга)
- Claude анализирует по трём направлениям: замена технологии, замена материала, поиск цен в интернете с источниками
- Возвращает карточки предложений (тот же `OptimizationProposalsPanel`)
- Предложения `technology` и `material` → «Принять/Отклонить» → создаёт новую версию «Ручная оптимизация N»
- Предложения `price_search` — информационные, смету не меняют, источники показываются явно
- Доступно в любой момент независимо от шагов 1–4

#### 6.7 OptimizationProposalsPanel компонент [x]

Создать `frontend/src/components/estimate/OptimizationProposalsPanel.tsx`:

Панель предложений показывается под тулбаром после завершения шага. Содержит:
- Заголовок: «Предложения по оптимизации (N)»
- Кнопки массового управления:
  - «Принять все (N)» — с диалогом подтверждения, применяет все предложения разом
  - «Принять все по группе» — dropdown: «Технологии (N)» / «Материалы (N)»
- Список карточек предложений, отсортированных по убыванию `economy_rub`
- Предложения с `confidence=low` сгруппированы в секцию «Требует проверки специалиста» в конце
- Каждая карточка: название строки, что меняется, экономия в руб, `explanation` от AI, кнопки «Принять» / «Отклонить»
- Checkbox-выбор для группового «Принять выбранные (N)»

---

### Фаза 7 — Экспорт [x]

#### 7.1 Скачать версию как Excel [x]

Добавить кнопку «Скачать .xlsx» рядом с каждой вкладкой версии (в VersionTabs).

**Backend endpoint:**
```
GET /tasks/{task_id}/estimate/versions/{version_id}/export
→ Генерирует xlsx из version.rows + доп. расходы + итоги
→ Использует существующий excel_service.py для генерации файла
→ Content-Disposition: attachment; filename="smeta_{version_display_name}.xlsx"
```

**Структура экспортируемого файла:**
- Лист "Смета": все строки из rows
- Строки доп. расходов (накладные, транспорт, непредвиденные)
- Итоговые строки (базис, общий итог, НДС 22%, итого с НДС)

#### 7.2 Экспорт сравнения [x]

В EstimateComparison добавить кнопку «Скачать сравнение .xlsx».

**Backend endpoint:**
```
POST /tasks/{task_id}/estimate/comparison/export
body: { version_ids: string[] }
→ Генерирует многоколоночный xlsx с выбранными версиями рядом
→ Строки выровнены по lineage_id (см. Фазу 5)
→ Ячейки с ценой дешевле исходной — зелёный фон, дороже — красный
```

**Точки интеграции:**
- `backend/app/routers/estimate_versions.py` — новые endpoints
- `backend/app/services/excel_service.py` — функция `generate_estimate_export()`

---

## Zustand store для редактора

Создать `frontend/src/stores/estimateEditor.ts`:

```typescript
interface EstimateEditorState {
  taskId: string | null;
  versions: EstimateVersionSummary[];
  activeVersionId: string | null;
  activeRows: EstimateRow[];
  selectedRowIds: Set<string>;
  activeTab: 'all' | 'works' | 'materials';
  compareVersionIds: string[];
  optimizationStep: 'idle' | 'running' | OptimizationStepType;
  proposals: OptimizationProposal[];
  
  // Actions
  loadVersions: (taskId: string) => Promise<void>;
  setActiveVersion: (versionId: string) => Promise<void>;
  updateRow: (rowId: string, changes: Partial<EstimateRow>) => void;
  saveRows: () => Promise<void>;
  toggleRowSelection: (rowId: string) => void;
  selectAll: () => void;
  deselectAll: () => void;
}
```

---

## Карта файлов

### Новые файлы Backend
```
backend/app/models/estimate_version.py
backend/app/schemas/estimate_version.py
backend/app/services/estimate_parser.py      ← парсинг Excel в EstimateRow[]
backend/app/routers/estimate_versions.py
backend/alembic/versions/014_add_estimate_versions.py
```

### Новые файлы Frontend
```
frontend/src/pages/EstimateOptimizer.tsx
frontend/src/stores/estimateEditor.ts
frontend/src/api/estimateVersions.ts
frontend/src/components/estimate/
  ├── EstimateGrid.tsx
  ├── EstimateGrid.css
  ├── VersionTabs.tsx
  ├── OptimizationToolbar.tsx
  ├── OptimizationProposalsPanel.tsx
  ├── AdditionalExpenses.tsx
  ├── EstimateSummary.tsx
  └── EstimateComparison.tsx
```

### Изменяемые файлы
```
backend/app/models/__init__.py              ← +EstimateVersion импорт
backend/app/constants.py                   ← +ESTIMATE_OPTIMIZATION в ESTIMATE_TASK_TYPES
backend/app/services/task_processor.py     ← +ветка ESTIMATE_OPTIMIZATION
backend/app/services/excel_service.py      ← +generate_estimate_export()
backend/app/main.py                        ← +include_router(estimate_versions)
frontend/src/App.tsx                       ← +новый route
frontend/src/types/index.ts                ← +новые типы и константы
frontend/src/components/TaskTypeSelector.tsx ← +карточка нового типа
frontend/src/pages/TaskCreate.tsx          ← +двойной upload для ESTIMATE_OPTIMIZATION
```

---

## Согласованные решения

1. **НДС:** 22% ✅
2. **Доп. расходы:** одна кнопка «Сохранить» — сохраняет только в текущей версии. Глобального обновления всех версий нет. ✅
3. **Файл заказчика:** если тип = "Смета" — парсим → создаём версию `version_label="client"`. Если "Проект" / "ТЗ" / "Другое" — храним как файл, используем как контекст для AI ✅
4. **Ручная оптимизация:** создаёт отдельную версию ✅
5. **Шаг 1:** создаёт версию вручную ("Зафиксировать") — не автоматически. Можно сохранить после любого подшага, обновить после следующего ✅
6. **Последовательность шагов:** строго 1→2→3→4. Пропуск шагов не предусмотрен — каждый шаг принимает на вход результат предыдущего. ✅
7. **Редактирование версий:** любую версию можно редактировать (не только активную). Следующий AI-шаг использует последнюю незаблокированную версию. ✅
8. **Принятие предложений:** доступно поштучно и массово («Принять все» / «Принять по группе»). ✅
9. **Уверенность AI:** каждое предложение содержит поле confidence (high/medium/low). Предложения с low — в секции «Требует проверки». ✅
10. **ГСН-коды:** в промпте инструкция «если не уверен в коде ГЭСН — не называй его, напиши описание». ✅

---

## Итоговый блок

**Реализован:** ✅ Полностью (фазы 1–7 завершены)  
**Текущий статус:** Фаза 7 завершена — generate_estimate_export() и generate_comparison_export() в excel_service.py; endpoints GET /export и POST /comparison/export в estimate_versions.py; кнопка «⬇ Скачать .xlsx» в контекстном меню VersionTabs; кнопка «⬇ Скачать сравнение .xlsx» в EstimateComparison с состоянием загрузки.  
**Следующий шаг:** Нет. Все 7 фаз реализованы.
