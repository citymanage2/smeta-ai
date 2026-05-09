# PDF-скан в задаче «Перечень из Гранд-сметы»

**Дата:** 2026-05-06  
**Статус:** в работе  
**Research:** `thoughts/research/2026-05-06-pdf-scan-grandsmeta.md`

## Цель

Добавить возможность загрузки PDF-скана (или цифрового PDF) гранд-сметы в задаче «Перечень из Гранд-сметы». Система распознаёт текст через Tesseract OCR (для скан-страниц) и PyMuPDF (для цифровых страниц), затем извлекает перечень работ и материалов через Claude — результат тот же xlsx-файл.

## Edge Cases — найдено и решено заранее

### Группа A: PDF-файл сам по себе

| # | Сценарий | Что сломается | Решение |
|---|---|---|---|
| A1 | Пустой PDF (0 страниц) | chunk_pdf_pages([]) → нет чанков → accumulated_items=[] → generate_list() с пустым списком, задача «завершена» без результата | После `fitz.open()` проверить `len(doc) == 0` → `raise ValueError("PDF не содержит страниц")` |
| A2 | PDF с паролем | `fitz.open()` открывается, но `doc.needs_pass == True` → попытка читать страницы бросает исключение | Сразу после open: `if doc.needs_pass: raise ValueError("PDF защищён паролем — снимите защиту перед загрузкой")` |
| A3 | Повреждённый PDF | `fitz.open()` бросает `fitz.FileDataError` или `Exception` | Обернуть в `try/except Exception as e: raise ValueError(f"Не удалось открыть PDF: {e}")` |
| A4 | PDF > 150 страниц | 150/8 = ~19 чанков × Claude API = долго и дорого; Render может получить timeout | `if len(doc) > 150: raise ValueError(f"PDF слишком большой ({len(doc)} стр.). Разбейте на части по 100 страниц.")` |
| A5 | PDF 50-150 страниц | Медленно, пользователь не понимает что происходит | `if len(doc) > 50: await self.update_progress(f"Большой файл: {len(doc)} страниц, обработка займёт несколько минут...")` |
| A6 | Файл не PDF, но с расширением .pdf | fitz может открыть или бросить исключение | Покрывается A3 (try/except вокруг open) |

### Группа B: Память и производительность

| # | Сценарий | Что сломается | Решение |
|---|---|---|---|
| B1 | A3/A4 скан при высоком DPI | A3 @ 300dpi → pixmap ~52MB RAM на страницу; 20 страниц → 1GB → OOM на Render | Использовать **dpi=200** (достаточно для OCR). Для страниц шире 2480px — масштабировать до max 2480px |
| B2 | Накопление всех pixmap в памяти | Если делать pixmap для каждой страницы до передачи в OCR → держим всё в RAM | Обрабатывать **постранично**: pixmap → PIL Image → pytesseract → text → pixmap удаляется. Не хранить все pixmap |
| B3 | PNG round-trip (bytes → encode → decode) | Лишние аллокации | Использовать `pix.pil_image()` (PyMuPDF ≥1.21, у нас 1.25.3) → PIL Image напрямую, без encode PNG |
| B4 | Конкурентные OCR-задачи | Tesseract — CPU-bound subprocess; несколько одновременных задач — CPU насыщение | Принять риск (малое число пользователей). Зафиксировать в логах: `logger.info("OCR start/end page N")` |

### Группа C: Tesseract / OCR

| # | Сценарий | Что сломается | Решение |
|---|---|---|---|
| C1 | Tesseract не установлен | `TesseractNotFoundError` → задача падает с cryptic error | `except pytesseract.pytesseract.TesseractNotFoundError: raise ValueError("OCR-движок не установлен. Обратитесь к администратору.")` |
| C2 | Нет языкового пакета rus | `tesseract` выдаёт ошибку или использует только eng | В Dockerfile устанавливаем оба: `tesseract-ocr tesseract-ocr-rus`. В коде `lang="rus+eng"` |
| C3 | Tesseract завис на сложной странице | По умолчанию нет таймаута → задача зависает навсегда | `pytesseract.image_to_string(img, lang="rus+eng", timeout=30)` — 30 сек. на страницу |
| C4 | OCR возвращает пустую строку | Страница есть, текста нет → в чанке только заголовок `--- Страница N ---` → Claude обрабатывает пустой чанк (тратит токены) | Пропускать чанки где суммарный текст < 20 символов после strip |
| C5 | Низкое качество скана — мусорный OCR | Tesseract выдаёт "||Р@бот@ 111||" → Claude получает мусор → вернёт пустые items | Добавить в промпт указание: "если строка нечитаема — пропускай". Нельзя гарантировать качество OCR, но Claude устойчив к артефактам |
| C6 | Tesseract timeout бросает исключение | При timeout pytesseract бросает `RuntimeError` | Поймать, залогировать, продолжить с пустой строкой для этой страницы: `logger.warning("OCR timeout page N")` |

