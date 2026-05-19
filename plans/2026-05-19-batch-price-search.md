# Батчевый поиск по прайсу

## Проблема

В цикле поиска цен (task_processor.py ~1580-1624) каждая позиция, не нашедшаяся по точному совпадению, делает отдельный HTTP-запрос к Cohere API для генерации embedding. 50 позиций = 50 последовательных запросов.

## Цель

Сократить количество запросов к Cohere с N до 2 (один батч для работ, один для материалов), используя уже существующий `generate_embeddings_batch`.

## Scope

- `backend/app/services/price_service.py` — добавить `batch_embedding_match_works` и `batch_embedding_match_materials`
- `backend/app/services/task_processor.py` — рефакторинг цикла поиска цен (строки ~1580-1624)

## Non-Goals

- Не трогаем Claude-шаг (Step 2, ненайденные позиции)
- Не меняем модели, схемы БД, миграции
- Не меняем логику web-search

## Acceptance Criteria

1. Все exact-матчи отрабатывают за 1 синхронный проход (без изменений поведения)
2. Все embedding-матчи для работ — 1 вызов Cohere вместо N
3. Все embedding-матчи для материалов — 1 вызов Cohere вместо N
4. Результат (`matched_by_gidx`, `unmatched_by_gidx`) идентичен предыдущей логике
5. numpy недоступен / embeddings не загружены → graceful fallback (все в unmatched)
6. Исключение в batch-запросе → все затронутые позиции уходят в unmatched (не крашим задачу)

## Фазы

### Фаза 1: price_service.py — batch функции [ ]

Добавить две модульные функции:

```
async def batch_embedding_match_works(names: list[str]) -> list[Optional[dict]]
async def batch_embedding_match_materials(names: list[str]) -> list[Optional[float]]
```

Алгоритм (на примере works):
1. Если `names` пустой или numpy/embeddings недоступны → вернуть `[None] * len(names)`
2. Нормализовать все имена через `normalize_name`
3. Одним `asyncio.to_thread(generate_embeddings_batch, normalized, "search_query")` получить матрицу запросов (M×1024)
4. `scores = dot(_works_embeddings, query_arr.T) / (works_row_norms[:, None] * query_norms[None, :])` → форма (N×M)
5. `best_indices = argmax(scores, axis=0)` → (M,)
6. Для каждого: если score >= SIMILARITY_THRESHOLD → вернуть `_works_cache[_works_index_map[best_idx]]`, иначе None
7. При нулевой норме запроса → None

### Фаза 2: task_processor.py — рефакторинг цикла [ ]

Было: 1 проход, awaits внутри цикла.

Стало: 3 прохода:

**Проход 1** (sync): для всех items → exact match. Результат: matched, need_emb_works, need_emb_materials, unmatched_others.

**Проход 2** (1 await): batch_embedding_match_works для need_emb_works → дополняем matched / unmatched.

**Проход 3** (1 await): batch_embedding_match_materials для need_emb_materials → дополняем matched / unmatched.

Items с типом не "Работа" и не "Материал" → сразу в unmatched (как и раньше).

### Фаза 3: Gates [ ]

- `python -m py_compile backend/app/services/price_service.py`
- `python -m py_compile backend/app/services/task_processor.py`
- `cd backend && ruff check app/services/price_service.py app/services/task_processor.py`

## Итог

- [ ] Реализован целиком
- [ ] Что осталось: —
