# Перечень из проекта (LIST_FROM_PROJECT)

## Контекст

Новая двухэтапная задача, зеркалящая архитектуру `LIST_FROM_GRAND` + `CHECK_LIST_COMPLETENESS`.

**Шаг 1 — `LIST_FROM_PROJECT`**: пользователь загружает PDF проектной документации (ПД/РД/ТЗ).
Claude читает документ как document block (нативная поддержка в API уже есть), извлекает все
работы и материалы строго по проекту, рассчитывает объёмы из чертежей там, где они не указаны явно.
Результат — Excel в том же формате, что и `LIST_FROM_GRAND`.

**Шаг 2 — `CHECK_PROJECT_COMPLETENESS`**: запускается кнопкой на странице задачи после завершения
Шага 1. Проверяет полноту материалов к каждой работе по нормативной базе ГЭСН/ФСНБ-2022,
добавляет недостающие, корректирует объёмы. Логика идентична существующему `CHECK_LIST_COMPLETENESS`.

**Ключевые отличия от LIST_FROM_GRAND:**
- Вход: PDF (не Excel), передаётся Claude нативно как document block — чанкинг не нужен
- Задача одним запросом (без resume), нет `progress_data.chunks_done`
- `progress_data.items` сохраняется так же — для использования Шагом 2

---

## Промпт Шага 1 — PROMPT_LIST_FROM_PROJECT (утверждён)

```
Ты — опытный инженер-сметчик и специалист по чтению проектной
документации.

Задача: составить перечень работ и материалов СТРОГО на основании
проектной документации. Ничего не добавляй от себя по нормативам —
только то, что следует из проекта.

═══════════════════════════════════════════════
ЧТО ИЗВЛЕКАТЬ
═══════════════════════════════════════════════

1. Все виды работ — из спецификаций, ведомостей, пояснительной записки,
   а также логически следующие из состава проекта (демонтаж, подготовка
   основания, подключение и т.п.), если они явно подразумеваются.
2. Все материалы к каждой работе — из спецификаций и ведомостей.

ПОРЯДОК СТРОК — строго:
  Работа 1
    Материал 1 к Работе 1
    Материал 2 к Работе 1
  Работа 2
    ...

РАЗДЕЛЫ: если есть явные разделы (АР, КР, ОВиК, ЭОМ, ВК и т.п.)
— указывай раздел в поле notes каждой позиции.

═══════════════════════════════════════════════
ОБЪЁМЫ — ВАЖНО
═══════════════════════════════════════════════

Для каждой позиции определяй объём по приоритету:
  1. Явно указан в спецификации / ведомости → используй как есть
  2. Не указан, но можно определить по чертежам / схемам / планам
     (площадь, длина, количество элементов и т.п.) → рассчитай
     и укажи в quantity, в notes добавь: "Объём определён по чертежу: [как]"
  3. Определить невозможно → null

═══════════════════════════════════════════════
ФОРМАТ ОТВЕТА
═══════════════════════════════════════════════

Верни результат СТРОГО в формате JSON, без markdown блоков,
без preamble текста, первый символ {, последний }:
{
  "items": [
    {
      "type": "Работа" | "Материал",
      "name": "Наименование",
      "unit": "Ед. изм. или пустая строка",
      "quantity": число или null,
      "notes": "Раздел документа / обоснование объёма"
    }
  ]
}

ВАЖНО: отвечай ТОЛЬКО валидным JSON. Никакого текста до { или после }.
```

---

## Промпт Шага 2 — PROMPT_CHECK_PROJECT_COMPLETENESS (утверждён)

*(Идентичен существующему `PROMPT_CHECK_COMPLETENESS`, источник — `LIST_FROM_PROJECT` вместо `LIST_FROM_GRAND`)*

```
Ты — опытный инженер-сметчик со знанием нормативной базы РФ
(ГЭСН/ФСНБ-2022, ФЕР/ТЕР Свердловской области, СП, ГОСТ).

Задача: проверить полноту учтённых материалов для каждой работы
в перечне, дополнить недостающие по нормативам.

Тебе передан готовый перечень работ и материалов из проектной
документации. Для каждой работы:

1. Проверь состав материалов по нормативной базе (в порядке
   приоритета):
   — ГЭСН / ФСНБ-2022 — нормы расхода материалов
   — Технические части сборников ГЭСН — что входит в норму,
     что учитывается отдельно
   — ФЕР/ТЕР Свердловской области — региональная специфика
   — СП и ГОСТ — для нестандартных решений

2. Если нормативно необходимый материал отсутствует — добавь его
3. Если объём материала не указан или некорректен — скорректируй
   по норме ГЭСН исходя из объёма работ
4. Если позиция корректна — оставь без изменений

В поле notes для каждой изменённой / добавленной позиции:
  "Добавлено по ГЭСН XX-XX-XXX: [обоснование]"
  "Объём скорректирован: в перечне [X] [ед], по норме ГЭСН [норма]"
  "Соответствует норме" — если позиция корректна

После проверки добавь поле "changes_summary" — текст с перечнем
всех добавленных и скорректированных позиций.

Верни результат СТРОГО в формате JSON, без markdown блоков,
без preamble текста, первый символ {, последний }:
{
  "items": [
    {
      "type": "Работа" | "Материал",
      "name": "Наименование",
      "unit": "Ед. изм.",
      "quantity": число или null,
      "notes": "Обоснование"
    }
  ],
  "changes_summary": "Краткое резюме всех изменений"
}

ВАЖНО: отвечай ТОЛЬКО валидным JSON. Никакого текста до { или после }.
```

---

## Фазы реализации