### Группа D: Кодировка embedded-текста

| # | Сценарий | Что сломается | Решение |
|---|---|---|---|
| D1 | Старый PDF из ГрандСметы с нестандартной кодировкой шрифта | `page.get_text()` возвращает "????????????????" или "ААААА" (много слов, но мусор) — страница классифицируется как "text" (≥30 слов), но текст непригоден | Перед принятием embedded-текста проверять: если доля кириллических символов < 10% при word_count ≥ 30 → считать OCR-страницей |
| D2 | PDF с watermark поверх текста | OCR видит watermark как текст → добавляет мусорные строки в чанк | Claude устойчив к такому мусору (промпт говорит восстанавливать смысл). Принять риск. |

### Группа E: Бизнес-логика обработки

| # | Сценарий | Что сломается | Решение |
|---|---|---|---|
| E1 | Все чанки вернули пустые items | accumulated_items=[] в конце → generate_list([]) → пустой xlsx → пользователь не понимает что произошло | После цикла: `if not accumulated_items: raise ValueError("Не удалось извлечь позиции из PDF. Проверьте качество скана.")` |
| E2 | Пользователь загружает xlsx И pdf одновременно (через API напрямую) | Фронт блокирует, но API открыт | В `_handle_list_from_grand()` при обнаружении обоих: `raise ValueError("Загрузите один файл: либо .xlsx, либо .pdf, но не оба сразу")` |
| E3 | Resume: при повторном запуске PDF перечитывается и переOCR-ится заново | Медленнее чем хотелось бы, но корректно (те же chunks_done пропускаются) | Принять — то же поведение что у xlsx (пересчитывает rows каждый раз). Документировать. |
| E4 | PDF с 0 извлечёнными страницами после фильтрации (все → пустые чанки) | chunk_pdf_pages возвращает [] → цикл не запускается → empty items | Покрывается A1 + E1 |

### Группа F: Фронтенд

| # | Сценарий | Что сломается | Решение |
|---|---|---|---|
| F1 | Пользователь загрузил файл → переключил таб → потерял файл | UX-фрустрация | Сбрасывать файл при смене таба (запланировано). Для внутреннего инструмента — приемлемо. |
| F2 | Перетащить xlsx на PDF-таб (drag&drop обходит accept) | Browser не блокирует drag&drop строго | Добавить frontend-валидацию в `onDrop`: если `grandInputMode === 'pdf'` и файл не `application/pdf` → показать ошибку "Ожидается PDF-файл" |
| F3 | Задача отправляется во время переключения таба | Race condition: submitting=true, пользователь кликает таб | Кнопки табов отключены когда `submitting=true` |

---

## Что НЕ меняется

- Модели БД, миграции — не нужны
- API роутер `/tasks` — уже принимает PDF
- `generate_list()` — один и тот же экспортёр
- Логика cancel/resume/partial — копируется из xlsx-ветки
- Задача `CHECK_LIST_COMPLETENESS` — работает поверх результата, не зависит от источника

---

## Фазы

### Фаза 1: OCR-инфраструктура (бэкенд, нет изменений логики)

**Файлы:** `backend/Dockerfile`, `backend/requirements.txt`, новый `backend/app/utils/pdf_ocr_extractor.py`

#### 1.1 Dockerfile — добавить Tesseract

```dockerfile
RUN apt-get update && apt-get install -y \
    gcc g++ libpango-1.0-0 libpangoft2-1.0-0 libcairo2 \
    libgdk-pixbuf-2.0-0 libffi-dev shared-mime-info \
    fonts-dejavu-core \
    tesseract-ocr tesseract-ocr-rus \      ← добавить
    && rm -rf /var/lib/apt/lists/*
```

#### 1.2 requirements.txt — добавить

