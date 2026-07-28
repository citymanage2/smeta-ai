# План: продолжение задач с чекпоинта + пауза при исчерпании баланса API

**Дата:** 2026-07-21
**Статус:** реализован полностью (Фазы 1, 2, 2б, 3, 4, 5 + baseline-починка тестов)
**Тип:** новая функция (Standard / M)
**Ветка:** `feature/resume-and-balance-pause`

---

## 1. Проблема

Две связанные проблемы:

1. **Рестарт вместо продолжения.** При любой остановке задачи (ошибка, обрыв,
   рестарт сервера) пользователю в большинстве случаев предлагают только
   «↺ Перезапустить» — задача запускается **с нуля**, повторно тратя токены,
   хотя чекпоинт мог быть сохранён. Кнопка «▶ Продолжить» (с точки прерывания)
   показывается лишь в двух узких случаях.
2. **Исчерпание баланса = ошибка.** Когда у Anthropic API кончаются деньги,
   задача уходит в `failed`. После пополнения счёта нужно вручную искать и
   перезапускать каждую задачу. Требование: задача должна уходить **на паузу**
   и после пополнения счёта **продолжаться автоматически** с места остановки.

## 2. Цель и критерии приёмки

- [x] **КП-1.** Для любой упавшей/остановленной задачи, у которой в
  `progress_data` есть чекпоинт (`chunks_done` или `_stage`), на фронте
  показывается основная кнопка «▶ Продолжить» (resume с чекпоинта) и
  второстепенная «↺ Перезапустить с начала». Сейчас это работает только для
  `ESTIMATE_FROM_LIST(pre_excel)` и `LIST_FROM_GRAND`.
- [x] **КП-2.** Типы `CHECK_LIST_COMPLETENESS` и `CHECK_PROJECT_COMPLETENESS`
  (уже resumable на бэкенде) получают рабочую кнопку «Продолжить».
- [x] **КП-3.** `LIST_FROM_PROJECT` пишет по-чанковый чекпоинт и продолжается с
  него (добавлен в `RESUMABLE_TYPES`).
- [x] **КП-3б (приоритет).** `ESTIMATE_FROM_LIST` пишет промежуточный чекпоинт
  внутри шага 2 (`claude_partial`, после каждой группы чанков); при обрыве/паузе
  в шаге 2 resume продолжает только по необсчитанным позициям — уже посчитанные
  в Claude повторно не отправляются. (fast/sync; для batch устойчивость уже есть.)
- [x] **КП-4.** При исчерпании баланса Anthropic задача переходит в статус
  `paused` (не `failed`), сохранив чекпоинт; текст объясняет причину.
- [x] **КП-5.** Планировщик каждые 10 минут автоматически пытается продолжить
  `paused`-задачи; при успехе (баланс пополнен) расчёт идёт дальше с чекпоинта,
  при неудаче задача тихо остаётся `paused`.
- [x] **КП-6.** На странице задачи `paused` показывается как «⏸ На паузе» с
  пояснением и ручной кнопкой «Продолжить сейчас».
- [x] **КП-7.** Рестарт сервера не ломает `paused`-задачи; поллер подхватывает
  их после старта. (`_recover_stuck_tasks` трогает только `processing`; при
  старте — немедленный проход `resume_paused_tasks`.)

## 3. Контекст (карта кода)

