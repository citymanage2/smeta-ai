# OCR-чекпоинт возобновляем — убрать бесконечный цикл перезапуска

## Проблема

Задача `LIST_FROM_GRAND` (PDF-скан) распознаётся Tesseract'ом постранично. После каждой
страницы прогресс пишется в `progress_data["ocr_pages_partial"]`
([task_processor.py](../backend/app/services/task_processor.py) `_handle_list_from_grand_pdf`),
чтобы после рестарта инстанса продолжить с нужной страницы.

Но предикат «есть чекпоинт» нигде не признаёт OCR-прогресс — он смотрит только на
`chunks_done` и `_stage ∈ {pre_excel, claude_partial}`:

- бэк: `resume_task` в [tasks.py](../backend/app/routers/tasks.py) (has_checkpoint)
- поллер: `_has_checkpoint` в [resume_poller.py](../backend/app/services/resume_poller.py)
- фронт: `hasResumeCheckpoint` в [TaskStatus.tsx](../frontend/src/pages/TaskStatus.tsx)

Во время OCR в `progress_data` есть только `ocr_pages_partial`. Итог: на фронте видна
**только** кнопка «Перезапустить», которая обнуляет `progress_data` → OCR стартует с 1-й
страницы → инстанс снова падает на ~4-й → бесконечный цикл. Сделанный по-страничный
чекпоинт — мёртвый груз.

## Решение

Научить единый предикат видеть OCR-чекпоинт (`ocr_pages_partial` / `ocr_pages`), чтобы
появлялась кнопка «Продолжить», продолжающая OCR с последней страницы. Прогресс
накапливается между падениями → задача доходит до конца даже при повторных рестартах.

Это НЕ устраняет первопричину рестартов (вероятный OOM Tesseract на слабом инстансе Render,
слой 1) — только разрывает цикл (слой 2). Слой 1 — отдельная инфра-задача.

## Фазы

### [x] Фаза 1 — единый предикат на бэке
- Новый модуль `backend/app/services/checkpoint.py`: `RESUMABLE_STAGES` +
  `has_resumable_checkpoint(progress_data)` — распознаёт `chunks_done`, `ocr_pages_partial`,
  `ocr_pages`, `_stage ∈ RESUMABLE_STAGES`.
- `resume_poller.py`: использовать общий предикат (сохранить алиас `_has_checkpoint` для тестов).
- `tasks.py` `resume_task`: заменить inline-предикат на общий.

### [x] Фаза 2 — фронт: кнопка «Продолжить» для OCR
- `TaskStatus.tsx`: `hasResumeCheckpoint` признаёт `ocr_pages_partial`/`ocr_pages`.
- Добавить ветку рендера OCR-резюма (сообщение «Распознано N стр., продолжим с последней»).

### [x] Фаза 3 — тесты
- `test_resume_poller.py`: добавить OCR-варианты в `test_has_checkpoint_variants`.
- Фронт: тест видимости resume-кнопки при OCR-чекпоинте.

### [x] Фаза 4 — слой 1: снизить пик памяти OCR (без потери точности)
- `pdf_ocr_extractor.py`: рендер страницы в grayscale (`csGRAY`) вместо RGB — 1 байт/пиксель
  вместо 3, память под pixmap и вход Tesseract втрое меньше. Точность не страдает: Tesseract
  бинаризует изображение внутри. DPI 150 не трогаем (ниже — риск для цифр в смете).
- Рендер вынесен в тестируемый хелпер `_render_page_image`.
- Лёгкий лог `peak_rss_mb` вокруг OCR (`resource.getrusage`, stdlib) — чтобы при повторных
  рестартах подтвердить/опровергнуть OOM без доступа к метрикам Render.
- Тесты `test_pdf_ocr_extractor.py`: grayscale-рендер, cap ширины, хелпер RSS (без tesseract).

### [x] Фаза 5 — диагностика по логам Render + фикс потери текста при таймауте
Логи после деплоя grayscale (через `render` CLI) подтвердили диагноз:
- Инстанс `smeta-ai-backend` на плане **starter = 512 МБ / 0.5 CPU**.
- `peak_rss_mb` в OCR: 371 → 423 → **479 МБ** (94% от 512). Незапланированный рестарт
  посреди OCR (без деплоя) = **OOM-kill**. Первопричина подтверждена.
- Дважды `ocr_timeout` (0.5 CPU): Tesseract не укладывался в 30с → страница возвращала
  пустой текст → позиции **молча терялись** (неполная смета — финансовый риск).

Действия:
- **Инфра (за пользователем):** апгрейд плана Render starter→standard (2 ГБ / 1 CPU) —
  убирает и OOM, и CPU-таймауты. Решение по биллингу.
- **Код (сделано):** `_ocr_page` таймаут 30→60с; таймаут-страницы помечаются
  `ocr_timeout=True` (хелпер `timed_out_page_numbers`); хендлер `_handle_list_from_grand_pdf`
  выдаёт явное предупреждение с номерами нераспознанных страниц вместо тихой потери.
- Тесты: `timed_out_page_numbers` (локально) + тег таймаута в `_ocr_page` (под importorskip).

## Итог

Реализовано целиком (код). Слой 2 (бесконечный цикл) устранён — кнопка «Продолжить».
Слой 1: пик памяти OCR срезан втрое (grayscale), причина падений подтверждена по логам —
**OOM на 512 МБ**; настоящее решение — апгрейд плана Render (инфра, за пользователем).
Дополнительно закрыт корректностный баг: таймаут OCR больше не теряет текст молча.
