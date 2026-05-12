# Сводная себестоимость — многолистовой редактор смет

**Статус:** [ ] В работе (Фаза 1 завершена)  
**Создан:** 2026-05-12  
**Размер задачи:** L (10+ файлов, новая модель БД, новый раздел UI)

---

## Проблема

Проект в smeta-ai содержит несколько разделов (АС, ЭОМ, Демонтаж АС и т.д.). Каждый раздел — это цепочка задач с несколькими версиями сметы. Сейчас суммарная стоимость проекта — это просто `SUM(Task.cost)`, без структуры: нет разбивки по разделам, нет итоговой таблицы для заказчика, нет редактируемого сводного документа. Отдел продаж вынужден собирать итог вручную в Excel.

## Цель

Дать пользователю инструмент для:
1. Выбора «заглавной» версии сметы из каждого раздела
2. Редактирования строк разделов в онлайн-редакторе (вкладки)
3. Автоматического расчёта Сводного листа (итоги по работам/материалам, НДС, прибыль, сумма для заказчика)
4. Экспорта итога в многолистовой Excel
5. Подтягивания итоговой суммы проекта из Сводной таблицы

---

## Challenge Log

### 1. Решает ли план проблему?

| Критерий приёмки | Покрыт? | Где |
|---|---|---|
| Выбор заглавной версии для раздела | ✅ | Фаза 1: `primary_version_id` на `WorkflowCard` |
| Модальный выбор разделов в сводную | ✅ | Фаза 4: `SectionSelector.tsx` |
| Редактор с вкладками (раздел + Сводная) | ✅ | Фаза 4: `SummaryEditor.tsx` |
| Редактирование строк разделов | ✅ | Фаза 4: переиспользует `EstimateGrid` |
| Автопересчёт Сводной при изменениях | ✅ | Фаза 4: `useSummaryEditorStore` + `calcSummary()` |
| Экспорт в многолистовой xlsx | ✅ | Фаза 2: `generate_summary_xlsx()` + эндпоинт |
| Сумма проекта из Сводной | ✅ | Фаза 5: `Project.summary_total` |

### 2. Самое эффективное решение?

**Выбранный подход:** `react-data-grid` (уже в проекте) + кастомный `SummarySheet`

**Альтернативы:**

| Подход | Плюсы | Минусы | Почему отклонён |
|---|---|---|---|
| FortuneSheet + SheetJS | Нативный multi-sheet, формулы | ~500 KB нов. зависимость, скудная документация, формулы не нужны | Формульный движок избыточен — расчёты детерминированы (JS) |
| Jspreadsheet CE | Multi-sheet, xlsx-экспорт | Не нативный React, формулы платные, ограниченный CE | Дополнительные ограничения и стиль отличается от проекта |
| react-data-grid + кастомный SummarySheet | Уже установлен, единый стиль, undo/redo/autosave уже есть | SummarySheet нужно писать вручную | **Выбран** — минимальные новые зависимости, максимальное переиспользование |

### 3. Нет ли кода ради кода?

- Не рефакторим `EstimateGrid` — используем как есть
- Не трогаем существующую агрегацию `SUM(Task.cost)` до Фазы 5 (обратная совместимость)
- Не меняем `EstimateVersion` — только добавляем `primary_version_id` на `WorkflowCard`
- Каждое изменение напрямую служит критериям приёмки

---

## Архитектура

### Новые модели БД

**1. Изменение `WorkflowCard`** (миграция `014`):
```python
primary_version_id: UUID | None  # FK → EstimateVersion, SET NULL on delete
```

**2. Новая модель `SummaryEstimate`** (миграция `015`):
```python
class SummaryEstimate(Base):
    id: UUID (PK)
    project_id: UUID (FK → Project, CASCADE DELETE, UNIQUE)
    
    # Массив выбранных разделов с их строками (snapshot при создании/сохранении)
    sections: JSON
    # [{card_id, card_name, version_id, rows: [EstimateRow]}]
    
    # Настраиваемые % для сводного листа (редактируются пользователем)
    overrides: JSON
    # {transport_pct, cleanup_pct, overhead_pct, daily_workers_cost,
    #  bank_guarantee_cost, cleaning_cost, ppr_cost, commissioning_cost,
    #  contingency_pct, profit_pct, vat_works_pct, vat_materials_pct, tax_pct}
    
    total_for_customer: Decimal(14, 2)  # кэш для ProjectCardResponse
    created_at, updated_at
```

