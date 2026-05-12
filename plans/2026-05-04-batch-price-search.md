# Батч-поиск по прайсу

Оптимизация поиска цен при составлении сметы: замена последовательных per-item вызовов Cohere на батчевые операции с дедупликацией и векторизованным cosine-поиском.

## Проблема

При обработке сметы каждая позиция, не прошедшая exact-match, вызывает отдельный HTTP-запрос к Cohere API (`generate_embedding`). Запросы идут последовательно.

- 200 позиций → ~40 сек только на эмбеддинги
- 1000 позиций → ~3–4 мин
- Дополнительно: повторяющиеся позиции (30–60% в типичной смете) эмбеддируются столько раз, сколько встречаются

## Решение

Три изменения в порядке приоритета:

1. **Дедупликация** — уникальные имена перед embedding-поиском
2. **Batch embeddings** — один вызов `generate_embeddings_batch` для всех уникальных промахов
3. **Vectorized cosine** — `query_matrix @ price_matrix.T` для всех запросов разом
4. **Снижение порога** — с 0.93 до 0.88 (уменьшить лишние fallback на Claude)

## Ожидаемый результат

| Сценарий | До | После |
|---|---|---|
| 100 позиций, 60% exact hits | ~8–12 сек | ~1–2 сек |
| 500 позиций, 40% exact hits | ~40–60 сек | ~3–5 сек |
| 1000 позиций, 30% exact hits | ~2–3 мин | ~5–10 сек |

---

## Фазы реализации

### [ ] Фаза 1 — Снизить порог совпадения

**Файл:** `backend/app/services/price_service.py`, строка 23

```python
# было
SIMILARITY_THRESHOLD = 0.93
# стало
SIMILARITY_THRESHOLD = 0.88
```

Дополнительно: добавить логирование пограничных случаев (0.85–0.93) для наблюдения.

---

### [ ] Фаза 2 — Добавить batch_match_from_pricelist в price_service.py

**Файл:** `backend/app/services/price_service.py`

Добавить новую функцию `batch_match_from_pricelist` после существующих `_embedding_match_*` функций:

```python
async def batch_match_from_pricelist(
    items: list[dict],
) -> dict[int, Any]:
    """
    Batch-поиск по прайсу с дедупликацией и vectorized cosine.

    items: [{"idx": int, "name": str, "type": "work"|"material"}]
    Returns: {idx: matched_result}

    Порядок операций:
    1. Exact match для всех
    2. Дедупликация уникальных имён
    3. Один вызов generate_embeddings_batch для уникальных
    4. Vectorized cosine: query_matrix @ price_matrix.T
    """
    from app.services.embedding_service import normalize_name, generate_embeddings_batch
    from typing import Any

    results: dict[int, Any] = {}
    need_embedding: list[tuple[int, str, str]] = []

    # Проход 1: exact match для всех позиций
    for item in items:
        idx, name, itype = item["idx"], item["name"], item["type"]
        if itype == "work":
            hit = _exact_match_work(name)
        else:
            hit = _exact_match_material(name)
        if hit is not None:
            results[idx] = hit
        else:
            need_embedding.append((idx, name, itype))

    if not need_embedding or not _numpy_available:
        return results

    work_items = [(idx, name) for idx, name, t in need_embedding if t == "work"]
    mat_items  = [(idx, name) for idx, name, t in need_embedding if t == "material"]

    async def _batch_embed_and_match(
        idx_name_pairs: list[tuple[int, str]],
        embeddings_matrix,
        row_norms,
        index_map: list[int],
        cache: list[dict],
    ) -> dict[int, Any]:
        if not idx_name_pairs or embeddings_matrix is None or row_norms is None:
            return {}

        # Дедупликация: уникальные имена с сохранением порядка
        unique_names = list(dict.fromkeys(n for _, n in idx_name_pairs))
        normalized   = [normalize_name(n) for n in unique_names]

        try:
            vecs = await asyncio.to_thread(
                generate_embeddings_batch, normalized, "search_query"
            )
        except Exception as e:
            logger.error("Batch embedding failed", error=str(e))
            return {}

        query_matrix = np.array(vecs, dtype=np.float32)      # Q×1024
        query_norms  = np.linalg.norm(query_matrix, axis=1)  # Q

        # Vectorized cosine: Q×P за один вызов BLAS
        scores_matrix = (query_matrix @ embeddings_matrix.T) / (
            query_norms[:, None] * row_norms[None, :]
        )
        best_idxs   = np.argmax(scores_matrix, axis=1)
        best_scores = scores_matrix[np.arange(len(unique_names)), best_idxs]

        # Логируем пограничные случаи для мониторинга порога
        for i, uname in enumerate(unique_names):
            sc = float(best_scores[i])
            if 0.85 <= sc < SIMILARITY_THRESHOLD:
                logger.debug(
                    "Embedding near-miss (below threshold)",
                    query=uname,
                    score=sc,
                    threshold=SIMILARITY_THRESHOLD,
                )

        # Строим маппинг имя → результат
        name_to_result: dict[str, Any] = {}
        for i, uname in enumerate(unique_names):
            if float(best_scores[i]) >= SIMILARITY_THRESHOLD:
                cache_idx = index_map[int(best_idxs[i])]
                name_to_result[uname] = cache[cache_idx]

        # Разворачиваем на все idx (включая дубли одного имени)
        out: dict[int, Any] = {}
        for orig_idx, orig_name in idx_name_pairs:
            if orig_name in name_to_result:
                out[orig_idx] = name_to_result[orig_name]
        return out

    # Проход 2: batch embed параллельно для works и materials
    work_hits, mat_hits = await asyncio.gather(
        _batch_embed_and_match(
            work_items, _works_embeddings, _works_row_norms,
            _works_index_map, _works_cache,
        ),
        _batch_embed_and_match(
            mat_items, _materials_embeddings, _materials_row_norms,
            _materials_index_map, _materials_cache,
        ),
    )
    results.update(work_hits)
    results.update(mat_hits)
    return results
```

