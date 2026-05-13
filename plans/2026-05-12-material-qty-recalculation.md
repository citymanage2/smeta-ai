# Автопересчёт объёмов материалов при изменении объёма работ

**Дата:** 2026-05-12  
**Обновлено:** 2026-05-13 (финализирован)  
**Статус:** Готов к исполнению

## Описание

При ручном изменении объёма работы в онлайн-редакторе сметы — автоматически пересчитываются объёмы всех связанных материалов в соответствии с нормативами **ГЭСН** (Государственные Элементные Сметные Нормы).

Нормативы берутся из ГЭСН-2017/ФСНБ-2022 через Claude API (по аналогии с задачей «Проверка полноты по ГЭСН») — никакой локальной базы нет, Claude сам знает нормы. Пересчёт срабатывает для всех связанных материалов — в том числе тех, чей объём был ранее задан вручную.

## Acceptance Criteria

1. При изменении `qty` работы → все связанные материалы пересчитываются по формуле `work.qty × qty_per_work_unit`
2. Пересчёт происходит **в том числе** для материалов с `qty_overridden = true` — флаг не блокирует пересчёт
3. Если материал имел `qty_overridden = true`, перед пересчётом его старое значение сохраняется в `qty_manual_backup`. После пересчёта показывается тост: _«Объём был задан вручную, сейчас пересчитан по нормативу. Нажмите ↩ чтобы вернуть предыдущий объём»_ — кнопка в тосте восстанавливает `qty_manual_backup`
4. На строке материала отображается мелкий серый текст прямо под числом: `«авто: 50 кг (норм. 0.5 на м²)»` — без hover, всегда видим
5. При ручном изменении `qty` материала → `qty_overridden = true`, текст меняется на `«задано вручную»`, показывается тост: _«Объём задан вручную, авто-расчёт отключён. Нажмите ↩ чтобы вернуть авто.»_ — кнопка в тосте сбрасывает `qty_overridden` и восстанавливает последнее авто-значение (`qty_manual_backup`)
6. Кнопка ↩ на ячейке `qty` материала с `qty_manual_backup != null`:
   - иконка «возврат» (↩ или ⤺), не «обновление» (↺)
   - подсказка при наведении: `«Вернуть ручной объём: 45 кг»` (конкретное значение, не абстракция)
   - нажатие восстанавливает `qty_manual_backup` и сбрасывает `qty_overridden`
   - кнопка не показывается, если `work_row_id` не найден в `activeRows`
   - нажатие не открывает редактор ячейки: `e.stopPropagation()` + `onMouseDown e.preventDefault()`
7. `qty_per_work_unit` и `norm_reference` заполняются Claude при импорте сметы по ГЭСН-2017/ФСНБ-2022. Если Claude не нашёл норму для данной пары работа–материал — поля `null`, пересчёт не применяется
8. Строки материалов с `qty_overridden = true` выделяются цветом (отдельный цвет, добавляется в существующую легенду цветов строк в редакторе)
9. При первом открытии сметы с нормативами — показывается однократная dismissable-плашка вверху грида: _«В этой смете работает авто-расчёт материалов. При изменении объёма работы материалы пересчитаются автоматически.»_ + кнопка «Понятно». Факт прочтения хранится в `localStorage`
10. После пересчёта — кратковременная подсветка (flash-анимация 1.5–2 сек: жёлтый фон → прозрачный) на ячейках `qty` всех пересчитанных материалов. То же — при Undo/Redo
11. `qty_per_work_unit = 0` — валидно. Показывается: `«авто: 0 кг (норм. 0 на м²)»`
12. Нормативы копируются вместе с данными строк при создании новой версии сметы (хранятся inline — автоматически)
13. Undo/Redo корректно откатывает и `work.qty`, и пересчитанные `material.qty`, и `qty_manual_backup`

## Архитектурные решения