### Новые API эндпоинты

```
GET    /projects/{project_id}/summary              → SummaryEstimateResponse | 404
POST   /projects/{project_id}/summary              → создать из выбранных карт
PUT    /projects/{project_id}/summary              → сохранить изменения строк + overrides
GET    /projects/{project_id}/summary/export       → скачать .xlsx

PATCH  /workflow-cards/{card_id}/primary-version   → {version_id: UUID | null}
```

### Структура фронтенда

```
frontend/src/
├── pages/
│   └── SummaryEditor.tsx          ← новая страница
├── components/summary/
│   ├── SectionSelector.tsx         ← модальный выбор разделов и версий
│   ├── SummarySheet.tsx            ← Сводный лист (две таблицы из скрина)
│   └── SummaryEditorTabs.tsx       ← табы: разделы + Сводная
├── stores/
│   └── summaryEditorStore.ts       ← новый Zustand-стор
└── api/
    └── summaryEstimate.ts          ← API-клиент
```

### Логика SummarySheet

Два блока (как на скриншоте):

**Левая таблица** (себестоимость + цена для заказчика):
```
1. Работы               = SUM(row.price_work × row.qty) по всем разделам
2. Материалы            = SUM(row.price_material × row.qty) по всем разделам
3. Транспортные расходы = Материалы × transport_pct%
4. Уборка и вывоз мусора = Работы × cleanup_pct%
5. Накладные            = Работы × overhead_pct%
6. Разнорабочие ежедневно = (ручной ввод, руб.)
7. Банковская гарантия  = (ручной ввод, руб.)
8. Клининг              = (ручной ввод, руб.)
9. РД (ППР), исполнит.  = (ручной ввод, руб.)
10. Пусконаладочные     = (ручной ввод, руб.)
─────────────────────────────────────────────
ИТОГО Себестоимость     = SUM(1..10)
Непредвиденные расходы  = ИТОГО × contingency_pct%
Плановая прибыль        = ИТОГО × profit_pct%
Полная себестоимость    = ИТОГО + Непредвиденные + Прибыль
НДС                     = Полная с/с × vat_pct%
Др. налоги              = Полная с/с × tax_pct%
ИТОГО для Заказчика     = Полная с/с + НДС + Налоги
```

**Правая таблица** (разбивка по разделам):
```
Раздел | Работы (с/с) | Ставка НДС | Стоимость с НДС 22% | Материалы (с/с) | Ставка НДС | Стоимость с НДС 20%
для каждого раздела из sections[]
─────
ИТОГО | ...
```

**НДС на работы = 22%, на материалы = 20%** (как на скриншоте — разные ставки).

---

## Фазы реализации

### Фаза 1 — Миграции и модели бэкенда
**Статус:** [x]

- [x] Миграция `021_add_primary_version_to_workflow_card.py` — добавить `primary_version_id` с `IF NOT EXISTS` (нумерация 021/022, т.к. 014-020 уже заняты)
- [x] Миграция `022_add_summary_estimate.py` — создать таблицу `summary_estimates` с `IF NOT EXISTS`
- [x] Модель `SummaryEstimate` в `backend/app/models/summary_estimate.py`
- [x] Обновить `backend/app/models/__init__.py`
- [x] Схемы Pydantic: `SummaryEstimateCreate`, `SummaryEstimateUpdate`, `SummaryEstimateResponse`, `SummaryOverrides`, `SectionInput`
- [x] Обновить `WorkflowCard` модель: добавить поле `primary_version_id`
- [x] Обновить `WorkflowCardResponse` схему: добавить `primary_version_id`
- [x] Gate: pytest — 91 passed (8 fail pre-existing, все из-за fitz/render.yaml), ruff на новых файлах чистый

