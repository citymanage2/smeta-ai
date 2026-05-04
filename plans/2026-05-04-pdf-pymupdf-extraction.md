# PDF: извлечение текста через PyMuPDF

## Цель

В задаче «Перечень из проекта» извлекать embedded-текст из PDF до отправки в Claude.
Текстовые страницы → текстом, страницы без текста (чертежи/сканы) → картинками.
Снижает расход токенов, повышает стабильность результата.

## Область изменений

Только `_handle_list_from_project()` и новый утилитный модуль.
`parse_file()`, `_build_file_contents()`, `_build_messages_with_files()` — не трогаем.

## Фазы

- [x] Фаза 1 — Зависимости: добавить `pymupdf==1.25.3` в `backend/requirements.txt`
- [x] Фаза 2 — Новый модуль `backend/app/utils/pdf_text_extractor.py`
- [x] Фаза 3 — Интеграция в `_handle_list_from_project()` (task_processor.py)
- [x] Фаза 4 — Gates (py_compile, ruff) + commit

## Порог текст/чертёж

30 слов на страницу — стартовое значение, скорректировать после тестов на реальных PDF.

## Итог

Реализован целиком. Изменены файлы:
- `backend/requirements.txt`
- `backend/app/utils/pdf_text_extractor.py` (новый)
- `backend/app/services/task_processor.py`
