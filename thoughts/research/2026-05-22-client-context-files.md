# Research: Использование файлов "Проект", "ТЗ", "Другое" при оптимизации сметы

**Дата:** 2026-05-22
**Задача:** Передавать контекстные файлы заказчика в Claude на этапах оптимизации сметы

---

## Текущее состояние

### Загрузка файлов (frontend/src/pages/TaskCreate.tsx:215)
- Основная смета: `index=0`, тип не помечается
- Файлы заказчика: `index=1..N`, с типами "Смета"/"Проект"/"ТЗ"/"Другое"
- Метаданные кодируются в `task.user_prompt` JSON: `{ "client_files": [{ "index": 1, "type": "Проект" }] }`

### Хранение (backend/app/models/task_input_file.py)
- Таблица `task_input_files` — одна запись на файл
- Поля: `task_id`, `file_index`, `file_name`, `mime_type`, `content` (bytes)

### Обработка (backend/app/services/task_processor.py:1996)
- `_handle_estimate_optimization()` обрабатывает только `file_type == "Смета"` → EstimateVersion.client
- Остальные типы игнорируются

---

## Этапы оптимизации (backend/app/routers/estimate_versions.py)

Функция `_run_optimization_step()` — основной обработчик всех этапов:
1. `completeness` — проверка полноты по ГЭСН
2. `redundancy` — удаление лишних позиций
3. `technology` — оптимизация технологий
4. `materials` — оптимизация материалов
5. `fill_prices` — проставление цен (отдельный путь, не через `_run_optimization_step`)

---

## Что умеет parse_file() (backend/app/utils/file_parser.py)

| Формат | MIME | Как парсится | Результат |
|--------|------|-------------|-----------|
| PDF | application/pdf | pdf_to_content_block() | Claude Vision block |
| XLSX | application/vnd.openxmlformats... | parse_xlsx() | Текст таблиц |
| XML | text/xml, application/xml | parse_xml() | Структурированный текст |
| JPG/PNG | image/* | file_to_base64() | Claude Vision block |
| Остальное | * | decode UTF-8 | Fallback текст |

**GSN формат — не поддерживается.**

---

## call_claude() (backend/app/services/claude_service.py)

Уже поддерживает параметр `image_data: Optional[list]` — можно передавать PDF/image блоки.

---

## Рекомендуемое использование по этапам

| Этап | Тип файла | Приоритет | Механизм |
|------|-----------|-----------|---------|
| completeness | Проект, ТЗ | Средний | Текст в промпт |
| **redundancy** | **Проект** | **Критичный** | PDF → image_blocks |
| **technology** | **Проект** | **Критичный** | PDF → image_blocks |
| materials | Другое (спецификации) | Низкий | XLSX → текст в промпт |
| fill_prices | — | Не нужен | — |

**Почему redundancy — критичный:** без проекта Claude угадывает, какие позиции "вне границ работ", что даёт ложные срабатывания.

**Почему technology — критичный:** высоты помещений, условия строительства, типология объекта влияют на выбор технологий.

---

## Ключевые файлы для изменений

1. `backend/app/routers/estimate_versions.py` — `_run_optimization_step()`, добавить загрузку контекста
2. `backend/app/services/task_processor.py` — промпты этапов (если там)
3. `backend/app/utils/file_parser.py` — возможно, добавить text-only режим для больших файлов

---

## Рекомендация

**Подход:** Гибридный
- PDF/изображения → `image_data` в `call_claude()`
- XLSX/XML/текст → текст в промпт

**Фаза 1 (эта реализация):** Текстовый режим для всех форматов — проще, безопаснее, не требует изменений в `call_claude()`. PDF парсить через существующий `parse_file()` который возвращает content block — но если не строка, добавить text-fallback через pdfplumber или просто пометить что файл есть.

**Риск:** Большие PDF могут переполнить контекстное окно. Решение: truncate до N символов с пометкой "(обрезано)".