### Фаза 2 — API эндпоинты и Excel-экспорт
**Статус:** [ ]

- [ ] `backend/app/routers/summary.py` — CRUD эндпоинты (`GET`, `POST`, `PUT`)
- [ ] Эндпоинт `PATCH /workflow-cards/{card_id}/primary-version` в `routers/workflow_cards.py`
- [ ] `backend/app/services/summary_service.py` — бизнес-логика: сборка sections из WorkflowCard + выбранной версии
- [ ] `backend/app/utils/xlsx_summary.py` — функция `generate_summary_xlsx(summary)`:
  - Лист на каждый раздел (строки из `section.rows`, стиль как в `generate_estimate_xlsx`)
  - Лист «Сводная» — левая и правая таблицы как на скриншоте
- [ ] Эндпоинт `GET /projects/{id}/summary/export` возвращает xlsx
- [ ] Подключить роутер в `main.py`
- [ ] Gate: все тесты зелёные, эндпоинты отвечают корректно

### Фаза 3 — Фронтенд: стор, API-клиент, типы
**Статус:** [ ]

- [ ] `frontend/src/types/summary.ts` — типы `SectionTab`, `SummaryOverrides`, `SummaryEstimate`, `SummaryEstimateResponse`
- [ ] `frontend/src/api/summaryEstimate.ts` — функции `getSummary`, `createSummary`, `updateSummary`, `exportSummary`, `setPrimaryVersion`
- [ ] `frontend/src/stores/summaryEditorStore.ts`:
  - State: `sections`, `summaryOverrides`, `activeTabIndex`, `isDirty`, `summaryId`, `undoStack`, `redoStack`
  - Actions: `loadSummary`, `updateSectionRows`, `updateOverride`, `save`, `undo`, `redo`, `reset`
  - `undo`/`redo` по той же схеме что в `estimateEditor.ts` (undoStack/redoStack из EstimateRow[][])
  - Pure function `calcSummary(sections, overrides)` → все итоги для SummarySheet
- [ ] Gate: `npx tsc --noEmit` без ошибок

### Фаза 4 — Фронтенд: UI-компоненты и страница
**Статус:** [ ]

- [ ] UI выбора главной версии на `WorkflowCard`:
  - В списке версий карточки раздела добавить кнопку/иконку «Сделать главной» рядом с каждой версией
  - Вызывает `PATCH /workflow-cards/{card_id}/primary-version`
  - Выбранная версия помечается визуально (иконка звезды или метка «Главная»)
- [ ] `SectionSelector.tsx` — модальное окно:
  - Список WorkflowCard проекта у которых есть `estimate_task_id` или `optimization_task_id`
  - Для каждой карты: чекбокс + дропдаун версий EstimateVersion (не rolled_back)
  - Дефолт дропдауна: `primary_version_id` карты если задан, иначе автовыбор (optimized > estimated)
  - Кнопка «Создать сводную»
- [ ] `SummarySheet.tsx` — Сводный лист:
  - Левая таблица: строки 1-10 с редактируемыми ячейками (% или руб.), итоги readonly
  - Правая таблица: разбивка по разделам, итоги
  - Реактивный пересчёт через `calcSummary()` при каждом изменении
  - Ставки НДС: работы 22%, материалы 20% (как на скриншоте)
- [ ] `SummaryEditorTabs.tsx` — горизонтальные вкладки:
  - Вкладки разделов: рендерят `EstimateGrid` с `rows` из `summaryEditorStore.sections[i].rows`, передавать `onUndo`/`onRedo` из store
  - Вкладка «Сводная» — рендерит `SummarySheet`
  - Кнопки панели инструментов: Сохранить, Экспорт xlsx — кнопки «Отменить изменение» / «Вернуть изменение» рендерит сам `EstimateGrid` через props (как в `EstimateOptimizer.tsx`)
- [ ] `SummaryEditor.tsx` — страница:
  - Если summary нет: показывает кнопку «Создать сводную» → открывает `SectionSelector`
  - Если summary есть: показывает `SummaryEditorTabs`
  - Breadcrumb: Проект → Сводная себестоимость