---

### [ ] Фаза 3 — Обновить task_processor.py

**Файл:** `backend/app/services/task_processor.py`

В функции `_process_estimate_from_list` (около строки 1276) заменить цикл per-item поиска по прайсу на вызов `batch_match_from_pricelist`.

**До:**
```python
for gidx, item in enumerate(items):
    name = item.get("name", "")
    itype = item.get("type", "")
    if itype == "work":
        hit = await find_work_price(name)
    else:
        hit = await find_material_price(name)
    if hit:
        matched_by_gidx[gidx] = hit
    else:
        unmatched_by_gidx[gidx] = item
```

**После:**
```python
from app.services.price_service import batch_match_from_pricelist

batch_items = [
    {"idx": gidx, "name": item.get("name", ""), "type": item.get("type", "")}
    for gidx, item in enumerate(items)
]
pricelist_hits = await batch_match_from_pricelist(batch_items)

for gidx, item in enumerate(items):
    if gidx in pricelist_hits:
        matched_by_gidx[gidx] = pricelist_hits[gidx]
    else:
        unmatched_by_gidx[gidx] = item
```

---

### [ ] Фаза 4 — Обновить fill_prices в estimate_versions.py

**Файл:** `backend/app/routers/estimate_versions.py`, функция `fill_prices` (~строка 771)

Аналогичная замена per-item цикла на `batch_match_from_pricelist` для шага «Заполнить цены из прайса».

---

### [ ] Фаза 5 — Тесты

- Тест дедупликации: список с повторяющимися именами → Cohere вызывается один раз
- Тест batch vs sequential: результаты идентичны
- Тест порога 0.88: проверить на реальных примерах строительной терминологии
- Тест с пустым прайсом (edge case): функция возвращает пустой dict без ошибок
- Тест с OOM-safe: 1000 запросов × 5000 прайс = 20MB scores matrix, память в норме

---

## Итог

- [ ] Реализован целиком
- [ ] Частично (какие фазы остались: )

## Исследование (проведено 2026-05-04)

- Диагноз подтверждён двумя агентами: research + critic
- Конкуренты (Гранд-Смета, RSMeans, ProEst) работают по нормативным кодам, не используют vector search — smeta-ai технически опережает их
- pgvector HNSW и BM25 нецелесообразны при каталоге < 50K позиций
- Критик добавил: дедупликация важнее batch (срабатывает даже без изменения архитектуры)
- Критик исправил: Claude web search уже батчится по 25 позиций — параллелизировать менее приоритетно