### Фаза 1 — Backend: LIST_FROM_PROJECT [x]

**Файлы:** `backend/app/constants.py`, `backend/app/services/task_processor.py`

**`constants.py`:**
- Добавить `"LIST_FROM_PROJECT": "Перечень из проекта"` в `TASK_TYPE_LABELS`

**`task_processor.py`:**
- Добавить константу `PROMPT_LIST_FROM_PROJECT` (промпт Шага 1, утверждённый выше)
- Написать метод `_handle_list_from_project(self, task: Task) -> None`:
  1. Найти PDF в `task.input_file_data` по `mime_type == "application/pdf"`
  2. Если PDF не найден — `raise ValueError("PDF-файл не найден во вложениях задачи")`
  3. Декодировать из base64 → `pdf_to_content_block(data)` → получить document block
  4. `await self.update_progress("Анализ проектной документации...")`
  5. Передать в `_call_claude_json`:
     - `messages = [{"role": "user", "content": PROMPT_LIST_FROM_PROJECT}]`
     - `image_data = [pdf_content_block]`  ← document block передаётся через image_data
     - `system_prompt = SYSTEM_BASE`
  6. `items = data.get("items", [])`
  7. Если items пустой — `raise ValueError("Claude не вернул ни одной позиции. Проверьте содержимое PDF.")`
  8. `await self._save_progress_data({"items": items})` — сохраняем для Шага 2
  9. `await self.update_progress(f"Найдено {len(items)} позиций. Формирование Excel...")`
  10. `excel_data = generate_list(items)`
  11. `await self.save_result("Перечень_из_проекта.xlsx", _XLSX_MIME, excel_data)`
- В методе `process()` добавить роутинг: `elif task_type == "LIST_FROM_PROJECT": await self._handle_list_from_project(task)`

---

### Фаза 2 — Backend: CHECK_PROJECT_COMPLETENESS + endpoint [x]

**Файлы:** `backend/app/constants.py`, `backend/app/services/task_processor.py`, `backend/app/routers/tasks.py`

**`constants.py`:**
- Добавить `"CHECK_PROJECT_COMPLETENESS": "Проверка полноты (по проекту)"` в `TASK_TYPE_LABELS`

**`task_processor.py`:**
- Добавить константу `PROMPT_CHECK_PROJECT_COMPLETENESS` (промпт Шага 2, утверждённый выше)
- Написать метод `_handle_check_project_completeness(self, task: Task) -> None`:
  - Логика идентична `_handle_check_completeness`, одно отличие:
    - Проверять `source_task.task_type.upper() != "LIST_FROM_PROJECT"` (вместо `LIST_FROM_GRAND`)
    - Использовать `PROMPT_CHECK_PROJECT_COMPLETENESS` (вместо `PROMPT_CHECK_COMPLETENESS`)
  - Использует те же `_chunk_by_work_boundaries` и `generate_list(..., changes_summary=...)`
  - Сохраняет результат: `"Проверка_полноты_по_проекту.xlsx"`
- В методе `process()` добавить: `elif task_type == "CHECK_PROJECT_COMPLETENESS": await self._handle_check_project_completeness(task)`

**`routers/tasks.py`:**
- Добавить endpoint `POST /tasks/check-project-completeness`:
  - Аналогичен существующему `POST /tasks/check-completeness`
  - Принимает `{ "source_task_id": "uuid" }`
  - Проверяет: source-задача существует, тип `LIST_FROM_PROJECT`, статус `completed`
  - Создаёт задачу `CHECK_PROJECT_COMPLETENESS`, записывает `source_task_id` в `user_prompt`
  - Наследует `project_id` из source-задачи
  - Запускает в background, возвращает `task_id`

---

### Фаза 3 — Frontend [x]

**Файлы:** `frontend/src/types/index.ts`, `frontend/src/components/TaskTypeSelector.tsx`, `frontend/src/api/tasks.ts`, `frontend/src/pages/TaskStatus.tsx`

**`types/index.ts`:**
- Добавить в `TASK_TYPE_LABELS`:
  - `LIST_FROM_PROJECT: 'Перечень из проекта'`
  - `CHECK_PROJECT_COMPLETENESS: 'Проверка полноты (по проекту)'`

**`TaskTypeSelector.tsx`:**
- Добавить `'LIST_FROM_PROJECT'` в массив `TASK_TYPES`

**`api/tasks.ts`:**
- Добавить функцию `checkProjectCompleteness(sourceTaskId: string)`:
  - `POST /tasks/check-project-completeness` с `{ source_task_id: sourceTaskId }`
  - Возвращает `{ task_id: string }`

**`TaskStatus.tsx`:**
- При статусе `completed` + тип `LIST_FROM_PROJECT`:
  - Показать карточку «Хотите проверить полноту материалов по ГЭСН?»
  - Кнопка «Да, проверить» → `checkProjectCompleteness(taskId)` → сохранить `checkTaskId` в state
  - Прогресс и результат CHECK_PROJECT_COMPLETENESS отображаются прямо на этой же странице
  - Поведение идентично существующей логике для `LIST_FROM_GRAND` / `CHECK_LIST_COMPLETENESS`

---

## Итог

| Что | Статус |
|---|---|
| Промпт Шага 1 (LIST_FROM_PROJECT) | утверждён |
| Промпт Шага 2 (CHECK_PROJECT_COMPLETENESS) | утверждён |
| Архитектура двухэтапности | утверждена |
| Фаза 1: бэкенд LIST_FROM_PROJECT | [x] |
| Фаза 2: бэкенд CHECK_PROJECT_COMPLETENESS + endpoint | [x] |
| Фаза 3: фронтенд | [x] |