- [ ] Маршрут `/projects/:projectId/summary` в `App.tsx`
- [ ] Кнопка «Сводная себестоимость» в `ProjectDetail.tsx` (на странице проекта, рядом с суммой или в шапке)
- [ ] Gate: `npx tsc --noEmit`, `npm run lint`, визуальная проверка в браузере (golden path)

### Фаза 5 — Интеграция project total + завершение
**Статус:** [ ]

- [ ] Добавить `summary_total: Decimal | None` в модель `Project` (миграция `016_add_summary_total_to_project.py`)
- [ ] В `summary_service.py`: при `POST`/`PUT` summary — обновлять `project.summary_total`
- [ ] В `routers/projects.py` `_aggregate()`: если `project.summary_total is not None` → возвращать его, иначе `SUM(Task.cost)` (обратная совместимость)
- [ ] В `ProjectCardResponse` / `ProjectDetail`: показывать индикатор «Сводная сформирована» рядом с суммой
- [ ] Gate: все тесты, `tsc --noEmit`, `lint` зелёные

---

## Важные детали реализации

### НДС на работы vs материалы
Скриншот показывает **разные ставки**: 22% на работы, 20% на материалы. Текущий `settings.VAT_RATE = 0.22` — это только для работ. В `SummaryOverrides` нужны два поля: `vat_works_pct` (default 22) и `vat_materials_pct` (default 20).

### Snapshot строк
Когда пользователь создаёт сводную — строки из `EstimateVersion.rows` **копируются** в `SummaryEstimate.sections[i].rows`. Изменения в сводном редакторе живут в `SummaryEstimate`, не затрагивают исходные `EstimateVersion`. Это защищает от случайного изменения рабочей сметы через сводную.

### Выбор версии по умолчанию в SectionSelector
Приоритет автовыбора: `optimization_task_id` > `estimate_task_id`. Внутри задачи: последняя не-rolled_back версия с `is_rolled_back = False`, сортировка по `created_at DESC`.

### Обратная совместимость project total
До тех пор пока сводная не создана — `project.summary_total is None` → `_aggregate()` возвращает `SUM(Task.cost)`. Существующие проекты работают без изменений.

### Блок overrides на SummarySheet
Поля с ручным вводом (Разнорабочие ежедневно, Банковская гарантия, Клининг, РД/ППР, Пусконаладочные) — абсолютные значения в рублях, хранятся в `overrides`. Поля с `%` (Транспорт 1%, Уборка 1.5%, Накладные 2%, Непредвиденные 2%, Прибыль 16%, НДС, Налоги 3%) — проценты от соответствующей базы.

### EstimateGrid в SummaryEditor
Передавать `rows` из `summaryEditorStore.sections[i].rows` как управляемое состояние. При `onRowsChange` → вызывать `summaryEditorStore.updateSectionRows(i, newRows)`, что пересчитывает `calcSummary()` автоматически. Не нужно менять сам `EstimateGrid`.

### Undo/Redo в SummaryEditor
Та же схема что в `estimateEditor.ts`: `undoStack: EstimateRow[][]` и `redoStack: EstimateRow[][]`. `MAX_HISTORY` — то же значение. Кнопки «Отменить изменение» / «Вернуть изменение» рендерит сам `EstimateGrid` через props `onUndo`/`onRedo` — менять `EstimateGrid` не нужно, только передать props из `SummaryEditorTabs`.

---

## Итог

| Фаза | Что даёт |
|------|---------|
| 1 — Миграции и модели | Фундамент: новые таблицы БД, поле выбора версии |
| 2 — API + Excel export | Бэкенд полностью готов, экспорт работает |
| 3 — Стор + API-клиент | Фронтенд-логика и типы готовы |
| 4 — UI-компоненты | Пользователь может работать со сводной |
| 5 — Project total | Сумма проекта берётся из сводной, всё интегрировано |

**Реализован целиком:** нет (план в работе)  
**Что осталось:** все 5 фаз
