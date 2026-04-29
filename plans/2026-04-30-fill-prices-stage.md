# Стадия «Проставить цены» в Оптимизации Смет

## Задача
Добавить шаг 5 «Проставить цены» в модуль оптимизации сметы (EstimateOptimizer).
После стадии «Оптимизация материалов» берутся позиции без цены → сначала ищутся в прайсе,
затем (ненайденные) — через Claude + веб-поиск (≥3 источника, средняя), с комментариями об источнике.

## Фазы

### [x] Фаза 1. Backend — новый шаг fill_prices
- `VALID_LABELS` в estimate_versions.py: добавить `"prices_filled"`
- Константа `PROMPT_FILL_PRICES` (аналог PROMPT_ESTIMATE_FROM_LIST)
- Функция `_run_fill_prices_step(task_id)`:
  - берёт последнюю не-откатанную версию
  - ищет строки без цены (price_work=0/None для work, price_material=0/None для material)
  - если таких нет → создаёт версию prices_filled с флагом all_priced=True
  - иначе: прайс-лист (exact+embedding), затем Claude+web для оставшихся
  - создаёт новую EstimateVersion(version_label="prices_filled")
  - кладёт proposals с info по каждой проставленной цене
- Маршрут `POST /tasks/{task_id}/estimate/optimize/fill-prices`

### [x] Фаза 2. Frontend — новая кнопка в OptimizationToolbar
- `OptimizationStep` в types/index.ts: добавить `'fill_prices'`
- STEPS в OptimizationToolbar.tsx: добавить шаг с requiredLabel='material_optimized', producedLabel='prices_filled'

### [x] Фаза 3. Frontend — EstimateOptimizer
- Баннер: для step==='fill_prices' показывать свои тексты
- handleViewStep: не открывать панель proposals для fill_prices

## Комментарии в Excel
- Из прайса: `optimization_note = "Из прайса: {price_list_name}"`
- Из интернета: `optimization_note = "Из интернета: Источник1: цена1; Источник2: цена2; ..."`

## Итог
[x] Реализован целиком. TypeScript — 0 ошибок, ruff — 0 замечаний.