### Бэкенд
- Диспетчер обработки: `TaskProcessor.process()` —
  [task_processor.py:833](backend/app/services/task_processor.py#L833).
  Единственная точка перевода в `failed`: `except Exception` →
  `update_status("failed", ...)` (строки 878–885).
- Сигнал баланса: `claude_service.py:330–335` — при 4xx с подстрокой
  `"credit balance"` бросается `RuntimeError("Баланс API Anthropic меньше 0…")`.
- «Просачивание» баланса без ретраев: `task_processor.py` строки 772, 816, 837,
  1837 (проверки `"credit balance"`/`"баланс api"`).
- Чекпоинты `_save_progress_data` — [task_processor.py:533](backend/app/services/task_processor.py#L533).
- Покрытие чекпоинтами по хендлерам:
  | Тип | Чекпоинт | Resumable (бэкенд) | Кнопка на фронте |
  |---|---|---|---|
  | `LIST_FROM_GRAND` (xlsx+pdf) | `chunks_done` | да | ✅ есть |
  | `CHECK_LIST_COMPLETENESS` | `chunks_done` | да | ❌ нет |
  | `CHECK_PROJECT_COMPLETENESS` | `chunks_done` | да | ❌ нет |
  | `ESTIMATE_FROM_LIST` | `_stage="pre_excel"` **только после всего шага 2** | частично | ✅ есть, но не спасает при обрыве в шаге 2 |
  | `LIST_FROM_PROJECT` | только `items` в конце (1461) | нет | ❌ только restart |
  | `ESTIMATE_OPTIMIZATION` | `partial_results` | нет (в /resume) | ❌ только restart |
- Resume-эндпоинт: `resume_task` — [tasks.py:626](backend/app/routers/tasks.py#L626).
  `RESUMABLE_TYPES` (строка 649), проверка чекпоинта (657), сброс в `pending`
  без очистки `progress_data`. Разрешён только из `failed`/`cancelled` (643).
- Restart-эндпоинт: `restart_task` — [tasks.py:675](backend/app/routers/tasks.py#L675),
  очищает `progress_data=None`.
- Запуск в фоне: `_run_task_in_background` — [tasks.py:163](backend/app/routers/tasks.py#L163).
- Планировщик: `AsyncIOScheduler` — [main.py:41](backend/app/main.py#L41),
  `scheduler.add_job(..., "interval", ...)` (137).
- Восстановление после рестарта: `_recover_stuck_tasks` —
  [main.py:92](backend/app/main.py#L92), трогает только `processing`.

### Фронтенд
- Статусы: `TaskStatus` тип + подписи —
  [types/index.ts:3](frontend/src/types/index.ts#L3), [:140](frontend/src/types/index.ts#L140).
- Цвета бейджей: `STATUS_COLORS` — [TaskStatus.tsx:34](frontend/src/pages/TaskStatus.tsx#L34).
- Условия кнопок resume/restart — [TaskStatus.tsx:905–1024](frontend/src/pages/TaskStatus.tsx#L905-L1024).
- Поллинг статуса — [TaskStatus.tsx:270](frontend/src/pages/TaskStatus.tsx#L270) (3 c),
  глобальный поллер — [useGlobalTaskPoller.ts:11](frontend/src/hooks/useGlobalTaskPoller.ts#L11) (5 c).
- Форматтер ошибок — [utils/formatError.ts](frontend/src/utils/formatError.ts).

## 4. Решение

### Слой 1 — «Продолжить» везде, где есть чекпоинт (фронтенд)
Заменить жёсткие условия на [TaskStatus.tsx:905/946] на общее правило:
если `resumableTypes.includes(task.task_type)` **и** есть чекпоинт
(`progress_data.chunks_done != null || progress_data._stage`), показывать
основную «▶ Продолжить» + «↺ Перезапустить с начала». Иначе — только restart.
Бэкенд для `CHECK_*` уже поддерживает resume — правится только UI.

### Слой 2 — добавить/усилить чекпоинты (бэкенд)
- **`ESTIMATE_FROM_LIST` (приоритет — самая дорогая задача).** Сейчас чекпоинт
  `pre_excel` пишется только ПОСЛЕ всего шага 2 ([task_processor.py:1954]); если
  баланс кончился в цикле Claude ([1884–1946]) — весь `claude_results` теряется,
  resume гоняет Claude заново. Добавить **промежуточный чекпоинт внутри шага 2**:
  - На входе в шаг 2 подгружать `claude_results` из `progress_data`.
  - Перед отправкой чанка отбрасывать позиции с `_id`, уже присутствующими в
    `claude_results` (повторно в Claude не шлём).
  - После каждого чанка сохранять `{_stage: "claude_partial", items, matched,
    claude_results}` отдельной сессией (как `pre_excel`).
  - Resume при `_stage == "claude_partial"`: восстановить `items`/`matched`/
    `claude_results`, продолжить шаг 2 по оставшимся позициям, затем шаг 3.
    Шаги 0–1 при этом прогоняются заново (дёшево, без Claude).
- `_handle_list_from_project` ([task_processor.py:1306]): переписать цикл по
  чанкам по образцу `_handle_check_completeness` — `start_chunk`,
  `_save_progress_data({"chunks_done": i+1, "items": ...})` после каждого чанка.
  Добавить `LIST_FROM_PROJECT` в `RESUMABLE_TYPES`.
- `ESTIMATE_OPTIMIZATION`: имеет `partial_results`, но не в `/resume`. Вынести
  отдельной подзадачей — оценить объём, при простоте включить, иначе оставить
  на restart (не блокирует КП).

### Слой 3 — пауза при исчерпании баланса + автовозобновление (бэкенд+фронт)
- Ввести класс `InsufficientBalanceError(RuntimeError)` в `claude_service.py`,
  бросать его вместо голого `RuntimeError` (330–335). Заменить строковые
  проверки в `task_processor.py` (772/816/837/1837) на `except
  InsufficientBalanceError`/`isinstance`.
- В `process()` (878) ловить `InsufficientBalanceError` **отдельно** →
  `update_status("paused", error="Баланс API исчерпан. Задача продолжится
  автоматически после пополнения.")`. Чекпоинт к этому моменту уже сохранён.
- Новый планировщик-джоб `resume_paused_tasks` (main.py, interval=10 мин):
  атомарно берёт задачи `paused` с чекпоинтом, помечает `pending` и запускает
  `_run_task_in_background`. Если баланс всё ещё пуст — задача снова уйдёт в
  `paused` (тихо). Гард от двойного запуска: только `paused`→`pending`.
- `resume_task` (tasks.py:643): добавить `paused` в разрешённые статусы и
  ручную кнопку «Продолжить сейчас».
- Фронт: добавить `'paused'` в `TaskStatus`, подпись «На паузе», цвет (амбер),
  блок «⏸ На паузе» с пояснением + кнопкой; обработать в `useGlobalTaskPoller`.

**Дефолты (можно поменять):** автовозобновление + ручная кнопка; интервал 10 мин.

## 5. Фазы

- [x] **Фаза 1 — Слой 1 (фронт: продолжение с чекпоинта везде).**
  `TaskStatus.tsx`: `RESUMABLE_TASK_TYPES` + `isResumable()`, условия кнопок
  обобщены (Branch A: `pre_excel`, Branch B: `chunks_done` для всех resumable-
  типов, включая `CHECK_*`). Добавлены `data-testid` resume/restart. Тесты:
  `TaskStatus.test.tsx` +4 (CHECK_LIST/PROJECT_COMPLETENESS, регрессия
  ESTIMATE pre_excel, no-checkpoint→restart-only). Гейты: tsc 0 ошибок,
  8/8 тестов TaskStatus. (Предсуществующий фейл `ProjectDetail.test.tsx` не
  связан — падает и на базовом состоянии.)
- [x] **Фаза 2 — Слой 2 (чекпоинты для `LIST_FROM_PROJECT`).**
  `_handle_list_from_project`: проход 1 (извлечение из PDF) пишет чекпоинт
  после каждого чанка (`chunks_done`, `_stage="pass1"`) и восстанавливает
  накопленные позиции + `seen_names` при resume; после прохода 1 — маркер
  `_stage="pass1_done"` (пауза в проходе 2 не перезапускает дорогой проход 1);
  проход 2 (уточнение объёмов) пишет чекпоинт после каждого null-чанка (resume
  считает лишь оставшиеся null). **Важно:** `InsufficientBalanceError` в любом
  чанке теперь пробрасывается (раньше non-first чанк молча пропускался — пауза
  для LIST_FROM_PROJECT не работала). `LIST_FROM_PROJECT` добавлен в
  `RESUMABLE_TYPES` (роутер) и `RESUMABLE_TASK_TYPES` (фронт). Миграция не нужна.
  Тесты: `test_list_from_project_resume.py` (4). Полный сьют: 255 passed.
- [x] **Фаза 2б (приоритет) — промежуточный чекпоинт в шаге 2
  `ESTIMATE_FROM_LIST`.** Инкрементальное сохранение `claude_results`
  (`_stage="claude_partial"`), пропуск уже посчитанных `_id`, resume-ветка.
  Реализация под текущий (fast/sync/batch) код: `_pending_chunks` (пропуск
  посчитанных), `_save_claude_partial` (чекпоинт), главный проход группами по
  `ESTIMATE_MAIN_CHECKPOINT_GROUP`=8 с чекпоинтом после каждой (не трогает
  `_run_chunks_parallel` и batch). Seed `claude_results` из claude_partial на
  входе. Router `has_checkpoint` + фронт `hasResumeCheckpoint`/кнопка расширены
  на `claude_partial`. **Уточнение премиса:** batch-режим (готов, на main)
  уже устойчив к рестарту/паузе, поэтому 2б покрывает дефолтный fast/sync путь.
  Тесты: `test_estimate_resume_checkpoint.py` (4), фронт `claude_partial` (1).
  Гейты: py_compile OK, целевые 18/18, фронт 38/38, tsc 0. Предсуществующие
  11 падений бэкенда — не связаны (проверено stash-прогоном на базе).
- [x] **Задача 1 (baseline) — починка 11 предсуществующих падений тестов + ruff.**
  Коммит `47a5ddd`. Каждое падение разобрано «тест устарел / код сломан»:
  migration_startup (деплой→Docker, читаем Dockerfile CMD), admin get_task
  (код: фильтр `deleted_at IS NULL` — недоведённый soft-delete), delete_project
  (тест: soft-delete теперь разрешён любому юзеру), task_file_slots +
  estimate_task_types_constant (тесты: `LIST_FROM_GRAND` больше не estimate-тип
  → `ESTIMATE_FROM_LIST`), conftest (импорт модели `TaskInputFile`), ruff F401.
  Итог сьюта: **239 passed, 8 skipped, 0 failed**.
- [x] **Фаза 3 — Слой 3a (пауза: `InsufficientBalanceError` + статус `paused`).**
  `claude_service.py`: класс `InsufficientBalanceError(RuntimeError)`, бросается
  вместо голого RuntimeError при 4xx «credit balance». `task_processor.py`:
  импорт класса; 3 строковых проверки (`_call_claude_json_with_retry`,
  `_interruptible_claude_json_with_retry`, ESTIMATE chunk) заменены на
  `except InsufficientBalanceError`; в `process()` отдельный
  `except InsufficientBalanceError` → `update_status("paused", ...)` (чекпоинт
  в progress_data переживает rollback). `tasks.py`: `resume_task` допускает
  статус `paused`. Тесты: `test_balance_pause.py` (7). Гейты: py_compile OK,
  ruff (изменённые файлы) чист, целевые 7/7, полный сьют **246 passed**.
- [x] **Фаза 4 — Слой 3b (автовозобновление планировщиком).**
  Новый `app/services/resume_poller.py` (по образцу `batch_poller`):
  `_has_checkpoint` (тот же предикат, что у ручного resume), `_find_resumable_
  paused_ids`, `_claim` (атомарный `paused`→`pending` через `WHERE status=
  'paused'` + rowcount — гард от двойного запуска), `resume_paused_tasks`
  (захват + fire-and-forget `_run_task_in_background`, ленивый импорт от цикла).
  `main.py`: job `interval, minutes=10, max_instances=1` + один немедленный
  проход при старте (подхват paused после рестарта, обёрнут в try/except).
  Миграция не нужна. Тесты: `test_resume_poller.py` (5). Полный сьют: 251 passed.
- [x] **Фаза 5 — Слой 3c (фронт: статус `paused`, блоки/цвета/поллер).**
  `types/index.ts` (тип + `STATUS_LABELS`) и `types/workflow.ts` (kanban-тип).
  `STATUS_COLORS`/карты статусов (амбер) во всех местах, где разъезжается тип:
  `TaskStatus.tsx`, `Admin.tsx`, `TaskDetailModal.tsx`, `ProjectCardPage.tsx`,
  `ProjectsSidebar.tsx`, `kanban/TaskStatusBadge.tsx`, type-test
  `status-colors-coverage.ts`. Блок «⏸ На паузе» + кнопка «▶ Продолжить сейчас»
  (`handleResume`) в `TaskStatus.tsx`. `kanban.ts`: paused-перечень блокирует
  переход на следующую стадию (hard, «продолжится автоматически») — иначе
  незавершённая пауза ошибочно разрешала стадию. `useGlobalTaskPoller.ts`:
  paused — не терминальный статус (задачу НЕ снимаем с отслеживания), инфо-тост
  один раз (гард `pausedNotified`). Тесты: `TaskStatus.test.tsx` +3 (блок,
  клик→resumeTask, подпись). Заодно снят предсуществующий AudioContext-шум в
  `ProjectDetail.test.tsx`/`TaskStatus.test.tsx` (мок `notificationSound`).
  Гейты: tsc 0, vitest **41 passed, 0 errors, exit 0**.
- [ ] **Фаза 6 — Интеграция, гейты, ревью, ручная проверка сценариев.**
- [x] **Фаза 7 (харденинг) — два пробела авто-возобновления по балансу.**
  Ветка `feature/balance-pause-hardening`.
  1. **Распознавание billing было только по подстроке `"credit balance"`.**
     Запросы могут идти через агрегатор/прокси (`settings` base_url) с иной
     формулировкой/кодом → billing-ошибка не опознавалась, задача уходила в
     `failed`, а не `paused`. Введены в `claude_service.py`:
     `_BALANCE_ERROR_MARKERS` (консервативный список: credit balance /
     insufficient balance|funds|_quota / balance is too low / out of credit /
     недостаточно средств|баланса), `_is_insufficient_balance(status, *texts)`
     (+ статус **402 Payment Required**), `_raise_if_insufficient_balance(e)`.
     Хелпер переиспользован в `call_claude` (заменил inline-проверку).
  2. **Batch-режим не уводил billing в паузу.** (а) `submit_claude_batch`
     оборачивает `batches.create` → `_raise_if_insufficient_balance` (billing →
     `InsufficientBalanceError` → `process()` уводит в `paused`, а не `failed`).
     (б) `_submit_estimate_batch` сохраняет resumable-чекпоинт `claude_partial`
     **ДО** отправки — иначе paused-задачу не подхватил бы `resume_poller`
     (`batch_pending` не в `RESUMABLE_STAGES`, а до submit его ещё нет).
  Тесты: `tests/test_balance_pause_hardening.py` (15). Гейты: py_compile OK,
  ruff (изменённые файлы) чист, 15/15 новых зелёные, регрессий в зонах
  billing/batch нет (6 падений `_client`-фрагильности — предсуществующие,
  подтверждено stash-прогоном на базе). **Не сделано (по договорённости):**
  billing при poll/collect batch не мапится (сбор результатов не тарифицируется
  — код ради кода).

- [x] **Фаза 8 — тупик «paused без чекпоинта» (баг с прода 2026-07-28).**
  Симптом: `ESTIMATE_FROM_LIST` встала в `paused` по балансу; после пополнения
  авто-возобновление молчало, кнопка «Продолжить сейчас» → «Не удалось
  возобновить задачу».
  1. **Корень.** И `resume_task`, и `resume_poller._find_resumable_paused_ids`
     требовали `has_resumable_checkpoint`. Но пауза наступает и ДО первого
     чекпоинта: в fast-режиме первая группа чанков идёт в Claude до
     `_save_claude_partial`, в batch-режиме — до Фазы 7 чекпоинта перед submit
     вообще не было (прод стоял на `b1345de`, т.е. без Фазы 7). `progress_data`
     пуст → поллер задачу не берёт, эндпоинт отвечает 409 «Нет сохранённого
     прогресса» → задача мертва навсегда. Фикс: для `paused` чекпоинт больше не
     обязателен (перезапуск с нуля — терять нечего) и тип задачи не ограничивается
     `RESUMABLE_TYPES`; для `failed`/`cancelled` контракт прежний (409).
  2. **Пачка Batch API не должна пересчитываться.** `checkpoint.is_batch_pending`
     (`_stage=batch_pending` + `batch_id`): такая paused-задача возвращается в
     `processing` без нового job — результаты (уже оплаченные) доберёт
     `batch_poller`. Реализовано и в эндпоинте, и в поллере
     (`_claim_batch_to_processing`).
  3. **Batch-задача помечалась `completed` сразу после submit.** `process()`
     после хендлера безусловно ставил `completed`, а `batch_poller` ищет только
     `processing`/`cancelled` → смета не достраивалась никогда. Теперь при
     `batch_pending` задача остаётся `processing` (`_is_batch_pending`).
  4. **Баланс на сборке пачки** в `batch_poller` → `paused` (было `failed`),
     чекпоинт `batch_pending` сохраняется → self-healing после пополнения.
  5. **Фронт** показывал общий текст вместо причины: `handleResume`/
     `handleRestart` выводят `detail` бэкенда через `formatApiDetail`, а resume
     проставляет фактический статус из ответа (`processing` для batch).
  Тесты: `tests/test_paused_resume_dead_end.py` (10/10 зелёные), обновлён
  контракт `tests/test_resume_poller.py`. Гейты: полный бэкенд-прогон
  `340 passed` (22 падения — предсуществующие, список идентичен stash-baseline),
  фронт `tsc --noEmit` чист.

Фазы 1 и 2 независимы (можно параллельно). Фазы 3→4→5 последовательны
(4 зависит от статуса `paused` из 3; 5 — от бэкенда 3–4).

## 6. Challenge Log

1. **Решает ли проблему?** Да: слои 1–2 закрывают «рестарт вместо продолжения»
   (КП-1..3), слой 3 — балансовую паузу с автопродолжением (КП-4..7).
2. **Самое ли эффективное решение?**
   - *Альт. A:* только ручной resume для баланса — не выполняет требование
     «продолжился автоматически». Отклонено.
   - *Альт. B:* Anthropic Message Batches API (`processing_mode='batch'`, уже
     заложен в модели) для устойчивости — это отдельная крупная переделка потока,
     избыточна для задачи. Отложено.
   - *Альт. C (выбрано):* переиспользовать существующий checkpoint+resume,
     добавить статус `paused` и планировщик-поллер. Минимум нового кода,
     опирается на готовую инфраструктуру. У Anthropic нет API проверки баланса —
     единственный способ «узнать про пополнение» это пробный вызов, поэтому
     поллер-ретрай — оптимальный паттерн.
3. **Нет ли «кода ради кода»?** `ESTIMATE_OPTIMIZATION` вынесен в опциональную
   подзадачу, чтобы не раздувать объём. Всё остальное привязано к КП.

## 7. Риски и edge-cases

- **Двойной запуск** paused-задачи поллером — гард `paused`→`pending` атомарно.
- **Шторм пробных вызовов** при куче paused-задач и пустом балансе — каждый
  падает быстро на первом вызове Claude; интервал 10 мин ограничивает частоту.
  При желании — обрабатывать по одной за тик.
- **Рестарт сервера во время paused** — `_recover_stuck_tasks` трогает только
  `processing`, `paused` не задевается; поллер подхватит после старта.
- **Баланс кончился на этапе без чекпоинта** (напр. `LIST_FROM_PROJECT` до
  фазы 2) — паузу ставить можно, но resume начнёт заново; фаза 2 это чинит.
- **Разъезд статусов фронт/бэк** — `TaskStatus` зашит в нескольких местах
  (types, STATUS_COLORS, поллеры); проверить все при добавлении `paused`.

## 8. Итог

Реализован. Выполнено: baseline-починка 11 предсуществующих падений тестов +
ruff (коммит `47a5ddd`); Фаза 3 — `InsufficientBalanceError` + статус `paused`
(`a16d499`); Фаза 4 — планировщик авто-возобновления `resume_paused_tasks`
(`028b574`); Фаза 5 — фронт `paused` (тип, цвета, блок «⏸ На паузе» + кнопка,
kanban-гейтинг, поллер). Ранее: Фаза 1 (`7d8bc41`), Фаза 2б (`137b738`).

Закрыты все КП-1..7 (включая КП-3 / Фазу 2 — по-чанковый чекпоинт для
`LIST_FROM_PROJECT`). Не сделано (по договорённости): `ESTIMATE_OPTIMIZATION`
resume оставлен на restart.

Гейты по завершении: бэкенд `251 passed, 8 skipped`, ruff (изменённые файлы)
чист; фронт tsc `0`, vitest `41 passed, 0 errors`.

**Дополнено 2026-07-28 (Фаза 8):** закрыт тупик «paused без чекпоинта не
возобновляется ни автоматически, ни кнопкой» + три смежные дыры (пересчёт уже
оплаченной пачки, `completed` сразу после submit batch, billing на сборке пачки).
Осталось: Фаза 6 (интеграционные гейты/ручные сценарии) — не начата;
`ESTIMATE_OPTIMIZATION` по-прежнему без по-шагового resume (перезапуск с нуля,
теперь доступен и из `paused`).
