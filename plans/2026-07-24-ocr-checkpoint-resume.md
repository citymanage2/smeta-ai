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

## Итог

Реализовано целиком (слой 2). Первопричина рестартов (слой 1, OOM OCR) — не входит в этот
план, отслеживается отдельно.
