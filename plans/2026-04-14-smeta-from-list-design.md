# Смета из перечня + вспомогательные улучшения

Дата: 2026-04-14  
Спецификация: `docs/superpowers/specs/2026-04-14-smeta-from-list-design.md`  
Статус: завершён

---

## Фазы

### Фаза 1 — Отображение исходного файла [x]

**Цель:** На странице `TaskStatus` показывать секцию «Исходный файл» со скачиванием.

- [x] Backend: добавить поле `input_files` (meta без content_b64) в `TaskStatusResponse` и `get_task_status`
- [x] Backend: endpoint `GET /tasks/{task_id}/input-file/{file_index}` — скачать исходный файл по индексу
- [x] Frontend `api/tasks.ts`: поле `input_files` в интерфейс `TaskStatusResponse`, функция `downloadInputFile`
- [x] Frontend `TaskStatus.tsx`: секция «Исходный файл» (иконка + имя + кнопка Скачать) — до блока «Результаты»

---

### Фаза 2 — Автоименование задач [x]

**Цель:** Поле «Название» автоматически заполняется из имени файла при создании задачи.

- [x] Frontend `TaskCreate.tsx`: при выборе файла заполнять поле name = `[метка типа]: [имя файла без расширения]`
- [x] Frontend `TaskCreate.tsx`: поле редактируемое и обязательное (валидация при сабмите)
- [x] Backend: добавлен параметр `name: Optional[str] = Form(None)` в `create_task`, сохраняется в `task.name`

---

### Фаза 3 — Новый тип задачи ESTIMATE_FROM_LIST [x]

**Цель:** Пользователь загружает Excel-перечень (или берёт из существующей задачи), получает смету с ценами.

Подфазы:

#### 3.1 — Константы и заглушка [x]
- [x] `constants.py`: добавить `ESTIMATE_FROM_LIST` в `TASK_TYPE_LABELS` и `ESTIMATE_TASK_TYPES`
- [x] `task_processor.py`: добавить ветку `ESTIMATE_FROM_LIST`
- [x] `frontend/src/types/index.ts`: добавить метку и в `ESTIMATE_TASK_TYPES`

#### 3.2 — Парсинг входного файла [x]
- [x] `xlsx_cost_parser.py`: функция `parse_list_sheet(bytes)` — парсинг листа «Перечень»
- [x] Обработка ошибок: лист не найден → понятное сообщение

#### 3.3 — Поиск цен по прайсу [x]
- [x] `task_processor.py`: шаг exact + embedding из `price_service` (без web search)
- [x] Результат: matched + unmatched

#### 3.4 — Claude для ненайденных позиций [x]
- [x] Промпт 1 (из спецификации): чанки по границам строк «Работа»
- [x] `_interruptible_claude_json` для поддержки кнопки «Стоп»

#### 3.5 — Сборка Excel и итогов [x]
- [x] `xlsx_exporter.py`: `generate_estimate_xlsx()` — колонки из спецификации
- [x] Вычисление накладных и транспортных расходов (3%)
- [x] Сохранение `task.cost` и `estimation_status = "estimated"`

#### 3.6 — Путь Б: из существующей задачи [x]
- [x] Backend: `GET /tasks/estimate-sources` — список завершённых LIST_FROM_GRAND / LIST_FROM_PROJECT со стадиями
- [x] Backend: `create_task` принимает `source_task_id` + `source_stage`; сохраняет Path B в `user_prompt` (JSON)
- [x] Backend: `_handle_estimate_from_list` — Path B: берёт items из `progress_data` источника (стадия 1) или связанной задачи проверки (стадия 2)
- [x] Frontend `api/tasks.ts`: `getEstimateSources`, типы `EstimateSource`, `EstimateSourceStage`
- [x] Frontend `TaskCreate.tsx`: переключатель «Загрузить файл / Из существующей задачи», выпадающий список источников, список стадий; автоимя из источника

#### 3.7 — Пересчёт сметы (редактирование + переопределение цены) [x]
- [x] Backend: `PATCH /tasks/{id}/estimate-items` — пересоздаёт Excel, обновляет cost и progress_data
- [x] Backend: `POST /tasks/{id}/estimate-items/{idx}/reprice` — промпт 2 к Claude, возвращает новые цены
- [x] Frontend `api/tasks.ts`: `patchEstimateItems`, `repriceEstimateItem`, типы `EstimateItem`, `RepriceItemResponse`
- [x] Frontend `TaskStatus.tsx`: таблица с редактируемыми ячейками (qty, work_price, material_price), автопересчёт стоимостей и итогов, кнопка «Сохранить изменения», кнопка «↺ Цена» для каждой строки

---

### Пост-релизные исправления и улучшения [x]

*(Сессия 2026-04-14, после первого деплоя)*

#### Исправления деплоя [x]
- [x] `xlsx_cost_parser.py`, `xlsx_exporter.py`, `constants.py`, `types/index.ts`, `Layout.tsx` — не были включены в первый коммит; деплой падал с `ImportError: cannot import name 'parse_list_sheet'` (commit `ebea608`)

#### Исправления видимости на фронте [x]
- [x] `TaskTypeSelector.tsx`: добавить `ESTIMATE_FROM_LIST` в захардкоженный массив `TASK_TYPES` — тип задачи не отображался в выпадающем списке (commit `71c59e0`)
- [x] `routers/tasks.py` → `get_task_status`: fallback `input_file_data → input_files` — у старых задач `input_file_data` пустой, исходный файл не показывался (commit `71c59e0`)

#### Имя файла-результата [x]
- [x] `task_processor.py`: хелпер `_result_filename(task, fallback)` — имя скачиваемого Excel-файла совпадает с названием задачи; sanitize спецсимволов, обрезка до 100 символов, fallback на прежнее имя при пустом `task.name`; применено ко всем финальным `save_result` (5 типов задач) (commit `1f1d999`)

#### Цветовая маркировка строк в Excel [x]
- [x] `excel_service.py`: функции `_row_fill(item)` и `_apply_row_fill()` — подсветка строк по статусу во всех листах `generate_list()` и `generate_list_project()`:
  - `#FFF2CC` — позиция добавлена (`notes` содержит «Добавлено»)
  - `#CFE2F3` — объём скорректирован (`notes` содержит «скорректирован»)
  - `#F4CCCC` — объём неизвестен (`quantity = null`) (commit `0ba2ad2`)

#### Скрытие подзадач из сайдбара [x]
- [x] `ProjectsSidebar.tsx`: `CHECK_LIST_COMPLETENESS` и `CHECK_PROJECT_COMPLETENESS` скрыты из дерева задач — отображаются только внутри родительской задачи (commit `0ba2ad2`)

#### Поллинг в фоновой вкладке [x]
- [x] `TaskStatus.tsx`: `visibilitychange` listener — при возврате на вкладку немедленно вызывает `fetchStatus` (браузер throttlит `setInterval` фоновых вкладок до ~1 раза в минуту, прогресс-сообщения зависали); refs на текущие fetch-функции исключают stale-closure (commit `f21b644`)

---

## Итог

| Фаза | Статус |
|---|---|
| 1 — Отображение исходного файла | [x] |
| 2 — Автоименование задач | [x] |
| 3.1-3.5 — ESTIMATE_FROM_LIST (ядро) | [x] |
| 3.6 — Путь Б (из существующей задачи) | [x] |
| 3.7 — Пересчёт сметы (редактирование) | [x] |
| Пост-релизные исправления и улучшения | [x] |
