# Custom Export Builder — кастомная выгрузка из сводной таблицы

**Дата:** 2026-05-14  
**Статус:** в работе

## Зачем

Пользователям нужно отправлять в снабжение перечни работ или материалов по одному или нескольким разделам. Текущий экспорт отдаёт всю сводную целиком. Нужен инструмент, позволяющий:
- Выбрать разделы (один/несколько/все)
- Выбрать тип строк: работы / материалы / всё
- Выбрать столбцы (убрать цены, стоимости, комментарии — если они не нужны)
- Отредактировать строки онлайн перед скачиванием
- Скачать результат в Excel

## Пользовательский сценарий

1. Открыть сводную → нажать «Сформировать выгрузку»
2. Шаг 1 (Config): выбрать разделы, тип строк, столбцы → «Далее»
3. Шаг 2 (Preview): отредактировать таблицу inline → «Скачать Excel»
4. Файл скачивается локально

## Архитектура

### Backend

**Новый endpoint:**
```
POST /api/projects/{project_id}/summary/custom-export
Content-Type: application/json
→ application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
```

**Тело запроса:**
```json
{
  "selected_section_ids": ["uuid1"],   // пусто = все разделы
  "row_types": ["work", "material"],   // "work" | "material" | оба
  "visible_columns": ["num", "name", "unit", "qty", "price_work", "price_material"],
  "rows": [                            // строки после редактирования (из фронта)
    { "section_name": "...", "num": 1, "name": "...", "unit": "шт", "qty": 5, ... }
  ]
}
```

**Новые файлы/функции:**
- `backend/app/utils/xlsx_summary.py` — добавить `generate_custom_export_xlsx(rows, visible_columns, section_groups)`
- `backend/app/schemas/summary_estimate.py` — добавить `CustomExportRequest`, `CustomExportRow`
- `backend/app/routers/summary.py` — добавить роут `POST .../custom-export`

### Frontend

**Новый компонент:**
- `frontend/src/components/summary/CustomExportModal.tsx`

**Изменения:**
- `frontend/src/components/summary/SummaryEditorTabs.tsx` — кнопка «Сформировать выгрузку»
- `frontend/src/api/summaryEstimate.ts` — функция `customExport(...)`

**Стейт модала:**
```typescript
step: 'config' | 'preview'
selectedSectionIds: Set<string>    // выбранные разделы
rowTypes: ('work' | 'material')[]  // тип строк
visibleColumns: string[]           // выбранные столбцы
editableRows: ExportRow[]          // строки для редактирования
```

**Столбцы (доступные):**
| key | Заголовок |
|---|---|
| num | № |
| name | Наименование |
| unit | Ед. изм. |
| qty | Кол-во |
| price_work | Цена работ |
| cost_work | Стоимость работ |
| price_material | Цена матер. |
| cost_material | Стоимость матер. |
| section | Раздел |

Столбцы по умолчанию: `num, name, unit, qty, price_work, cost_work, price_material, cost_material`

## Фазы реализации

### Фаза 1 — Backend [ ]
- [ ] Схемы `CustomExportRow`, `CustomExportRequest` в `schemas/summary_estimate.py`
- [ ] Функция `generate_custom_export_xlsx` в `utils/xlsx_summary.py`
- [ ] Роут `POST /projects/{project_id}/summary/custom-export` в `routers/summary.py`

### Фаза 2 — Frontend [ ]
- [ ] API-функция `customExport` в `api/summaryEstimate.ts`
- [ ] Компонент `CustomExportModal.tsx` — шаг Config
- [ ] Компонент `CustomExportModal.tsx` — шаг Preview (inline editing)
- [ ] Кнопка в `SummaryEditorTabs.tsx`

## Итог

- [ ] Реализован целиком
- [ ] Что осталось: —