- **Норматив хранится inline** в JSON-поле `rows` (без новых таблиц и миграций БД)
- **Нормативы получает Claude** — при импорте сметы вызывается отдельный async-шаг в `task_processor.py`, который отправляет структуру работа→материалы в Claude с промптом по ГЭСН-2017/ФСНБ-2022. Локальной базы нет. Схема точно такая же, как в `_handle_check_completeness`: чанкинг по `_chunk_by_work_boundaries`, по 25 элементов, Claude возвращает `qty_per_work_unit` и `norm_reference` на каждый материал
- **`parse_estimate_excel()` остаётся синхронной** — только парсит структуру и проставляет `work_row_id`. Claude-шаг вызывается отдельно после неё в async-обработчике
- **Пересчёт — клиентский**, выполняется в `handleRowsChange` в `EstimateGrid.tsx` (не внутри `NumberEditor`) — там доступны все строки сразу
- **Пересчёт применяется к полному `rows`** (до фильтрации по табам «Работы» / «Всё»), результат затем мерджится обратно — иначе изменения материалов потеряются при активном табе «Работы»
- **Ретроактивная миграция не нужна** — нормативы заполняются только при новых парсингах; существующие сметы остаются без нормативов
- **Комментарий** — мелкий серый текст в ячейке (second-line), не тултип

## Новые поля в EstimateRow

```python
work_row_id: Optional[str] = None           # ссылка на id работы
qty_per_work_unit: Optional[float] = None   # норматив ГЭСН: кол-во материала на 1 ед. работы
qty_overridden: Optional[bool] = None       # True = задано вручную
qty_manual_backup: Optional[float] = None  # сохранённый ручной объём до последнего пересчёта
norm_reference: Optional[str] = None       # ссылка на норму, напр. «ГЭСН 08-01-003»
```

Все поля опциональные — полная обратная совместимость.

## Фазы

### [x] Фаза 1 — Схема данных

- [x] `backend/app/schemas/estimate_version.py` — добавить пять полей в `EstimateRowSchema`
- [x] `frontend/src/types/index.ts` — добавить пять полей в `interface EstimateRow`

### [x] Фаза 2 — Обогащение нормативами ГЭСН при импорте (backend)

Схема реализации полностью аналогична `_handle_check_completeness` в `task_processor.py`.

#### Шаг 2.1 — Синхронная привязка материалов к работам

В конце `parse_estimate_excel()` вызывается синхронная утилита `link_materials_to_works(rows)` — только проставляет `work_row_id`, Claude не вызывает:

```python
def link_materials_to_works(rows: list[dict]) -> list[dict]:
    last_work = None
    for row in rows:
        if row["type"] == "work":
            last_work = row
        elif row["type"] == "material" and last_work is not None:
            row["work_row_id"] = last_work["id"]
        # section — не сбрасывает last_work
    return rows
```

**Ограничение:** несколько работ подряд без материалов между ними — последующие материалы привязываются к последней работе. Это осознанное ограничение, задокументированное здесь.

#### Шаг 2.2 — Async Claude-шаг: получение нормативов ГЭСН

Вызывается в `task_processor.py` **после** `parse_estimate_excel()`, перед сохранением `EstimateVersion`. Оба места вызова парсера (строки ≈1799 и ≈1835) обрабатываются одинаково.

**Новый промпт** `PROMPT_ENRICH_NORMS` в `task_processor.py`:

```
Ты — опытный инженер-сметчик со знанием ГЭСН-2017/ФСНБ-2022, ФЕР/ТЕР по Свердловской области.

Тебе передан перечень работ и материалов из строительной сметы.
Для каждого материала определи норматив расхода на единицу работы по ГЭСН/ФСНБ.

Для каждого материала верни:
- qty_per_work_unit: число (норма расхода на 1 единицу работы) или null, если норма не определена
- norm_reference: шифр нормы, например "ГЭСН 08-01-003" или null

Верни результат СТРОГО в формате JSON, без markdown, первый символ {, последний }:
{
  "materials": [
    {
      "row_id": "id строки материала",
      "qty_per_work_unit": число или null,
      "norm_reference": "ГЭСН XX-XX-XXX" или null
    }
  ]
}

ВАЖНО: отвечай ТОЛЬКО валидным JSON. Никакого текста до { или после }.
```

