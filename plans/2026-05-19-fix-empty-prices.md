# Fix Empty Prices — Исправление пустых цен в ESTIMATE_FROM_LIST

## Проблема

При создании смет на больших перечнях Claude иногда возвращал позиции с `work_price: null` или `material_price: null`.
Существующий ретрай ловил только позиции, **полностью отсутствующие** в ответе (по ID), но не позиции с **null ценой**.

## Решение (Вариант 3: промпт + автоматический ретрай + ручная кнопка)

### Фазы

- [x] **Фаза 1.1** — Усилить `PROMPT_ESTIMATE_FROM_LIST`
  - Добавлен блок «АБСОЛЮТНЫЙ ЗАПРЕТ на null-цены»
  - Явно запрещены null и 0 для work_price/material_price

- [x] **Фаза 1.2** — Автоматический ретрай null-цен в `_handle_estimate_from_list`
  - После существующего ретрая missing_ids добавлен проход по `claude_results`
  - Позиции с null/zero ценой отправляются повторно батчами по 5

- [x] **Фаза 2** — Метод `fix_empty_prices` в `TaskProcessor`
  - Читает `progress_data.items`, находит пустые цены
  - Отправляет в Claude батчами по 5 с тем же промптом + web_search
  - Обновляет items, пересоздаёт xlsx, обновляет cost

- [x] **Фаза 3** — Эндпоинт `POST /tasks/{task_id}/estimate-items/fix-empty-prices`
  - Запускает `fix_empty_prices_background` через FastAPI BackgroundTasks
  - Возвращает 202 немедленно; задача переходит в status=processing
  - Защита: 409 если уже processing или не ESTIMATE_FROM_LIST

- [x] **Фаза 4** — Фронтенд
  - API: `fixEmptyPrices()` в `frontend/src/api/tasks.ts`
  - State: `fixingPrices`, `needsItemReload` в `TaskStatus.tsx`
  - Кнопка «🔧 Исправить пустые цены (N)» — показывается только когда N > 0
  - После клика: task переходит в processing → существующий polling обнаруживает → items перезагружаются

## Файлы

| Файл | Изменения |
|---|---|
| `backend/app/services/task_processor.py` | Промпт, null-price retry, метод fix_empty_prices, fix_empty_prices_background |
| `backend/app/routers/tasks.py` | Эндпоинт fix-empty-prices |
| `frontend/src/api/tasks.ts` | fixEmptyPrices() |
| `frontend/src/pages/TaskStatus.tsx` | Кнопка, state, useEffect reload |

## Статус

Реализован целиком — 2026-05-19.
