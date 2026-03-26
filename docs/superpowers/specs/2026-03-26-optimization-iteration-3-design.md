# Итерация 3 — Модуль оптимизации смет и подбор аналогов

**Дата:** 2026-03-26
**Стек:** FastAPI + openpyxl + Claude web-search / React + TypeScript

---

## Контекст

Итерации 1–2 добавили сущность Project с задачами, файловыми слотами (source/estimate/optimized) и экспорт в xlsx/PDF. Итерация 3 добавляет автоматическую оптимизацию сметы: система читает xlsx из слота `estimate`, ищет более дешёвые аналоги через прайс-лист и Claude web-search, генерирует оптимизированный xlsx и сохраняет в слот `optimized`.

---

## Архитектура

### Подход: два специализированных endpoint-а

- `POST /tasks/{task_id}/optimize/analyze` — синхронный, возвращает top-70% позиций для редактирования пользователем
- `POST /tasks/{task_id}/optimize/run` — запускает фоновую обработку, прогресс через `task.progress_message`

Новый тип задачи `OPTIMIZE_SMETA` в TaskCreate использует ту же логику `run` без шага `analyze` (с настройками по умолчанию: все категории, top-70%).

---

## Backend

### Новые endpoint-ы

#### `POST /tasks/{task_id}/optimize/analyze`

**Auth:** `get_current_user`

**Body:**
```json
{
  "categories": ["work", "material", "extra", "other"],
  "other_description": "произвольный текст (если выбрано other)"
}
```

**Поведение:**
1. Ищет `TaskResult` по `task_id` и `slot="estimate"` — 404 если не найден
2. Парсит xlsx через `xlsx_optimizer.parse_estimate_xlsx(file_bytes)`
3. Фильтрует по `categories`
4. Вызывает `xlsx_optimizer.get_top_items(items, categories, threshold=0.7)`
5. Возвращает JSON

**Ответ:**
```json
{
  "items": [
    {
      "row_index": 5,
      "name": "Кирпич керамический М150",
      "type": "material",
      "quantity": 10000,
      "unit": "шт",
      "price_excl_vat": 12.50,
      "price_incl_vat": 15.25,
      "total": 152500.00,
      "selected": true
    }
  ],
  "total_analyzed": 45,
  "total_selected": 12,
  "coverage_pct": 71.3
}
```

**Ошибки:** 400 если xlsx не парсится, 404 если слот пуст

---

#### `POST /tasks/{task_id}/optimize/run`

**Auth:** `get_current_user`

**Body:**
```json
{
  "items": [
    {
      "row_index": 5,
      "name": "Кирпич керамический М150",
      "type": "material",
      "quantity": 10000,
      "unit": "шт",
      "price_excl_vat": 12.50,
      "price_incl_vat": 15.25,
      "total": 152500.00
    }
  ],
  "prompt": "Ищи аналоги в Екатеринбурге, предпочитай отечественных производителей",
  "categories": ["work", "material"]
}
```

**Поведение:**
1. Проверяет что задача существует — 404 если нет
2. Ищет `TaskResult` слота `estimate` — 404 если нет
3. Устанавливает `task.status = "processing"`, `task.estimation_status = "processing_optimization"`, `task.progress_message = "Начинаем оптимизацию..."`
4. Запускает фоновую задачу `_run_optimization_background(task_id, items, prompt)`
5. Возвращает `{"task_id": task_id, "status": "optimization_started"}`

**Фоновая функция `_run_optimization_background`:**
- Для каждой позиции из `items`:
  1. Поиск в прайс-листе: `price_service.find_work_price(name)` или `find_material_price(name)`
  2. Если не найдено или цена выше сметной — Claude web-search (до 3 итераций, берём минимальную)
  3. Сравнение: цена с НДС сравнивается с `price_incl_vat`, без НДС — с `price_excl_vat`
  4. Пишет прогресс: `task.progress_message = f"Обработано {i}/{total}: {name[:40]}"`
- Вызывает `generate_optimized_xlsx(original_bytes, optimization_results)`
- Сохраняет результат в новый `TaskResult` с `slot="optimized"`
- Обновляет `task.status = "completed"`, `task.estimation_status = "optimized"`, `task.progress_message = None`
- При ошибке: `task.status = "failed"`, `task.error_message = str(e)`

