# Spec: Code Review Fixes
**Date:** 2026-04-22
**Type:** Bug fixes + надёжность
**Status:** Approved

---

## Проблема

Code review по принципам review-sm-smeta выявил 7 нарушений: 3 блокирующих (финансовая ошибка, race condition, потеря задач), 3 важных (перерасход API, хрупкий semantic search, неточный timeout), 1 будущее (индекс БД).

## Цель

Устранить все найденные нарушения без изменения публичного API и UX.

## Scope

| # | Исправление | Файлы |
|---|------------|-------|
| 1 | VAT_RATE = 0.22 → одна константа в config.py | config.py, excel_service.py, xlsx_optimizer.py |
| 2 | asyncio.Lock для price cache | price_service.py |
| 3 | Retry чанков в task_processor (3 попытки) | task_processor.py |
| 4 | Prompt caching в Claude API | claude_service.py |
| 5 | Sparse embedding matrix | price_service.py |
| 6 | Cumulative timeout с учётом rate-limit sleep | claude_service.py |
| 7 | Составной индекс tasks(project_id, estimation_status) | models/task.py + миграция |

## Критерии приёмки

- [ ] Все функции `generate_*` в excel_service.py используют `settings.VAT_RATE = 0.22`
- [ ] `xlsx_optimizer.py` использует `settings.VAT_RATE`
- [ ] Тест `test_xlsx_optimizer.py` обновлён с VAT=0.22
- [ ] Заголовок НДС в Excel динамический (`f"НДС ({int(settings.VAT_RATE*100)}%)"`)
- [ ] `load_cache()` захватывает `asyncio.Lock` при обновлении глобалов
- [ ] Одиночная строка без эмбеддинга не ломает матрицу
- [ ] Чанк с transient-ошибкой Claude ретраится ≤3 раз перед падением задачи
- [ ] `TaskCancelledError` не ретраится — пробрасывается немедленно
- [ ] `call_claude()` уменьшает remaining_timeout после каждого rate-limit sleep
- [ ] System prompt передаётся с `cache_control: ephemeral`
- [ ] `ruff check .` — 0 ошибок
- [ ] `pytest --tb=short -q` — все тесты зелёные

## Нон-цели

- Изменение публичного REST API
- UI-изменения
- Рефакторинг сверх минимально необходимого
- Idempotency key (отдельная задача)