```
pytesseract>=0.3.13
Pillow>=10.0.0
```

#### 1.3 Новый файл `backend/app/utils/pdf_ocr_extractor.py`

Функция `extract_pdf_with_ocr(pdf_bytes: bytes) -> list[dict]`:

```
Защиты (из edge case анализа):
- A1: после open → if len(doc) == 0 → raise ValueError
- A2: if doc.needs_pass → raise ValueError с понятным сообщением
- A3: весь open в try/except fitz.FileDataError → raise ValueError
- A4: if len(doc) > 150 → raise ValueError
- B2: страницы обрабатываются ПООЧЕРЁДНО, pixmap не аккумулируется
- B3: pix.pil_image() вместо pix.tobytes("png") → PIL Image напрямую
- B1: dpi=200 (не 300); если page.rect.width > 2480 → масштаб чтобы width ≤ 2480
- D1: embedded-текст валидируется по доле кириллицы: если word_count≥30 но кириллица<10% → OCR
- C1: pytesseract import в try → TesseractNotFoundError → clear ValueError
- C3: pytesseract.image_to_string(timeout=30)
- C6: if timeout exception → page text = "" + logger.warning
```

Логика для каждой страницы:
```python
text = page.get_text().strip()
words = text.split()
cyrillic_ratio = sum(1 for c in text if 'Ѐ' <= c <= 'ӿ') / max(len(text), 1)

if len(words) >= 30 and cyrillic_ratio >= 0.10:
    # embedded текст достаточного качества (D1)
    return {"page": N, "text": text, "method": "embedded"}
else:
    # скан или плохая кодировка → OCR (B1, B2, B3)
    matrix = fitz.Matrix(scale, scale)  # scale из DPI и ограничения ширины
    pix = page.get_pixmap(matrix=matrix)
    img = pix.pil_image()               # B3: без PNG round-trip
    pix = None                          # B2: освобождаем
    try:
        ocr_text = pytesseract.image_to_string(img, lang="rus+eng", timeout=30)
    except RuntimeError:                # C6: timeout
        logger.warning("OCR timeout", page=N)
        ocr_text = ""
    return {"page": N, "text": ocr_text.strip(), "method": "ocr"}
```

Вспомогательная функция `chunk_pdf_pages(pages: list[dict], pages_per_chunk: int = 8) -> list[str]`:
- Группирует страницы по N штук (8 страниц, не 6 — для меньшего числа Claude-запросов)
- Каждая группа → строка с разделителями `--- Страница N (метод: embedded/ocr) ---`
- **C4**: пропускать страницы с text < 20 символов после strip
- Возвращает только непустые чанки (суммарный текст чанка > 50 символов)

**Gates Phase 1:**
- [x] `python -m py_compile backend/app/utils/pdf_ocr_extractor.py`
- [x] `pytest backend/tests/ -q` (существующие тесты зелёные — ошибка ModuleNotFoundError для fitz была до этой фазы, не регрессия)

---

### Фаза 2: Адаптация обработчика LIST_FROM_GRAND (бэкенд)

**Файлы:** `backend/app/services/task_processor.py`

#### 2.1 Новый промпт `PROMPT_LIST_FROM_GRAND_PDF`

Размещается рядом с `PROMPT_LIST_FROM_GRAND`. Отличия:
- Объясняет Claude, что входные данные — OCR-текст гранд-сметы (возможны артефакты распознавания)
- Говорит игнорировать строки цен/итогов/коэффициентов (Итого, НДС, Всего и т.д.)
- Акцент на извлечении колонок: наименование, ед. изм., количество
- Коды расценок (ТЕР, ФЕР, ГЭСН, ТЕРр) — пропускать как отдельную позицию, включать только если это часть наименования
- Выходной JSON — идентичен `PROMPT_LIST_FROM_GRAND`

```python
PROMPT_LIST_FROM_GRAND_PDF = """Ты — опытный инженер-сметчик.

Тебе передан текст, распознанный из PDF-скана гранд-сметы. Текст может содержать артефакты OCR (лишние символы, разрывы строк). Восстанавливай смысл по контексту.

Задача: извлечь все позиции — работы и материалы — точно как в документе. Ничего не добавляй.

ПРОПУСКАЙ строки: итого, всего, НДС, сметная прибыль, накладные расходы, коэффициенты, шифры расценок (ТЕР-xx-xx, ФЕРр-xx и т.д.) если они стоят отдельной строкой без наименования работы.

ПОРЯДОК: Работа → её Материалы.

Верни ТОЛЬКО валидный JSON (первый символ {, последний }):
{
  "items": [
    {
      "type": "Работа" | "Материал",
      "name": "Наименование",
      "unit": "Ед. изм.",
      "quantity": число или null,
      "notes": ""
    }
  ]
}"""
```

