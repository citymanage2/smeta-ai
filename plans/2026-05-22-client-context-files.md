# План: Использование файлов "Проект", "ТЗ", "Другое" при оптимизации сметы

**Дата:** 2026-05-22  
**Статус:** [ ] В работе

---

## Challenge Log

1. РЕШАЕТ ЛИ ПЛАН ПРОБЛЕМУ? — Да. Файлы будут переданы в Claude на этапах optimizatii.
2. САМОЕ ЭФФЕКТИВНОЕ РЕШЕНИЕ? — Да. Используем уже существующие механизмы: `parse_file()`, `image_data` в `call_claude()`, `TaskInputFile` таблица. Без новых зависимостей.
3. КОД РАДИ КОДА? — Нет. Только одна новая вспомогательная функция + изменения в промптах.

---

## Фаза 1: Хелпер + интеграция в _run_optimization_step

**Файл:** `backend/app/routers/estimate_versions.py`

### Задачи

- [ ] Добавить импорты: `TaskInputFile`, `base64`, `parse_file`
- [ ] Написать `_load_client_context(task, db)` — возвращает `(text: str, image_blocks: list[dict])`
  - Читает `task.user_prompt` → `client_files` metadata
  - Загружает `TaskInputFile` по `task_id`
  - Для файлов с типом НЕ "Смета": парсит через `parse_file()`
  - Если результат — строка: добавляет в текстовый контекст (truncate до 8000 символов)
  - Если результат — dict (PDF/image block): добавляет в `image_blocks`
  - Возвращает `(text_context, image_blocks)`
- [ ] В `_run_optimization_step()`, после строки 605 (формирование `rows_json`):
  - Вызвать `_load_client_context(task, db)` для этапов: completeness, redundancy, technology, materials
  - Если `text_context`: добавить секцию `=== ДОКУМЕНТАЦИЯ ЗАКАЗЧИКА ===` перед строками сметы в промпте
  - Если `image_blocks`: передать в `call_claude(image_data=image_blocks)`
- [ ] Обновить промпты этапов — добавить инструкцию использовать контекст если он есть

**Статус:** [x]

---

## Итог

Реализован целиком: [x]  
Что осталось: —

## Изменения

- `backend/app/routers/estimate_versions.py`:
  - Добавлены импорты: `base64`, `json as _json_top`, `TaskInputFile`, `parse_file as _parse_file`
  - Добавлены константы: `_CONTEXT_FILE_TYPES`, `_CONTEXT_TEXT_LIMIT`
  - Добавлена функция `_load_client_context(task, db)` — загружает файлы "Проект"/"ТЗ"/"Другое" по метаданным из `task.user_prompt`, возвращает текст + image_blocks
  - В `_run_optimization_step()`: после формирования `rows_json` вызывается `_load_client_context`, результат вставляется в промпт и передаётся как `image_data` в `call_claude`
  - Все 4 промпта этапов дополнены инструкцией использовать документацию заказчика

## Следующий шаг (опционально)

Передавать PDF через Claude Vision API (`image_data`) уже реализовано. При желании можно добавить логирование — сколько файлов контекста было передано в каждом запуске.
