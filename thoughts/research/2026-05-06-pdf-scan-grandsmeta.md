# Research: PDF-скан в задаче «Перечень из Гранд-сметы»

## Текущее состояние

### Бэкенд (`task_processor.py`)
- `_handle_list_from_grand()` — ищет только xlsx/excel MIME в вложениях. PDF игнорирует.
- `PROMPT_LIST_FROM_GRAND` — работает с табличным текстом из xlsx (строки → чанки через `chunk_rows()`).
- Импорты: `parse_xlsx_grand`, `chunk_rows`, `rows_to_text` из `app/utils/file_parser.py`; `generate_list` из `app/services/excel_service.py`.

### Готовая инфраструктура
- `extract_pdf_hybrid()` в `app/utils/pdf_text_extractor.py` — уже работает:
  - PyMuPDF: если страница ≥30 слов → берёт embedded-текст
  - Иначе → PNG base64 для Claude Vision
  - Используется в `_handle_list_from_project()`
- `pymupdf==1.25.3` — уже в requirements.txt
- FileUpload на фронте уже принимает `.pdf`

### Чего не хватает
- Tesseract (pytesseract) — не установлен
- Pillow — не в requirements.txt (нужна для pytesseract)
- Нет OCR-утилиты для grandsmeta-PDF
- Нет промпта под сырой OCR-текст гранд-сметы
- Нет UI-переключателя Excel/PDF-скан в форме

## Решение (подтверждено пользователем)

| Вопрос | Решение |
|---|---|
| Тип PDF | Оба: скан + цифровой |
| Стратегия для image-страниц | Tesseract OCR |
| Деплой Tesseract | Dockerfile (apt-get) |
| Одновременная загрузка xlsx+pdf | Запрещена, взаимоисключение |
| UI | Два таба «Excel» / «PDF-скан» в форме |

## Архитектура новой функции

### Новый модуль: `pdf_ocr_extractor.py`
```
pdf_bytes → PyMuPDF страницы
  ├── страница с embedded текстом (≥30 слов) → text напрямую
  └── страница без текста (скан)             → PNG → pytesseract → text

Результат: список [{"page": N, "text": str, "method": "embedded"|"ocr"}]
```

### Изменение `_handle_list_from_grand()`
```
Текущий поток:
  файлы → найти xlsx → parse_xlsx_grand → chunk_rows → Claude (PROMPT_LIST_FROM_GRAND)

Новый поток:
  файлы:
    ├── xlsx найден → старый поток (без изменений)
    └── pdf найден  → extract_pdf_with_ocr → chunk_pdf_pages → Claude (PROMPT_LIST_FROM_GRAND_PDF)
    └── оба        → ошибка (обрабатывается на фронте)
    └── ничего     → ошибка как сейчас
```

### Чанкинг PDF
- Xlsx: `chunk_rows()` делит по ~100 строк с сохранением границ «работ»
- PDF: делим по N страниц (по 5-8 страниц на чанк)
- Прогресс и resume-логика — такая же через `progress_data`

### Новый промпт `PROMPT_LIST_FROM_GRAND_PDF`
- Тот же JSON-формат на выходе
- Учитывает особенности OCR-текста гранд-сметы:
  - Коды ТЕР/ФЕР/ГЭСН → игнорировать цены, брать только наименование+ед+кол-во
  - Артефакты OCR (лишние символы, переносы строк) → Claude сам справляется
  - Итоговые строки (Итого, Всего) → пропускать

### Frontend (`TaskCreate.tsx`)
- Новый стейт: `grandInputMode: 'excel' | 'pdf'`
- Только для `taskType === 'LIST_FROM_GRAND'`: показывать табы под заголовком задачи
- Excel-таб: FileUpload с `accept=".xlsx,.xls"`
- PDF-таб: FileUpload с `accept=".pdf"`
- При смене таба: сбрасывать `files`

## Зависимости

| Пакет | Где | Назначение |
|---|---|---|
| `pytesseract>=0.3.13` | requirements.txt | Python-обёртка Tesseract |
| `Pillow>=10.0.0` | requirements.txt | PIL Image для pytesseract |
| `tesseract-ocr` | Dockerfile apt-get | Tesseract engine |
| `tesseract-ocr-rus` | Dockerfile apt-get | Русский языковой пакет |

## Что НЕ меняется
- Модели БД (новых полей не нужно — mime_type уже хранится в `task_input_files`)
- API роутер (`/tasks` POST) — уже принимает любые файлы по допустимым форматам
- `generate_list()` — тот же экспортёр, одинаковый выход
- Логика cancel/resume — копируется из xlsx-ветки

## Рекомендуемый подход — ВЫБРАН
Вариант B (Hybrid OCR): embedded text там где есть, Tesseract там где скан.
Это избегает ненужных затрат на Vision-токены и уже проверено в `extract_pdf_hybrid()`.
