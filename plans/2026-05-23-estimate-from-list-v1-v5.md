# Версии V1–V5 для задачи «Смета из перечня»

**Дата:** 2026-05-23  
**Статус:** Завершён

## Цель

Подключить оптимизационный тулбар V1–V5 к задаче `ESTIMATE_FROM_LIST`.  
Ранее шаги оптимизации были доступны только в `ESTIMATE_OPTIMIZATION`.

## Версии

| Версия | Шаг | Что делает |
|---|---|---|
| V1 — Полнота | `completeness` | Проверка полноты по ГЭСН: все ли нормативные материалы учтены |
| V2 — Лишнее | `redundancy` | Поиск дублей и позиций, которые можно убрать |
| V3 — Технологии | `technology` | Замена технологий на более дешёвые (ABC-анализ) |
| V4 — Материалы | `materials` | Замена материалов на аналоги дешевле (ABC-анализ) |
| V5 — Цены | `fill_prices` | Заполнение пустых цен через прайс → кеш → веб-поиск |

## Что изменено

### Фаза 1 — Frontend [x]

- [x] `frontend/src/types/index.ts` — убрать `ESTIMATE_FROM_LIST` из `GENERIC_EDITOR_TASK_TYPES`  
  Теперь задача открывается в estimate-режиме с `EstimateGrid` + `OptimizationToolbar`

- [x] `frontend/src/components/estimate/OptimizationToolbar.tsx` — метки кнопок обновлены на V1–V5:
  - `V1 — Полнота`
  - `V2 — Лишнее`
  - `V3 — Технологии`
  - `V4 — Материалы`
  - `V5 — Цены`

- [x] `frontend/src/pages/EstimateOptimizer.tsx`:
  - Добавлен импорт `initEstimateVersionFromResult`
  - В estimate-режиме при пустом списке версий для `ESTIMATE_FROM_LIST` автоматически вызывается `init-from-estimate-result`, затем повторная загрузка версий

- [x] `frontend/src/pages/TaskStatus.tsx`:
  - При завершении `ESTIMATE_FROM_LIST` редирект на `/tasks/:id/estimate` (аналогично `ESTIMATE_OPTIMIZATION`)

### Фаза 2 — Backend [—]

Изменений не требуется:
- Эндпоинты оптимизации (`/estimate/optimize/*`) не проверяют `task_type` — работают с любой задачей
- `init-from-estimate-result` уже создаёт структурированную `EstimateVersion` из результата `ESTIMATE_FROM_LIST`
- Все version_label и display_name (`V1 - Полнота`, …, `V5 - Цены`) уже заданы корректно
- `prices_filled` уже в `VALID_LABELS`

## Итог

| Фаза | Статус |
|---|---|
| Frontend (4 изменения в 4 файлах) | [x] |
| Backend | не требовался |