**Новая async-функция** `_enrich_rows_with_gesn_norms(rows)` в `task_processor.py`:

```python
async def _enrich_rows_with_gesn_norms(self, rows: list[dict]) -> list[dict]:
    # Чанкинг по границам работ, аналогично _handle_check_completeness
    chunks = _chunk_by_work_boundaries(rows, max_chunk_size=25)
    rows_by_id = {r["id"]: r for r in rows}

    for chunk in chunks:
        chunk_json = json.dumps({"items": chunk}, ensure_ascii=False, indent=2)
        messages = [{"role": "user", "content": f"{chunk_json}\n\n{PROMPT_ENRICH_NORMS}"}]
        try:
            data = await self._interruptible_claude_json_with_retry(
                messages, system_prompt=SYSTEM_BASE, processing_timeout=120.0
            )
        except Exception:
            # Не падаем — строки останутся без нормативов
            continue

        for item in data.get("materials", []):
            row = rows_by_id.get(item.get("row_id"))
            if row and item.get("qty_per_work_unit") is not None:
                row["qty_per_work_unit"] = item["qty_per_work_unit"]
                row["norm_reference"] = item.get("norm_reference")

    return rows
```

Порядок вызовов в обработчике:
```python
rows = parse_estimate_excel(file_data)          # синхронно — парсинг + link_materials_to_works
rows = await self._enrich_rows_with_gesn_norms(rows)  # async — Claude ГЭСН
# далее сохранение EstimateVersion
```

### [x] Фаза 3 — Логика пересчёта (frontend)

- [x] Создать `frontend/src/utils/estimateRecalc.ts`:
  - `applyWorkQuantityChange(rows, changedWorkId, newQty)` — пересчёт **всех** связанных материалов, включая `qty_overridden = true`; для последних сохраняет `qty_manual_backup` (только если `qty_manual_backup` ещё не было — т.е. не перезатирает уже сохранённое)
  - `buildNormComment(row, workUnit?)` — возвращает строку: `«авто: 50 кг (норм. 0.5 на м²)»`; `norm_reference` добавляется в `title` ячейки; при `qty_overridden` возвращает `«задано вручную»`

- [x] `frontend/src/components/estimate/EstimateGrid.tsx`:
  - **Пересчёт в `handleRowsChange`**: если изменилась работа → `applyWorkQuantityChange(fullRows, workId, newQty)`, результат мерджится перед сохранением
  - В `NumberEditor.commit()` при `row.type === 'material'` → `qty_overridden: true` (без удаления `qty_manual_backup`)
  - Отображение `buildNormComment` как мелкий серый second-line текст в ячейке `qty` материала (`QtyCell` через `GridContext`)
  - Кнопка ↩ для материалов с `qty_manual_backup != null` — `e.preventDefault()` + `e.stopPropagation()`, title с конкретным значением
  - Flash-анимация (row-класс `row-recalc-flash`, 1.8 сек, yellow fade)
  - Цвет `row-qty-overridden` (amber) в палитре и в легенде
  - Однократный баннер (localStorage `smeta_recalc_banner_seen`)
  - Тост при пересчёте overridden-строк с кнопкой «↩ Вернуть»
  - Тост при ручном изменении qty материала с нормой с кнопкой «↩ Вернуть авто»
  - Undo/Redo: flash через useEffect с детектированием внешних изменений rows

- [x] `frontend/src/stores/estimateEditor.ts` — без изменений: `updateRows()` уже корректно сохраняет снапшот до применения новых rows

### [ ] Фаза 4 — Тесты

- [ ] `backend/tests/test_estimate_norms.py`:
  - `test_link_materials_sets_work_row_id` — синхронная привязка
  - `test_link_materials_section_does_not_break_link` — section не сбрасывает last_work
  - `test_link_materials_multiple_works_in_row_links_to_last` — документирует ограничение
  - `test_enrich_norms_stores_qty_per_work_unit` — Claude-ответ записывается в строку
  - `test_enrich_norms_stores_norm_reference` — ссылка на норму сохраняется
  - `test_enrich_norms_skips_null_from_claude` — null-норма не перезаписывает поле
  - `test_enrich_norms_tolerates_claude_error` — при ошибке Claude строки остаются без нормативов, не падают