**Немедленный ответ:** `{"task_id": task_id, "status": "optimization_started"}`

---

### Новый тип задачи `OPTIMIZE_SMETA`

В `backend/app/constants.py`:

```python
TASK_TYPE_LABELS["OPTIMIZE_SMETA"] = "Оптимизация сметы"
ESTIMATE_TASK_TYPES.add("OPTIMIZE_SMETA")
```

В `task_processor.py` — обработчик для `OPTIMIZE_SMETA`:
- Читает загруженный xlsx из `input_file_data[0]`
- Парсит все позиции (без analyze-шага), все категории, top-70%
- Запускает ту же логику оптимизации, результат пишет в `TaskResult` слот `optimized`
- Итоговый статус: `estimation_status = "optimized"`

---

## Утилиты

### `backend/app/utils/xlsx_optimizer.py`

```python
def parse_estimate_xlsx(file_bytes: bytes) -> list[dict]:
    """
    Парсит xlsx сметы. Ищет строку-заголовок в первых 10 строках
    по ключевым словам: 'наименование', 'цена', 'стоимость'.
    Возвращает список позиций:
    {row_index, name, type, quantity, unit, price_excl_vat, price_incl_vat, total}
    Строки без наименования пропускаются.
    """

def get_top_items(items: list[dict], categories: list[str], threshold: float = 0.7) -> list[dict]:
    """
    Фильтрует по категориям, сортирует по total убывающе,
    берёт позиции пока накопленная сумма < threshold * итог.
    Все позиции помечаются selected=True.
    """

def generate_optimized_xlsx(original_bytes: bytes, optimization_results: list[dict]) -> bytes:
    """
    Открывает оригинальный xlsx, добавляет 4 колонки к первому листу:
    'Цена сниженная', 'Стоимость сниженная', 'Источник', 'Примечание'.
    Заливка: зелёная (#E2EFDA) для найденных аналогов,
             жёлтая (#FFEB9C) для 'Не найдено'.
    Пересчитывает итоговые строки.
    Добавляет лист 2 'Сравнение': таблица было/стало,
    экономия по строке и итоговая экономия в ₽ и %.
    Возвращает bytes.
    """
```

`optimization_results` — список по одному элементу на каждую входную позицию:
```python
{
    "row_index": int,
    "name": str,
    "original_price": float,        # цена из сметы (та, с которой сравнивали)
    "new_price": float | None,      # найденная цена (None = не найдено)
    "source": str,                  # URL или название поставщика / "Не найдено"
    "savings_abs": float | None,    # экономия на единицу
    "savings_pct": float | None,    # процент экономии
    "has_vat": bool,                # True = цена с НДС, False = без НДС
}
```

---

## Статус задачи

Новое переходное значение `estimation_status`:

| Значение | Описание |
|---|---|
| `unestimated` | Смета не рассчитана |
| `estimated` | Смета рассчитана, готова к оптимизации |
| `processing_optimization` | Идёт поиск аналогов |
| `optimized` | Оптимизация завершена |
| `not_applicable` | Тип задачи не предполагает сметы |

В `ESTIMATION_STATUS_LABELS`:
```python
"processing_optimization": "Оптимизируется",
```

---

## Frontend

### Изменения файлов

| Файл | Действие |
|---|---|
| `frontend/src/api/tasks.ts` | Добавить `analyzeOptimize()`, `runOptimize()` |
| `frontend/src/components/OptimizeModal.tsx` | Новый компонент — 4-шаговый wizard |
| `frontend/src/pages/ProjectDetail.tsx` | Кнопка «Оптимизировать» + `<OptimizeModal>` |
| `frontend/src/types.ts` | Добавить `OPTIMIZE_SMETA` в `TaskType`, `"processing_optimization"` в `EstimationStatus` |
| `frontend/src/components/TaskTypeSelector.tsx` | Добавить `OPTIMIZE_SMETA` с подсказкой |

---

### `frontend/src/api/tasks.ts`

```typescript
export async function analyzeOptimize(
  taskId: string,
  categories: string[],
  otherDescription?: string
): Promise<AnalyzeOptimizeResponse> {
  const res = await apiClient.post(`/tasks/${taskId}/optimize/analyze`, {
    categories,
    other_description: otherDescription ?? null,
  });
  return res.data;
}

export async function runOptimize(
  taskId: string,
  items: OptimizeItem[],
  prompt: string,
  categories: string[]
): Promise<{ task_id: string; status: string }> {
  const res = await apiClient.post(`/tasks/${taskId}/optimize/run`, {
    items,
    prompt,
    categories,
  });
  return res.data;
}
```

