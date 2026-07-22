# Хендофф: resume-with-checkpoint + пауза при исчерпании баланса API

**Дата:** 2026-07-23
**Ветка:** `feature/resume-and-balance-pause` (от `main`, после мёржа estimate-processing-modes)
**План:** `plans/2026-07-21-resume-and-balance-pause.md` — источник истины, актуализируй после каждой фазы.

## Цель фичи (в одну строку)
Чтобы при любой остановке задача продолжалась с чекпоинта (а не с нуля), а при
исчерпании счёта Anthropic уходила на паузу и после пополнения продолжалась.

## Что уже сделано (закоммичено)
- `7d8bc41` **Фаза 1** — фронт: «▶ Продолжить» показывается для любой resumable-
  задачи с чекпоинтом (не только 2 узких случая). Починило `CHECK_LIST_COMPLETENESS`
  / `CHECK_PROJECT_COMPLETENESS`. Файл `frontend/src/pages/TaskStatus.tsx`
  (`RESUMABLE_TASK_TYPES`, `hasResumeCheckpoint`, `isResumable`, `data-testid`).
- `7251b84` **fix** — устаревший `ProjectDetail.test.tsx` (старые типы + старый
  дефолт-вид) + 2 гарда в `ProjectDetail.tsx`.
- `137b738` **Фаза 2б** — промежуточный чекпоинт шага 2 `ESTIMATE_FROM_LIST`
  (`_stage="claude_partial"`): главный проход группами по
  `ESTIMATE_MAIN_CHECKPOINT_GROUP`=8 чанков, `_pending_chunks` (пропуск
  посчитанных), `_save_claude_partial`, seed `claude_results` на входе. Router
  `has_checkpoint` + фронт `hasResumeCheckpoint` расширены на `claude_partial`.
  Тесты `backend/tests/test_estimate_resume_checkpoint.py`.

## ЗАДАЧА 1 (первая в новом чате): починить предсуществующие падения
В полном бэкенд-сьюте **11 предсуществующих падений** (падают и на `main`, НЕ
связаны с этой фичей — подтверждено stash-прогоном). Их нужно починить ПЕРВЫМИ.
Плюс 2 ruff-ошибки. Список:

Бэкенд-тесты (`cd backend && python3 -m pytest -q`):
1. `tests/test_admin.py::test_admin_delete_task` (assert 200 == 404)
2. `tests/test_migration_startup.py::test_render_yaml_start_command_has_no_stamp_head`
3. `tests/test_migration_startup.py::test_render_yaml_start_command_has_upgrade_head`
4. `tests/test_migration_startup.py::test_render_yaml_upgrade_head_before_uvicorn`
5. `tests/test_migration_startup.py::test_render_yaml_fix_script_before_upgrade_head`
6. `tests/test_projects_router.py::test_delete_project_requires_admin`
7. `tests/test_task_file_slots.py::test_upload_estimate_slot_parses_cost`
8. `tests/test_task_file_slots.py::test_delete_estimate_slot_clears_cost`
9. `tests/test_task_file_slots.py::test_auto_fill_estimate_slot_sets_status_and_slot`
10. `tests/test_task_file_slots.py::test_auto_fill_no_result_sets_unestimated`
11. `tests/test_xlsx_cost_parser.py::test_estimate_task_types_constant`

ruff (`cd backend && python3 -m ruff check .`):
- F401 неиспользуемый импорт `extract_pdf_with_ocr` в `app/services/task_processor.py:26`
  (и, возможно, ещё один в той же строке).

Подсказки к диагностике (не проверено, гипотезы):
- `test_migration_startup` читает `render.yaml` — вероятно, стартовая команда
  изменилась. Смотреть `render.yaml` vs assert'ы теста.
- `test_admin_delete_task` / `test_delete_project_requires_admin` — эндпоинты
  удаления/прав; вероятно, тесты устарели или изменилось поведение (как было с
  `ProjectDetail.test`). Проверить, ассерты vs реальные роуты.
- `test_task_file_slots` (cost) / `test_xlsx_cost_parser::test_estimate_task_types_constant`
  — связано с парсингом стоимости сметы / константой `ESTIMATE_TASK_TYPES`.
- Для КАЖДОГО падения: сначала понять, тест устарел или код сломан (как в
  ProjectDetail). Чинить по существу, не подгонять. Каждое — доказанное, не
  «для красоты» (принцип bulletproof).

## ЗАДАЧИ 2+: продолжить план по фазам (bulletproof)
Осталось из `plans/2026-07-21-resume-and-balance-pause.md`:
- [ ] **Фаза 2 (не приоритет)** — по-чанковый чекпоинт для `LIST_FROM_PROJECT`
  (сейчас пишет только финальные items; добавить как в `_handle_check_completeness`,
  добавить в `RESUMABLE_TYPES`).