#### 2.2 Изменение `_handle_list_from_grand()`

В начале функции добавляется разветвление с защитой E2:

```python
excel_bytes: Optional[bytes] = None
pdf_bytes: Optional[bytes] = None

for f in await self._load_input_files(task):
    mime = f.get("mime_type", "")
    if "spreadsheet" in mime or "excel" in mime or mime == _XLSX_MIME:
        excel_bytes = base64.b64decode(f["content_b64"])
    elif mime == "application/pdf":
        pdf_bytes = base64.b64decode(f["content_b64"])

# E2: запретить оба одновременно
if excel_bytes and pdf_bytes:
    raise ValueError("Загрузите один файл: либо .xlsx, либо .pdf, но не оба сразу")

if excel_bytes:
    await self._handle_list_from_grand_xlsx(task, excel_bytes)
elif pdf_bytes:
    await self._handle_list_from_grand_pdf(task, pdf_bytes)
else:
    raise ValueError("Не найден файл (.xlsx или .pdf) во вложениях задачи")
```

Существующий код переезжает в `_handle_list_from_grand_xlsx()` без изменений.

Новый метод `_handle_list_from_grand_pdf()`:

```
Последовательность:
1. update_progress("Анализ PDF гранд-сметы...")
2. extract_pdf_with_ocr(pdf_bytes)            ← A1-A4, C1 обрабатываются внутри
3. A5: if len(doc) > 50 → update_progress(warn)
4. chunk_pdf_pages(pages) → chunks            ← C4 пропускает пустые страницы
5. if not chunks → raise ValueError("Не удалось извлечь текст из PDF...")  ← E1 early
6. Цикл по chunks (идентично xlsx-ветке):
   - _check_cancelled()
   - update_progress(f"Обрабатывается часть {i+1} из {total}...")
   - _call_claude_json_with_retry(chunk_text, PROMPT_LIST_FROM_GRAND_PDF)
   - accumulated_items.extend(items)
   - _save_progress_data(chunks_done=i+1, items=accumulated_items, ...)
   - при отмене: save partial + raise TaskCancelledError
   - при Claude error: save partial, continue
7. E1: if not accumulated_items → raise ValueError("Не удалось извлечь позиции...")
8. generate_list(accumulated_items) → xlsx → save_result
```

**resume-логика (E3 — ИСПРАВЛЕНО 2026-05-10):** OCR теперь запускается в `asyncio.to_thread()` (не блокирует event loop → Render не перезапускает инстанс). После завершения OCR результат сохраняется в `progress_data["ocr_pages"]`. При повторном запуске (после рестарта) — OCR пропускается, берутся сохранённые страницы.

**Gates Phase 2:**
- [x] `python -m py_compile backend/app/services/task_processor.py`
- [x] `pytest backend/tests/ -q` (ошибка ModuleNotFoundError для fitz — pre-existing, не регрессия)
- [ ] Ручной тест: создать задачу LIST_FROM_GRAND с PDF-файлом, убедиться что задача проходит в completed

---

### Фаза 3: Фронтенд — два таба в форме создания задачи

**Файлы:** `frontend/src/pages/TaskCreate.tsx`

#### 3.1 Новый стейт

```tsx
const [grandInputMode, setGrandInputMode] = useState<'excel' | 'pdf'>('excel');
```

Сброс при смене `taskType`:
```tsx
useEffect(() => {
  setGrandInputMode('excel');
  setFiles([]);
}, [taskType]);
```

#### 3.2 UI — табы под заголовком задачи

Только если `taskType === 'LIST_FROM_GRAND'`:

```tsx
{taskType === 'LIST_FROM_GRAND' && (
  <div className="grand-input-tabs">
    <button
      className={grandInputMode === 'excel' ? 'active' : ''}
      onClick={() => { setGrandInputMode('excel'); setFiles([]); }}
    >
      Excel (.xlsx)
    </button>
    <button
      className={grandInputMode === 'pdf' ? 'active' : ''}
      onClick={() => { setGrandInputMode('pdf'); setFiles([]); }}
    >
      PDF-скан
    </button>
  </div>
)}
```

