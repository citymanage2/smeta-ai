# Авто-применение предложений оптимизации

**Дата:** 2026-04-24
**Статус:** [x] Реализован

## Задача

Убрать ручное принятие/отклонение каждой позиции при оптимизации.
Вместо этого все три уровня предложений (высокий, средний, низкий) автоматически применяются в смете, визуально выделяются по уровню. Сметчик редактирует смету вручную в онлайн-редакторе, удаляя не нужные строки.

## Фазы

### Фаза 1 — Бэкенд: поле `optimization_confidence` [x]

- Добавлен `optimization_confidence: Optional[Literal["high", "medium", "low"]]` в `EstimateRowSchema`
- Файл: `backend/app/schemas/estimate_version.py`

### Фаза 2 — Бэкенд: авто-применение proposals [x]

- Добавлена функция `_auto_apply_proposals(source_rows, proposals)` в `estimate_versions.py`
  - `add` → создаёт новую строку с `optimization_confidence`
  - `replace_tech/replace_material` → обновляет поля строки + ставит `optimization_confidence`
  - `remove` → удаляет строку из списка
- В `_run_optimization_step` после парсинга proposals вызывается `_auto_apply_proposals`
- Новая версия создаётся с уже применёнными строками (не оригинальными)
- Proposals сохраняются в `optimization_proposals` для истории
- RESPONSE_FORMAT обновлён: `new_value` теперь включает `type, unit, qty` для корректного создания строк

### Фаза 3 — Фронтенд: тип + визуальная подсветка [x]

- Добавлен `optimization_confidence?: 'high' | 'medium' | 'low'` в `EstimateRow` (`types/index.ts`)
- В `EstimateGrid`:
  - Компонент `ConfidenceBadgeCell` — бейдж с текстом уровня
  - Колонка `CONFIDENCE_COL` ("Уровень") добавлена во все три набора колонок
  - `rowClass` возвращает `row-proposal-{high|medium|low}` для подсвеченных строк
- В `EstimateGrid.css`:
  - `.row-proposal-high` → зелёная левая граница + зелёный фон
  - `.row-proposal-medium` → жёлтая левая граница + жёлтый фон
  - `.row-proposal-low` → оранжевая левая граница + оранжевый фон
  - `.confidence-badge-{high|medium|low}` — бейджи в ячейке колонки

### Фаза 4 — Фронтенд: сводная панель [x]

- `OptimizationProposalsPanel` получил проп `autoApplied?: boolean`
- При `autoApplied=true`:
  - Показывает заголовок "изменения применены автоматически"
  - Статистика: + добавлено / − удалено / ⇄ заменено
  - Легенда цветов
  - Список изменений (readonly, без кнопок)
  - Только кнопка "Закрыть"
- При `autoApplied=false` (кастомная оптимизация): прежний режим accept/reject
- `EstimateOptimizer`: `handleStepComplete` и `handleViewStep` передают `autoApplied: true`

## Итог

Реализован целиком. Ручное принятие позиций устранено для шагов 1–4. Кастомная оптимизация (выбор строк вручную) сохраняет прежний режим accept/reject.