---

### `OptimizeModal.tsx` — структура wizard

**Шаг 1 — Категории**
```
Чекбоксы:
  [x] Работы
  [x] Материалы
  [ ] Дополнительные расходы
  [ ] Другое → [текстовое поле]
[Анализировать]
```

**Шаг 2 — Предварительный анализ**
- Вызов `analyzeOptimize()` → спиннер → таблица
- Таблица: Наименование | Тип | Цена без НДС | Цена с НДС | Стоимость | [☑]
- Все строки по умолчанию включены
- Кнопка «+ Добавить позицию» — поиск по полному списку позиций сметы
- Редактируемое поле prompt (предзаполнено системным текстом)
- `[Запустить поиск цен]`

**Шаг 3 — Прогресс**
- Вызов `runOptimize()` → polling `getTaskStatus()` каждые 2 сек
- Показывает `task.progress_message`
- Progress bar (анимированный, не детерминированный)
- Нет кнопки отмены

**Шаг 4 — Результат**
```
Найдено аналогов: 8 из 12
Итоговая экономия: 127 450 ₽ (14%)

[таблица: было → стало, источник]

[Скачать xlsx]  [Закрыть]
```
- «Скачать xlsx» → `GET /tasks/{id}/files/optimized/download`
- «Закрыть» → callback для обновления списка задач в ProjectDetail (задача теперь `optimized`)

---

### `ProjectDetail.tsx` — кнопка

В строке каждой задачи добавляется кнопка:
```tsx
{task.estimation_status === 'estimated' && (
  <button onClick={() => setOptimizingTaskId(task.id)}>
    ⚡ Оптимизировать
  </button>
)}
```

Состояние modal:
```tsx
const [optimizingTaskId, setOptimizingTaskId] = useState<string | null>(null);

{optimizingTaskId && (
  <OptimizeModal
    taskId={optimizingTaskId}
    onClose={() => {
      setOptimizingTaskId(null);
      fetchProject(); // обновить список задач
    }}
  />
)}
```

---

## Обработка ошибок

| Ситуация | Поведение |
|---|---|
| Слот `estimate` пуст | 404 из `/analyze` |
| xlsx не парсится (повреждён) | 400 с сообщением |
| Задача не найдена | 404 |
| Ошибка web-search для позиции | позиция помечается «Не найдено», обработка продолжается |
| Фатальная ошибка фона | `task.status = "failed"`, modal показывает ошибку |
| Таймаут polling (> 5 мин) | modal показывает «Превышено время ожидания» |

---

## Тесты

`backend/tests/test_xlsx_optimizer.py`:
1. `test_parse_estimate_xlsx_returns_items` — парсинг xlsx с известной структурой → список позиций
2. `test_parse_estimate_xlsx_skips_empty_rows` — строки без наименования пропускаются
3. `test_get_top_items_covers_threshold` — top-70% накопленная сумма >= 70%
4. `test_get_top_items_filters_categories` — фильтрация по категориям работает
5. `test_generate_optimized_xlsx_adds_columns` — результирующий xlsx содержит новые колонки
6. `test_generate_optimized_xlsx_has_comparison_sheet` — лист «Сравнение» присутствует
7. `test_generate_optimized_xlsx_green_fill_for_found` — зелёная заливка для найденных
8. `test_generate_optimized_xlsx_yellow_fill_for_not_found` — жёлтая заливка для не найденных

`backend/tests/test_optimize_endpoint.py`:
1. `test_analyze_returns_items` — POST analyze → 200, список позиций
2. `test_analyze_empty_slot_returns_404` — без estimate-файла → 404
3. `test_run_starts_background` — POST run → 200, status = optimization_started
4. `test_run_task_not_found` — несуществующая задача → 404

---

## Не входит в Итерацию 3

- Пакетная оптимизация всех задач проекта сразу
- Сохранение истории оптимизаций (несколько версий)
- Сравнение нескольких версий сметы (Итерация 4)
- Интеграция с внешними API прайсов (Леруа Мерлен и пр.)