#### 3.3 Доработка FileUpload: prop `onValidateFile` (F2)

**Проблема**: `FileUpload` использует хардкоженный `ACCEPTED_EXTENSIONS` в `validateAndAdd()`. Prop `accept` передаётся только в `<input>`, drag-and-drop его игнорирует. Нужно добавить callback для кастомной валидации.

**Изменение `FileUpload.tsx`:**
```tsx
interface FileUploadProps {
  // ... существующие пропы ...
  onValidateFile?: (file: File) => string | null  // null = ок, string = текст ошибки
  hint?: string
}
```

В `validateAndAdd()` после существующих проверок:
```tsx
if (onValidateFile) {
  const customError = onValidateFile(file)
  if (customError) {
    validationErrors.push(`«${file.name}»: ${customError}`)
    return
  }
}
```

#### 3.4 FileUpload — условный accept + drag-and-drop валидация (F2)

```tsx
{taskType === 'LIST_FROM_GRAND'
  ? <FileUpload
      accept={grandInputMode === 'excel' ? '.xlsx,.xls' : '.pdf'}
      maxFiles={1}
      hint={grandInputMode === 'pdf'
        ? 'Скан или цифровой PDF гранд-сметы'
        : 'Excel-файл гранд-сметы (.xlsx)'}
      onValidateFile={(file) => {
        // F2: защита от drag-and-drop обхода accept
        if (grandInputMode === 'pdf' && file.type !== 'application/pdf')
          return 'Ожидается PDF-файл'
        if (grandInputMode === 'excel' && !file.name.match(/\.(xlsx|xls)$/i))
          return 'Ожидается Excel-файл (.xlsx)'
        return null
      }}
      ...
    />
  : <FileUpload ... />
}
```

#### 3.4 Кнопки табов блокируются при отправке (F3)

```tsx
<button
  disabled={submitting}  // F3: нельзя переключить таб во время submit
  onClick={() => { setGrandInputMode('excel'); setFiles([]); }}
>
```

#### 3.5 Стили — использование существующих классов переключателей

Табы оформляются в стиле существующих переключателей (`inputMode` / `projectMode`). Новых CSS-классов минимум.

**Gates Phase 3:**
- [x] `cd frontend && npx tsc --noEmit` (0 ошибок типов)
- [x] `cd frontend && npm run lint` (скрипт отсутствует в проекте — не применимо)
- [ ] Визуальная проверка: таб «Excel» → FileUpload принимает только .xlsx; таб «PDF-скан» → принимает только .pdf
- [ ] Drag-and-drop .xlsx на PDF-таб → показывает ошибку "Ожидается PDF-файл"
- [ ] Таб заблокирован во время submitting

---

## Challenge Log

### 1. Решает ли план задачу?

Да. Пользователь сможет загрузить PDF (скан или цифровой), получить xlsx-результат — те же работы и материалы что при xlsx-пути.

### 2. Самое эффективное решение?

Альтернативы рассмотрены:
- **Claude Vision** — дороже (vision-токены), уже используется для чертежей. Пользователь выбрал Tesseract.
- **Cloud Vision API** — внешний сервис, новый ключ, стоимость. Избыточно.
- **Новый тип задачи LIST_FROM_GRAND_PDF** — дублирование кода, лишняя карточка в меню. Лучше расширить существующую.

**Выбранный подход**: Hybrid OCR (PyMuPDF + Tesseract) внутри существующего типа задачи — минимум новых зависимостей, знакомая пользователю точка входа.

### 3. Нет «кода ради кода»?

- Не создаём новый тип задачи.
- Не рефакторим `_handle_list_from_grand()` целиком — только выносим xlsx-логику в `_handle_list_from_grand_xlsx()`.
- Не меняем БД, роутер, `generate_list()`.

---

## Итог

- [x] Research написан
- [x] Plan написан
- [x] Фаза 1 реализована
- [x] Фаза 2 реализована
- [x] Фаза 3 реализована
- [x] Hotfix: OCR→asyncio.to_thread + кэш ocr_pages в progress_data (2026-05-10)
- [ ] Ручное тестирование пройдено (post-deploy)