- [ ] **Фаза 3** — `InsufficientBalanceError(RuntimeError)` в
  `backend/app/services/claude_service.py` (вместо голого RuntimeError по
  подстроке "credit balance", ~строки 330-335); ловить его ОТДЕЛЬНО в
  `TaskProcessor.process()` (`except Exception` в task_processor) →
  `update_status("paused", ...)` вместо `"failed"`. Заменить хрупкие строковые
  проверки "credit balance"/"баланс api" (task_processor: в `_fetch_chunk` ~2032,
  chunk-обёртках) на `isinstance`. Router `resume_task`: добавить `paused` в
  разрешённые статусы.
- [ ] **Фаза 4** — планировщик авто-возобновления. `AsyncIOScheduler` уже есть
  (`backend/app/main.py:41`, `scheduler.add_job(..., "interval", ...)` ~137).
  Добавить job (interval 10 мин) `resume_paused_tasks`: атомарно берёт `paused`
  с чекпоинтом, помечает `pending`, запускает `_run_task_in_background`. У
  Anthropic НЕТ API проверки баланса — узнать про пополнение можно только
  пробным вызовом (снова упадёт → снова `paused`). Гард от двойного запуска.
  `_recover_stuck_tasks` (main.py ~92) трогает только `processing` — `paused`
  не задевает, но проверить.
- [ ] **Фаза 5** — фронт: добавить `'paused'` в `TaskStatus`
  (`frontend/src/types/index.ts` тип + `STATUS_LABELS`), `STATUS_COLORS`
  (`TaskStatus.tsx:34`), блок «⏸ На паузе» + кнопка «Продолжить сейчас», обработать
  в `useGlobalTaskPoller.ts` (сейчас только completed/failed).

Дефолты для Фаз 3-5 (согласованы): авто-возобновление + ручная кнопка; интервал 10 мин.

## КРИТИЧНО: окружение и правила
- **Backend:** `cd backend`. Питон — только `python3` (НЕ `python`, venv нет,
  deps глобальные Python 3.9). Тесты: `python3 -m pytest -q`. `asyncio_mode=auto`
  (async-тесты без декоратора). Компиляция: `python3 -m py_compile <file>`.
  Линт: `python3 -m ruff check .`. Миграции: при изменении `models/*.py` СНАЧАЛА
  создать `alembic/versions/0NN_описание.py` с `IF NOT EXISTS` (см. CLAUDE.md).
  Для статуса `paused` миграция НЕ нужна (поле `status` строковое `String(20)`,
  не Enum).
- **Frontend:** `cd frontend`. Тесты: `npx vitest run`. Типы: `npx tsc --noEmit`
  (это и есть lint-гейт; отдельного eslint НЕТ). Тест-паттерн — см.
  `src/__tests__/TaskStatus.test.tsx` / `ProjectDetail.test.tsx` (vi.mock, findByTestId).
- **Правила проекта (CLAUDE.md):** отвечать по-русски; каждую новую функцию —
  через skill `bulletproof`; после каждой задачи — git commit (осмысленный,
  с `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`);
  актуализировать план после каждой сессии; в конце чата — рефлексия в
  `.business/история/YYYY-MM-DD-краткое-название.md`.
- **Impact Analysis:** предсуществующие 11 падений — это baseline. После своих
  правок сравнивай с ним (stash-прогон), чтобы отличать свою регрессию от старого.
  Когда Задача 1 выполнена — baseline должен стать «0 падений».
- **Не деплоить** без явного запроса.

## Ключевой контекст архитектуры (чтобы не переоткрывать)
- Обработка задач: `TaskProcessor.process()` в `backend/app/services/task_processor.py` —
  единственная точка перевода в `failed` (`except Exception` → `update_status("failed")`).
- Вызов Claude: `backend/app/services/claude_service.py`. Баланс детектится ТОЛЬКО
  по подстроке "credit balance" в 4xx (~330-335) → `RuntimeError`. Rate-limit (429)
  — это НЕ падение, а ожидание с backoff внутри вызова.
- Нет Celery/очереди — фон через FastAPI `BackgroundTasks`; авто-восстановление
  `processing`→`failed` при рестарте в `_recover_stuck_tasks` (main.py).
- `ESTIMATE_FROM_LIST` шаг 2 — 3 режима (`task.processing_mode`, дефолт "fast"):
  batch (Message Batches API, свой resume через поллер, УЖЕ устойчив), fast
  (параллельно, `_run_chunks_parallel` — барьер), sync. Фаза 2б добавила
  `claude_partial` для fast/sync. `_run_chunks_parallel` и batch НЕ трогать без нужды.
- Чекпоинты в `Task.progress_data` (JSONB): `chunks_done`/`_stage`
  (`pre_excel`|`claude_partial`|`batch_pending`). Resume-эндпоинт
  `POST /tasks/{id}/resume` (`backend/app/routers/tasks.py`), `RESUMABLE_TYPES`.