- [ ] `frontend/src/utils/estimateRecalc.test.ts`:
  - `applyWorkQuantityChange` пересчитывает материалы без `qty_overridden`
  - `applyWorkQuantityChange` пересчитывает материалы **с** `qty_overridden = true` и сохраняет `qty_manual_backup`
  - `applyWorkQuantityChange` не перезатирает `qty_manual_backup`, если он уже был
  - `applyWorkQuantityChange` пропускает материалы без `qty_per_work_unit`
  - `applyWorkQuantityChange` пропускает материалы с другим `work_row_id`
  - `buildNormComment` формирует `«авто: 50 кг (норм. 0.5 на м²)»`
  - `buildNormComment` возвращает `«задано вручную»` при `qty_overridden` и нет `qty_per_work_unit`
  - `buildNormComment` при `qty_per_work_unit = 0` → `«авто: 0 кг (норм. 0 на м²)»`

## Edge Cases (решены до имплементации)

### Данные при парсинге

| Ситуация | Решение |
|---|---|
| Claude не нашёл норму для пары работа–материал | `qty_per_work_unit = null`, пересчёт не применяется |
| Claude вернул ошибку или невалидный JSON | Строки остаются без нормативов, сохранение не блокируется |
| `material.qty = null` | Норматив `null` |
| `material.qty = 0` | `qty_per_work_unit = 0` — валидно, показывается `«авто: 0»` |
| Материал стоит до любой работы | `work_row_id = null` — пересчёт не применяется |
| Строка `section` между работой и материалами | `section` не сбрасывает `last_work`, связь сохраняется |
| Несколько работ подряд без материалов | Материалы после них привязываются к последней работе (ограничение) |

### Ручное редактирование в UI

| Ситуация | Решение |
|---|---|
| `work.qty = 0` после редактирования | Материалы получают `qty = 0` — корректно |
| Отрицательное число | Допустимо для корректировочных позиций |
| Материал с `qty_overridden = true` | Пересчёт срабатывает, `qty_manual_backup` сохраняется, показывается тост |
| `qty_manual_backup` уже был | Не перезатирается — пользователь может вернуть исходный ручной объём |
| Пользователь удаляет работу | Материалы с `work_row_id` на удалённую строку работают как обычные строки |
| Кнопка ↩ при удалённой работе | Не показывается |
| Кнопка ↩ при `qty_manual_backup = null` | Не показывается |
| Пользователь меняет цену, не объём | Пересчёт не триггерится |
| Перемещение строк в таблице | `work_row_id` — id-based, не позиционный → пересчёт корректен |
| Активен таб «Работы» | Пересчёт применяется к полному `rows` (не `displayedRows`) — данные не теряются |

### Undo/Redo

| Ситуация | Решение |
|---|---|
| Undo после пересчёта | Снапшот включает все пересчитанные строки → undo откатывает и `work.qty`, и `material.qty` одновременно |
| Undo после ручного редактирования | `qty_overridden` и `qty_manual_backup` восстанавливаются из снапшота |
| Flash-анимация при Undo/Redo | Применяется к строкам, затронутым откатом |

### Производительность

| Сценарий | Решение |
|---|---|
| 500+ строк в смете | `applyWorkQuantityChange` O(n), ~0.1мс — не блокирует UI |
| 50 материалов у одной работы | Все пересчитываются за один проход |
| Debounce 500мс | Пересчёт синхронный в store → бэкенд получает уже финальные данные |

## Итог

- [ ] Реализован целиком
- [x] Реализован частично
- [ ] Не реализован

**Что осталось:** Фаза 4 — тесты (`backend/tests/test_estimate_norms.py` и `frontend/src/utils/estimateRecalc.test.ts`)
