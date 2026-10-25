# План: чистка тестов

**Статус:** done — фазы 0–7 сделаны 25–26.10.2026; открытые пункты «Найдено по пути» — отдельные задачи
**Ревью:** 25.10.2026, все тесты бэкенда (159 файлов) и фронта (71 файл + 2 type-level)

## Зачем

Часть тестов мешает, а не защищает: ломается при рефакторинге без изменения
поведения, проверяет вызовы моков вместо результата, повторяет код реализации,
гоняет один сценарий десятью способами, проверяет вёрстку, формат и тексты.

Критерий пользователя: хороший тест ловит сломанную функциональность. Переписали
код, поведение прежнее — тест проходит. На бэкенде — интеграционные тесты
эндпоинтов с тестовой БД; дешёвый юнит, который ловит реальные ошибки, остаётся.
Конкретный ожидаемый результат — нормально, проверка магических чисел — нет.

## Как проверяли

10 ревьюеров по тематическим группам (только чтение, каждое «повторяет
реализацию» сверено с продовым кодом). Утверждения о продовом коде и мёртвом коде
перепроверены вручную. Противоречие между группами (обе предлагали удалить
друг у друга тест стоимости веб-поиска в пачке) разрешено: остаётся
`test_api_cost_pricing.py`, где закреплены цены по правилу №13.

## Сводка

| Группа | Тестов | Удалить | Переписать | Спорно |
|---|---|---|---|---|
| Б1 Балансы, траты на API, метрики, дашборд | 159 | 21 | 28 | 4 |
| Б2 Воркер, очередь, ETA, возобновление | 238 | 27 | 38 | 2 |
| Б3 Обработка ИИ: пачки, чанки, оптимизация, PDF | 223 | 44 | 40 | 3 |
| Б4 Разбор файлов и xlsx | 309 | 40 | 26 | 17 |
| Б5 Цены, единицы, эталон, эмбеддинги | 344 | 36 | 62 | 4 |
| Б6 Запрос КП | 203 | 15 | 17 | 2 |
| Б7 Документы, сводная, корректировки | 134 | 12 | 9 | 2 |
| Б8 RBAC, миграция смет, хранилище, прочее | 160 | 54 | 19 | 1 |
| Ф1 Редактор, расчёты, выгрузка, сводная | 357 | 56 | 38 | 26 |
| Ф2 Страницы, дашборд, канбан, КП, статус | 312 | 71 | 49 | 4 |
| **Итого** | **≈2440** | **≈376 (15%)** | **≈326 (13%)** | **≈65** |

Без изменений остаётся ≈1670 тестов (≈69%). Хорошие файлы-образцы:
`test_batch_results_proxy`, `test_chunks_watcher_session`,
`test_optimization_manual_start`, `test_material_kits`, `test_summary_calc`,
`test_price_suggestions`, `test_normalize_name_collisions`,
`test_estimate_single_source`, `kpRequestPage`, `requestKp`,
`TaskStatusHeartbeat`.

## 0. Опасное — убрать первым

- `test_migration_startup.py::test_upgrade_head_creates_projects_table`,
  `test_stamp_head_then_upgrade_head_skips_migrations` — выполняют
  `DROP TABLE IF EXISTS projects CASCADE` и `DROP TABLE alembic_version` на базе
  из `os.environ["DATABASE_URL"]` (строки 139–140, 188–189). Сейчас пропускаются:
  локально переменная не задана, в прод-образе нет pytest. Но запуск тестов с
  выставленной `DATABASE_URL` (dev-контейнер, проверка на настоящем PostgreSQL)
  снесёт проекты каскадом вместе с карточками. Второй к тому же проверяет сам
  alembic, а не наш код. → удалить оба; проверка миграций на чистом PostgreSQL,
  если нужна, — отдельная задача с отдельной переменной и пустой БД.
- `test_schema_integrity.py` — весь файл (6 тестов). Диагностика разового
  инцидента «stamp head» на ревизии 006; с `DATABASE_URL` падает на
  `== '006'` (последняя миграция — 053). → удалить.

## Найдено по пути — это код, а не тесты, решить отдельно

1. **Разбор гранд-сметы.** Колонку «всего с учётом коэффициентов» парсер ищет
   только в 1–4 строках под шапкой (`file_parser._find_header_row`, строка 130).
   Настоящая раскладка ГРАНД (подзаголовок под «Количество») разбирается
   верно. Файл с однострочной шапкой потеряет коэффициенты — объём возьмётся из
   «Количества». Тесты, которые якобы это проверяют
   (`test_quantity_of_equipment_is_the_total_column`,
   `test_material_position_survives`), проходят только потому, что числа в обеих
   колонках равны. → переписать фикстуру; решить, искать ли колонку и в самой шапке.
2. **«Перевод смет» в админке опасен после выполнения.** Миграция выполнена
   04.08.2026. По правилу №1 `progress_data['items']` у сметы заморожен как вывод
   ИИ, поэтому после любой правки сметы отчёт покажет «расхождение», а
   `/resolve prefer=items` перезапишет правки человека ответом ИИ (с бэкапом в
   историю). → кандидат на удаление функции целиком: эндпоинты, сервис, скрипт,
   панель.
3. **`PUT /tasks/{id}/estimate/versions/{vid}/rows`** (`estimate_versions.save_rows`)
   переписывает `progress_data['items']` и для версии входного файла — проверки
   слота нет. Фронт этот путь сейчас не вызывает (`saveGenericRows` не
   используется), но прямой вызов API заменит позиции ИИ строками заказчика.
4. **Контракт «HTTP 401/403» между `anthropic_admin._request` и паузой в
   `worker._sync_api_cost_job`** не проверен ни с одной стороны — тесты обеих
   сторон сами сочиняют строку ошибки. Сменится формат — пауза синхронизации
   молча перестанет работать (правило №13).
5. **Не покрыто тестами вовсе:** правило единиц (№8) у кнопки «Цена»
   (`reprice_estimate_item`); логика `_process_single_item` оптимизации и
   возобновление по (лист, строка); правило №6 на уровне эндпоинта (все тесты
   зовут `_sync_task_items` напрямую); `not_started` (№20) в очистке задач без
   job и в прогнозе очереди.
6. **Мёртвый код:**
   - `BatchProgressBar` и `utils/batchProgress` — бэкенд не присылает «Обработка
     батча N из M» (пишет «часть N из M»), полоса не показывается никогда;
   - `excel_service.generate_smeta` — вызывает только `test_basic`;
   - флаг `is_shared` — только пишется (`main._initialize_users`), `can_access`
     его игнорирует;
   - `resume_paused_tasks(runner=…)` и `_claim` — ветка только для тестов;
   - `sys.modules.setdefault("fitz", MagicMock())` в шапке тестов — ничего не
     делает (conftest импортирует настоящий fitz);
   - `_make_xlsx_bytes` в `test_task_history.py` — не используется;
   - класса `.de-overlay` в коде нет (тест на него вечно зелёный).
7. **`__type-tests__/status-colors-coverage.ts` не защищает того, ради чего
   создан:** все четыре настоящих места (`STATUS_LABELS`, `STATE_STYLE`,
   `Admin.tsx`, `TaskStatus.tsx`) уже `Record<TaskStatus, …>`; ослабят любое до
   `Partial` — файл не заметит. Второй тип `TaskStatus` в `types/workflow.ts` не
   покрыт. → `satisfies Record<TaskStatus, …>` у самих констант.
8. **Хрупкость окружения:** `test_slots_*` зависят от `os.cpu_count` (падают на
   машине с ≤4 ядрами); `NOW` в `test_dashboard_pulse` считается при импорте
   (мигает при прогоне через полночь UTC); `test_spa_catch_all` проходит только
   при собранном `frontend/dist` (в .gitignore) — на чистом клоне падает;
   `test_anthropic_admin_cost::test_returns_none_without_admin_key` при заданном
   `ANTHROPIC_API_KEY` уходит в настоящий HTTP.
9. **(фаза 3) `/prices/match-preview` для материала всегда показывает цену `null`:**
   `price_service.find_top_n_materials` кладёт цену в ключ `min_price`, а роутер
   (`prices_catalog.match_preview`) читает `price`. Старый тест подставлял
   подделку с ключом `price` и этого не видел; на векторах в БД (`price_db`)
   видно сразу. → поправить ключ в роутере или в сервисе.
10. **(фаза 3) Тесты ходят в сеть:** `test_price_unit_match.py`
    `test_nesvodimaya_edinica_cenu_ne_daet`, `test_kesh_tozhe_sveryaet_edinicu`,
    `test_pozicii_ishodnoy_zadachi_ne_pravyatsya` отправляют позицию в настоящий
    `call_claude` (клиент не подменён) и по 40 с ждут повторов после ошибки
    соединения. → при переписывании файла на `processor_env` уйдёт само.
11. **(фаза 3) Общая in-memory база — одно соединение на все сессии:**
    `rollback()` любой сессии откатывает чужую незакоммиченную запись. Тест с
    настоящей конкуренцией сессий на `TestSessionLocal` будет мигать (у цикла
    воркера `claim_one` на пустой очереди терял `complete` соседней job).
    Поэтому `worker_loop` — на своей базе-файле.
12. **(фаза 4) Веб-поиск цены не работал с 06.08.2026 — ИСПРАВЛЕНО (2b836cc):**
    `price_service._web_search_*` передавали обёртке `call_claude` `task_id`,
    `db`, `is_extra`, она их не принимала; `TypeError` глотал `except`. Цена с
    рынка не находилась вовсе (оптимизация, «найти цену»), вызовы не попадали в
    журнал затрат. Нашли независимо Б1 и Б3; тесты стояли строгим xfail, сняты.
13. **(фаза 4) `xlsx_optimizer._map_columns`:** заголовок «Цена работы (за ед.)»
    распознаётся как колонка единицы (есть «ед» и точка) — ценой за единицу
    становится стоимость строки (10000 вместо 10). Наш файл сметы разбирается
    верно; файл заказчика с таким заголовком в слоте «estimate» — нет. → открыто.
14. **(фаза 4) Новая запись кеша цен не видна точному поиску до перезагрузки:**
    `save_to_cache` кладёт её в `_cache_works_cache`, а `_exact_match_cache_work`
    ищет по `_cache_works_by_norm`, который строится только в `load_cache` —
    одна и та же позиция может повторно уходить в платный поиск. → открыто.
15. **(фаза 4) Защита правки п. 1 — ИСПРАВЛЕНО (ae8492c):** колонка стоимости с
    подписью «…всего с учётом коэффициентов» не принимается за объём.
16. **(фаза 4) Мелочи, открыто:** `parse_xml` не срезает namespace у атрибутов;
    карты `Record<string, …>` в `ProjectsSidebar`, `TaskDetailModal`, `Trash` не
    знают `not_started` (в `Trash` и `paused`) — показывается запасное значение;
    старые ошибки типов в тестах `kpRequestPage:506`, `requestKp:511`,
    `optimizationEditor:142` (типы тестов основной tsconfig не проверяет);
    остальные тесты `test_kp_parser.py` подменяют свой `kp_parser.call_claude`.

**Что закрыто из пп. 1–11:** п. 1 (правка `file_parser` + защита, п. 15), п. 2
(функция удалена), п. 4 (`test_cost_sync_pause` на настоящем HTTP-ответе), п. 5
(кнопка «Цена», правило №6 через эндпоинт, логика оптимизации, `not_started`),
п. 6 (кроме флага `is_shared` — это схема БД), п. 7 (`satisfies` у карт), п. 8,
п. 9 (ddbb899), п. 10. Открыты: п. 3 (`save_rows` для версии входного файла),
п. 11 (свойство тестовой базы, учтено в `worker_loop`).

---

## 1. Удалить

### Файлы целиком

| Файл | Почему |
|---|---|
| `backend/tests/test_schema_integrity.py` | см. раздел 0 |
| `backend/tests/test_grand_parse_single_pass.py` | приватная `_find_header_row`, счётчик вызовов openpyxl, тест `asyncio.to_thread` |
| `backend/tests/test_xlsx_exporter.py` | «байты не пустые», тексты шапки, жирность; суть переезжает одним интеграционным тестом в `test_export.py` |
| `backend/tests/test_processing_mode.py` | объявление колонки модели |
| `backend/tests/test_user_role_type_bug.py` | grep текста миграции 003 и баг PostgreSQL, не воспроизводимый на SQLite |
| `backend/tests/test_rbac_permissions.py` | функции `return None` / `return True`; оставшийся `test_is_admin_and_is_manager` — в `test_kp_roles_access.py` |
| `backend/tests/test_migrate_estimate_items.py` | дубли API-тестов через реэкспорт скрипта; 2 теста `TestTotalsMatchFile` — в `test_estimate_single_source.py`, 1 — в API-файл |
| `frontend/src/__tests__/editorCompactHeader.test.tsx` | классы `.de-*`, длина title, тексты подсказок |
| `frontend/src/__tests__/smetaListSticky.test.tsx` | sticky/top/фон |
| `frontend/src/__type-tests__/api-tasks-exports.ts` | экспорты и так проверяет tsc через импорт в `TaskStatus.tsx`; список устарел |

Почти целиком (остаётся 1–2 теста, их перенести): `editorNumberFormat.test.tsx`
(2 → к тестам адаптера и выгрузки), `smetaListStages.test.tsx` (1),
`TaskStatusEta.test.tsx` (1), `test_optimization_parallel.py` (остаток
переписывается), `test_chunk_tally_visible.py` (остаток переписывается).
Если подтвердится мёртвость `BatchProgressBar` — удалить с компонентом
`BatchProgressBar.test.tsx` и `batchProgress.test.ts`.

### Б1. Балансы, траты на API, метрики, дашборд

- `test_admin_api_health.py::test_balance_detail_empty_without_api_data` — пустой хвост `_balance_error_detail`. Тривиальная ветка приватного форматтера.
- `test_admin_api_health.py::test_balance_detail_truncates_long_message` — длина хвоста < 260. Магическое число и формат текста.
- `test_balance_pause.py::test_insufficient_balance_is_runtimeerror_subclass` — `issubclass(…, RuntimeError)`. Иерархия классов, на неё ничто в `app/` не опирается.
- `test_balance_pause_hardening.py::test_call_claude_maps_402_to_balance, test_call_claude_maps_insufficient_quota` — 402 и insufficient_quota → InsufficientBalanceError. Дубль `test_balance_pause.py::test_credit_balance_4xx_raises_insufficient_balance` и тестов предиката.
- `test_balance_service.py::TestSync::test_without_admin_key_returns_none` — проброс None одной строкой. «Нет ключа» закрыт в anthropic_admin и worker.
- `test_cost_sync_pause.py::test_success_clears_pause` — приватный `_cost_sync_paused_until` = None. Внутреннее состояние без видимого эффекта.
- `test_anthropic_admin_cost.py::TestCredential::test_no_keys_at_all` — `is_configured()` False. Дубль `test_returns_none_without_admin_key` после его исправления.
- `test_api_balance_endpoint.py::TestSyncEndpoint::test_sync_survives_anthropic_failure` — отказ Anthropic → 200. Целиком входит в `TestSyncDiagnostics::test_error_text_reaches_response`.
- `test_api_rate_limit_counter.py::test_recent_hits_add_hint` — «429»/«лимит» в hint. Текст; сигнал несёт `hits_1h`.
- `test_api_rate_limit_counter.py::test_old_hits_do_not_alarm` — вчерашний 429 не тревожит. Окна — дубль `test_counts_are_split_by_window`, остальное — текст.
- `test_rate_limit_retry.py::test_rate_limit_exhausted_raises` — после ретраев 429 пробрасывается. Дубль `test_balance_pause_via_proxy.py::test_429_without_balance_marker_still_retries` (там ещё число попыток).
- `test_rate_limit_retry.py::test_rate_limit_warning_is_logged, test_rate_limit_log_includes_retry_after_and_actual_wait` — «rate limit»/«839» в stdout. Текст лога; 429 пишется структурно в `system_events`.
- `test_usage_metrics.py::test_queue_and_work_seconds_from_timestamps` — тайминги 180/840. Та же ветка, что `test_finished_counters_keep_exact_seconds`; числа повторяет `test_card_usage_api::test_card_list_carries_stage_usage`.
- `test_usage_metrics.py::test_all_four_token_kinds_counted` — сумма четырёх видов токенов. `test_main_and_extra_are_summed_separately` ловит потерю любого вида.
- `test_usage_metrics.py::test_task_without_any_calls_present_with_zeros` — нули без вызовов. Дубль `test_card_usage_api.py::test_stage_without_ai_calls_reports_zeros` (эндпоинт).
- `test_usage_metrics.py::test_several_runs_sum_tokens_but_time_is_of_the_last` — «время последнего прогона» не проверяется, двух прогонов нет. Дубль `test_main_and_extra_are_summed_separately`.
- `test_resume_poller_balance_gate.py::test_no_paused_tasks_skips_ping` — без пауз пинга нет. Дубль `test_resume_poller.py::test_resume_paused_tasks_noop_when_none`.

### Б2. Воркер, очередь, ETA, возобновление

- `test_migration_startup.py::test_stamp_head_then_upgrade_head_skips_migrations, test_upgrade_head_creates_projects_table` — см. раздел 0.
- `test_migration_startup.py::test_render_yaml_start_command_has_upgrade_head` — в CMD есть `alembic upgrade head`. Дубль `test_render_yaml_upgrade_head_before_uvicorn`.
- `test_admin_queue_health_resources.py::test_db_connections_absent_on_sqlite` — на SQLite `db_connections` = null. Ветка нужна только тестам.
- `test_eta_queue_position.py::test_single_task_is_next_in_line` — позиция 1, старт 0. Дубль `test_position_matches_growing_wait`.
- `test_eta_service.py::test_queue_order_is_by_creation_time` — порядок по created_at. Дубль `test_eta_queue_position.py::test_positions_follow_queue_order`.
- `test_job_queue.py::test_reclaim_requeues_stale` — протухшая job → queued. Дубль `test_orphaned_tasks.py::test_reclaim_requeue_keeps_task_processing` (перенести туда `status == "queued"`, `claimed_by is None`).
- `test_job_queue.py::test_reclaim_fails_after_max_attempts` — попытки исчерпаны → failed. Дубль `test_orphaned_tasks.py::test_reclaim_max_attempts_marks_task_failed` (перенести проверку статуса job).
- `test_job_retry_visible.py::test_retry_message_lands_in_task` — сообщение о повторе в задаче. Дубль сквозного `test_worker_reports_retry_on_failure` (перенести `progress_log`).
- `test_orphaned_tasks.py::test_requeue_after_shutdown_empty_list` — пустой список → 0. Тривиальный ранний return.
- `test_paused_resume_dead_end.py::test_poller_resumes_paused_without_checkpoint` — дубль `test_resume_poller.py::test_resume_paused_tasks_enqueues_job` (сделать его parametrize по progress_data).
- `test_restart_no_double_run.py::test_lone_run_stops_when_new_job_exists` — та же ветка `_check_cancelled`. Дубль `test_superseded_run_stops_at_checkpoint`.
- `test_restart_no_double_run.py::test_run_without_job_id_is_not_stopped` — job_id=None не бросает. Тривиальный ранний return.
- `test_resume_poller.py::test_resume_paused_tasks_claims_and_runs` — вызов подставленного runner. Ветка только для тестов.
- `test_worker_admission.py::test_ratio_uses_container_not_process` — тормоз срабатывает через запас, а не долю. Дубль `test_memory_snapshot.py::test_snapshot_ratio_prefers_container_over_process`.
- `test_worker_crash_recovery.py::test_attempt_is_not_refunded` — дубль `test_requeues_job_of_dead_process_on_same_host` (перенести `attempts == 1`).
- `test_worker_crash_recovery.py::test_all_three_jobs_of_dead_process_return` — тот же UPDATE на трёх строках. Дубль того же теста.
- `test_worker_duplicate_run_guard.py::test_embedding_threads_explicit_setting` — настройка 3 → 3. Проброс.
- `test_worker_memory_brake.py::test_brake_off_when_idle` — дубль `test_worker_admission.py::test_brake_off_when_idle_even_if_over_ratio`.
- `test_worker_memory_brake.py::test_brake_on_above_limit_while_busy` — дубль `test_worker_admission.py::test_absolute_rss_threshold_still_works_without_cgroup`.
- `test_worker_memory_brake.py::test_pause_threshold_above_warn` — сравнивает два дефолта конфига. Не поведение.
- `test_worker_memory_report.py::test_rss_mb_returns_number`, `test_memory_snapshot.py::test_rss_mb_returns_number_on_this_platform` — «None или > 0». Тавтология, дубли друг друга; смоук даёт `test_snapshot_never_raises`.
- `test_worker_memory_report.py::test_rss_fields_include_delta` — ключи полей лога. Форма лога.
- `test_worker_price_cache_warmup.py::test_ensure_price_cache_skips_when_loaded` — подменённый `load_cache` не вызван. Вызов мока.
- `test_task_worker_heartbeat.py::test_returns_age_of_running_job, test_none_when_no_job_for_task` — сервис в обход эндпоинта. Дубли `test_status_endpoint_exposes_heartbeat_age`, `test_status_endpoint_null_without_job`.
- `test_progress_summary.py::test_items_reduced_to_count_only` — дубль `test_sensitive_fields_are_stripped`.

### Б3. Обработка ИИ: Batch API, чанки, оптимизация, PDF

- `test_claude_batch.py::test_batch_cost_is_half_of_regular, test_web_search_adds_flat_fee_on_top_of_tokens, test_web_search_fee_not_halved_by_batch` — стоимость пачки и поиска. Дубли `test_api_cost_pricing.py::TestBatchDiscount` — цены держим в одном месте.
- `test_claude_batch.py::test_extract_usage_reads_web_search_requests` — приватный хелпер. Дубль `test_batch_results_proxy.py::test_batch_results_parsed_after_rewrite`.
- `test_claude_batch.py::test_submit_claude_batch_returns_id, test_poll_claude_batch_status, test_cancel_claude_batch` — проброс аргумента в заглушку SDK.
- `test_estimate_batch_mode.py::test_resume_from_batch_collects_and_runs_step3` — аргументы мока step3. Дубль `test_batch_retry_parity.py::test_resume_from_batch_skips_retry_when_all_priced`.
- `test_processing_mode.py` — весь файл (3): колонка, значение по умолчанию, запись ORM.
- `test_chunk_tally_visible.py::test_tally_line_reports_done_and_left, test_tally_line_empty_without_stage, test_tally_line_survives_overcount, test_second_stage_does_not_reset_first_to_zero` — текст строки счётчика через приватные методы.
- `test_chunk_tally_visible.py::test_launch_line_mentions_restored_items, test_launch_line_without_restore_is_plain, test_launch_line_always_reports_pending_not_total` — текст строки запуска; функция лишь подставляет аргументы.
- `test_chunks_parallel.py::test_empty_workers_returns_empty` — тривиальная ветка.
- `test_chunks_progress_deadline.py::test_no_progress_published_without_label` — отсутствие вызова своего метода.
- `test_chunks_progress_deadline.py::test_user_cancel_still_reported_as_cancel_not_deadline` — дубль `test_chunks_parallel.py::test_cancellation_raises_and_cancels_workers`.
- `test_chunks_progress_deadline.py::test_no_deadline_means_no_limit` — дубль `test_chunks_parallel.py::test_results_preserve_order`.
- `test_truncated_response.py::test_normal_response_still_returns_text` — счастливый путь. Дубль `test_rate_limit_retry.py::test_rate_limit_is_retried`.
- `test_estimate_resume_checkpoint.py::test_pending_chunks_empty_when_all_done, test_pending_chunks_all_when_none_done` — крайние случаи. Дубль `test_pending_chunks_excludes_done_ids`.
- `test_lost_positions_warning.py::test_warning_uses_singular_for_one` — грамматика текста.
- `test_lost_positions_warning.py::test_no_warning_when_nothing_lost` — дубль `test_lost_positions_reported.py::test_no_warning_when_ai_returned_everything`.
- `test_optimization_parallel.py::test_process_single_item_does_not_raise_on_exception` — дубль `test_process_single_item_work_exception_returns_none_price`.
- `test_optimization_parallel.py::test_batch_loop_produces_correct_batch_sizes, test_gather_results_preserve_row_index_order, test_checkpoint_empty_progress_data_processes_all_items, test_checkpoint_already_done_merged_into_results` — код реализации скопирован в тело теста.
- `test_optimization_parallel.py::test_optimization_batch_size_constant_is_positive` — константа > 0.
- `test_price_search_prompt.py::test_price_service_has_find_work_price, test_price_service_has_find_material_price` — `hasattr`.
- `test_analogs_service.py::TestEffortEstimate::test_estimate_of_nothing_is_zero` — 0 → 0; пустой выбор эндпоинт и так отклоняет.
- `test_pdf_exporter.py::test_pdf_returns_bytes, test_pdf_starts_with_pdf_magic` — weasyprint замокан в conftest, проверяется заглушка.
- `test_pdf_exporter.py::test_pdf_no_description` — дубль `test_export.py::test_export_pdf_returns_file`.
- `test_pdf_exporter.py::test_pdf_html_contains_project_name, test_pdf_html_contains_task_type_label, test_pdf_html_empty_slot_shows_placeholder` — надписи в HTML.
- `test_pdf_ocr_extractor.py::test_peak_rss_mb_positive` — RSS в 1..100000; магические границы.
- `test_pdf_validation.py::test_pdf_to_content_block_rejects_empty_bytes` — та же ветка. Дубль `test_pdf_to_content_block_rejects_corrupted_bytes`.

### Б4. Разбор файлов и xlsx

- `test_grand_material_not_section.py::test_material_reaches_claude_with_unit_and_quantity` — формат текста для Claude. Дубль `test_material_starting_with_blok_is_a_position`.
- `test_grand_parse_single_pass.py` — весь файл (6).
- `test_grand_position_not_total.py::test_material_of_the_next_work_reaches_the_list` — тот же баг регулярки. Дубль `test_equipment_with_ispolnenie_reaches_the_list`.
- `test_grand_resource_rows.py::test_resource_row_is_not_a_position, test_no_duplicate_material` — следуют из точного списка в `test_work_and_section_survive`.
- `test_grand_resource_rows.py::test_unnumbered_row_with_own_cost_survives` — дубль `test_source_position_number.py::test_parse_row_without_number_gets_empty`.
- `test_source_no_all_stages.py::test_completeness_keeps_number_of_source_position` — дубль первого шага `test_end_to_end_list_to_estimate_file`.
- `test_source_no_all_stages.py::test_estimate_row_schema_accepts_number` — поле pydantic-схемы, которую не использует ни один эндпоинт.
- `test_source_no_all_stages.py::test_uploaded_list_without_column_still_parses` — дубль `test_multisheet_estimate.py::…::test_our_own_old_perechen_is_not_counted_twice`.
- `test_source_no_all_stages.py::test_estimate_totals_block_reads_after_shift` — дубль `test_estimate_total_unchanged_by_new_column`.
- `test_source_no_all_stages.py::test_optimization_row_copy_keeps_number` — проверяет `dict()`. Закреплено в `test_kp_clone_version_and_ref.py::test_clone_version_copies_content_and_does_not_commit`.
- `test_source_no_all_stages.py::test_statement_export_carries_the_column` — дубль `test_document_export.py::test_export_accepts_any_columns_of_the_document`.
- `test_source_position_number.py::test_parse_keeps_position_number` — подмножество `test_parse_number_with_dot_and_letter`.
- `test_source_position_number.py::test_completeness_payload_drops_source_no` — дубль `test_kp_clone_version_and_ref.py::test_prompt_view_drops_kp_ref_and_source_no_without_touching_rows`.
- `test_multisheet_estimate.py::TestExactNumbers::test_returned_total_is_the_grand_total` — дубль `TestRoundTrip::test_rows_survive_the_editor_round_trip_with_the_same_total`.
- `test_xlsx_cost_parser.py::test_extract_total_cost_float_value` — тот же путь, что `test_extract_total_cost_case_insensitive`.
- `test_xlsx_cost_parser.py::test_estimate_task_types_constant` — копия константы.
- `test_xlsx_exporter.py` — весь файл: `test_xlsx_returns_bytes, test_xlsx_has_tasks_sheet, test_xlsx_has_all_slot_sheets` (ничего не проверяют), `test_xlsx_tasks_sheet_headers, test_xlsx_empty_slot_shows_placeholder` (тексты), `test_xlsx_total_row_is_bold, test_xlsx_date_column_has_no_time` (оформление); остальные 3 — в «Переписать».
- `test_xlsx_generic_headers.py::TestGrandMultiRowHeader::test_title_block_is_not_data, test_vertically_merged_header_not_duplicated` — следуют из точных ожиданий соседних тестов.
- `test_xlsx_optimizer.py::test_generate_optimized_xlsx_green_fill_for_found, test_generate_optimized_xlsx_yellow_fill_for_not_found` — цвет заливки, правила нет.
- `test_xlsx_summary.py::test_header_matches_screen` — тексты заголовков листа, обратно не разбирается.
- `test_xlsx_summary_targets.py::test_target_columns_are_added_after_the_old_ones` — тексты 11 заголовков; положение колонок закреплено значениями в `test_section_target_and_deviation_match_screen`.
- `test_generic_service_rows.py::TestPerechenSheet::test_parsed_back_without_junk_row` — дубль `test_xlsx_generic_headers.py::TestNumberingRow::test_generated_perechen_has_no_junk_first_row`.
- `test_generic_service_rows.py::TestPerechenSheet::test_list_sheet_parser_sees_only_real_items` — дубль `test_multisheet_estimate.py::…::test_our_own_old_perechen_is_not_counted_twice`.
- `test_generic_service_rows.py::TestRowsToXlsxNumbers::test_roundtrip_is_stable` — дубль `test_xlsx_generic_headers.py::TestMultipleSheets::test_roundtrip_preserves_sheets_rows_and_columns`.
- `test_kp_xlsx_marks.py::test_estimate_export_without_kp_ref_has_no_kp_fill` — уже проверено в `test_estimate_export_fills_kp_rows`.
- `test_estimate_norms.py::test_enrich_norms_stores_norm_reference` — тот же путь, что `test_enrich_norms_stores_qty_per_work_unit` (перенести туда вторым assert).

### Б5. Цены, единицы, эталон, эмбеддинги

- `test_price_bulk_add.py::TestUnitCanonical::test_prefixed_unit_scales_price, test_plain_unit_has_factor_one` — дубль `TestBulkAdd::test_prefixed_unit_price_recalculated` и `test_unit_multiplier_with_tail.py::TestPriceMatching::test_factor_extracted`.
- `test_price_bulk_add.py::TestMinPriceRule::test_contractors_only_gives_minimum, test_estimate_price_wins_even_if_higher` — дубль `test_price_min_kp.py::test_without_kp_old_rule_stays`.
- `test_price_bulk_add.py::TestMinPriceRule::test_estimate_price_wins_when_lower` — обычный `min()` даёт тот же ответ, правило приоритета не отличает.
- `test_price_bulk_add.py::TestBulkAdd::test_existing_unit_not_overwritten` — дубль `test_incompatible_unit_is_not_written`.
- `test_price_cache_no_full_reload.py::test_background_task_reference_is_kept` — продовый код не вызывается, проверяется asyncio.
- `test_price_coercion.py::test_estimate_xlsx_drops_negative_price, test_estimate_xlsx_survives_garbage_price, test_estimate_xlsx_normal_case_unchanged` — дубль `test_estimate_xlsx_mixed_valid_and_broken` (итог 4635).
- `test_price_service_embedding.py::test_embedding_match_work_no_embeddings_returns_none, test_embedding_match_material_no_embeddings_returns_none` — одна строка `if … is None`.
- `test_price_unit_match.py::test_promt_trebuet_cenu_za_edinicu_pozicii` — текст промпта; правило №8 защищает код `prices_for_unit`.
- `test_price_updated_at.py::test_money_eps_is_half_kopeck` — копия константы; порог закреплён `test_price_changed_below_eps_is_not_a_change`.
- `test_unit_multiplier_with_tail.py::TestPriceMatching::test_cost_matches_either_way` — арифметика литералов самого теста.
- `test_unit_multiplier_with_tail.py::TestQuantityConverted::test_notes_name_the_conversion` — дубль `test_multiplier_applied` + формулировка примечания.
- `test_unit_normalizer.py::TestNormalizeUnitQuantity::test_100_m2_with_space, test_unknown_unit_ml, test_zero_prefix_not_changed` — дубли таблиц `test_unit_multiplier_with_tail.py`.
- `test_unit_normalizer.py::TestNormalizeItems::test_notes_created_when_empty` — примечание не начинается с «;». Форматирование.
- `test_unit_normalizer.py::TestNormalizeItems::test_idempotent` — на «м2» менять нечего. Дубль `test_unit_multiplier_with_tail.py::test_idempotent`.
- `test_reference_price_api.py::test_preview_says_when_vector_search_is_off` — тавтология: autouse-фикстура сама ставит False.
- `test_reference_price_parse.py::test_plan_does_not_touch_the_database` — дубль `test_reference_price_api.py::test_preview_changes_nothing`.
- `test_reference_price_real_format.py::test_column_numbers_row_is_not_a_position` — дубль `test_reads_every_section_sheet`.
- `test_reference_price_real_format.py::test_case_and_spaces_still_mean_the_same_position` — дубль `test_reference_price_parse.py::test_same_name_twice_keeps_the_last_price`.
- `test_embedding_service.py::test_normalize_grade_does_not_swallow_words` — дубль `test_normalize_name_collisions.py::test_grade_rule_does_not_eat_words`.
- `test_embedding_service.py::test_normalize_m_dash_50, test_normalize_m100_lowercase, test_normalize_grade_written_differently_is_one_key, test_normalize_latin_m_to_cyrillic` — дубль `test_normalize_name_collisions.py::test_material_grade_still_collapses`.
- `test_embedding_service.py::test_normalize_extra_spaces, test_normalize_empty_string` — дубль `test_normalize_name_collisions.py::test_case_and_spaces_still_normalized`.
- `test_embedding_service.py::test_generate_embeddings_batch_default_is_document` — значение аргумента по умолчанию.
- `test_embedding_service.py::test_model_unavailable_raises` — исключение задаёт сам мок.
- `test_coefficient_and_percentages.py::test_task_cost_uses_project_percentages` — дубль `test_project_percentages_recalculate_estimates`.
- `test_coefficient_and_percentages.py::test_existing_projects_default_to_3_percent` — значение колонки по умолчанию; эндпоинтный `test_documents_api.py::test_project_percentages_default_to_3` остаётся.

### Б6. Запрос КП

- `test_kp_roles_access.py::test_is_production` — проверка `in` frozenset.
- `test_kp_roles_access.py::test_production_roles_are_assignable_and_not_managers` — копия констант. Дубль `test_admin_creates_employee_with_production_role`, `test_production_roles_are_not_project_manager`.
- `test_kp_roles_access.py::test_kp_category_role` — копия словаря. Дубль `test_kp_requests_create.py::test_mixed_selection_creates_two_requests_with_roles`.
- `test_kp_roles_access.py::test_pm_token_works` — PM получает 200 на `/projects`; дубль всего набора.
- `test_kp_pricing.py::test_net_price_returns_unrounded_decimal` — внутренняя деталь; «одно округление» закрыто `test_order_matters_single_rounding`.
- `test_kp_pricing.py::test_vat_then_unit_then_one_rounding` — деление точное, порядок не проверяет. Дубль `test_kp_offers.py::test_manual_price_confirmed_and_matrix`.
- `test_kp_pricing.py::test_selection_overrides_minimum` — дубль `test_kp_offers.py::test_selected_offer_overrides_minimum` (через эндпоинт).
- `test_kp_pricing.py::test_matrix_cells_and_minimum, test_matrix_empty_cell_for_offer_without_price, test_matrix_incompatible_reason_in_cell` — дубли эндпоинтных тестов матрицы в `test_kp_offers.py` и `test_kp_parser.py`.
- `test_kp_pricelist.py::test_write_requires_done` — дубль первого шага `test_retry_access_and_status`.
- `test_kp_requests_create.py::test_yolka_and_elka_are_different_positions_like_on_screen` — дубль общего файла примеров `test_collapse_key_matches_frontend_fixtures`.
- `test_kp_requests_create.py::test_split_selection_mixed_generic` — дубль `test_preview_groups_and_employee_counts_and_writes_nothing`.
- `test_kp_requests_create.py::test_can_view_and_work_kp` — матрица чистых функций, каждый кейс проверен эндпоинтами (кейс «admin» добавить в `test_cancel_by_author_and_head_not_by_other_pm_or_production`).
- `test_kp_clone_version_and_ref.py::test_task_processor_prompt_helper_drops_kp_ref` — однострочный псевдоним. Дубль `test_prompt_view_drops_kp_ref_and_source_no_without_touching_rows`.

### Б7. Документы, сводная, корректировки, снимок ИИ

- `test_documents_api.py::test_head_of_sales_can_write_foreign_document` — дубль `test_pm_writes_document_of_colleague`.
- `test_documents_api.py::test_readonly_query_param_cannot_grant_write` — параметра `read_only` у `apply` нет, FastAPI его отбрасывает. Дубль `test_write_blocked_while_task_processing`.
- `test_documents_api.py::test_locate_by_task_works_for_colleague` — дубль `test_pm_writes_document_of_colleague`.
- `test_documents_api.py::test_heartbeat_works_for_colleague` — дубль `test_heartbeat_reports_other_editor` (в нём поставить pm2 вместо head).
- `test_summary_section_document.py::test_colleague_opens_section_of_other_project, test_colleague_resolves_divergence` — один путь `can_edit()==True`. Дубль переписанного `test_head_of_sales_can_edit_foreign_section`.
- `test_summary_targets.py::test_has_section_targets_notices_a_single_target` — внутренний флаг; эффект виден в `test_xlsx_summary_targets.py::test_section_target_and_deviation_match_screen` и `test_file_without_targets_looks_as_before`.
- `test_summary_targets.py::test_removing_section_removes_its_target` — проверяет удаление раздела. Дубль `test_summary_section_document.py::test_removing_section_keeps_the_others`.
- `test_ai_baseline.py::test_snapshot_is_a_copy_not_a_reference` — пустой: после commit и `expire_all` вернётся 3000 и без `deepcopy`.
- `test_ai_baseline.py::test_read_returns_none_for_task_without_snapshot` — тривиальный `scalar_one_or_none`. Дубль `test_reconciliation.py::test_without_snapshot_says_so_and_breaks_nothing`.
- `test_reconciliation.py::test_signals_are_written_for_the_same_task` — проверяет журнал, а не сверку. Дубль `test_correction_signals.py::test_estimate_edit_keeps_price_source`.
- `test_list_edits_reach_estimate.py::test_input_file_document_does_not_touch_task_items` — ветка недостижима через API: раньше срабатывает `ensure_writable` → 409.

### Б8. RBAC, миграция смет, хранилище, прочее

- `test_estimate_migration_api.py::TestReport::test_summary_counts_present` — простая сумма. Дубль `test_report_classifies_every_estimate`.
- `test_estimate_migration_api.py::TestDiffExplained::test_row_without_numbers_is_described` — дубль `test_report_survives_rows_without_numbers`.
- `test_estimate_migration_api.py::TestOnlyRealDifferences::test_type_written_differently_is_not_a_difference, test_zero_and_empty_quantity_are_the_same` — дубль `test_formatting_difference_is_not_a_conflict`.
- `test_estimate_migration_api.py::TestOnlyRealDifferences::test_changed_price_is_still_a_difference` — дубль `TestDiffExplained::test_changed_price_is_not_order_only`.
- `test_estimate_migration_api.py::TestOnlyRealDifferences::test_sample_names_the_changed_field` — формулировка и формат числа. Дубль `test_sample_shows_both_values`.
- `test_migrate_estimate_items.py` — 9 тестов: дубли API-тестов через реэкспорт скрипта (`test_dry_run_changes_nothing`, `test_apply_creates_version_without_losing_numbers`, `test_apply_is_idempotent`, `test_matching_estimate_is_in_sync`, `test_conflict_is_reported_and_not_migrated`, `test_excluded_task_is_never_touched`); `TestDryRun::test_report_shows_money` (ожидание той же `items_total`); `TestConflicts::test_prefer_items_resolves_conflict_and_backs_up` (консольный путь, которого нет в админке); `TestTotalsMatchFile::test_rows_and_items_give_same_total` (дубль `test_estimate_single_source.py::TestRowItemConversion::test_round_trip_keeps_numbers`).
- `test_rbac_isolation.py::test_manager_sees_all_active_projects` — роль на списки не влияет. Дубль `test_pm_sees_all_active_projects`.
- `test_rbac_isolation.py::test_pm_can_get_own_project, test_manager_can_get_foreign_project` — дубль `test_pm_opens_foreign_project`.
- `test_rbac_isolation.py::test_pm_archives_foreign_project, test_pm_archives_foreign_task` — дубль `test_pm_archives_own_project` / `test_archive_loose_task_hides_from_active` (сделать в них владельцем pm2).
- `test_rbac_isolation.py::test_backfill_marks_existing_admin_archive_as_shared` — мёртвый флаг `is_shared`.
- `test_rbac_isolation.py::test_named_admin_login` — дубль `test_auth.py::test_login_valid`.
- `test_rbac_isolation.py::test_pm_can_estimate_from_own_source` — дубль `test_pm_estimates_from_foreign_source`.
- `test_rbac_permissions.py` — 9 тестов: `return None` / `return True` / `can_edit is can_access` / проброс в `is_manager` / дубль нормализации роли.
- `test_user_role_type_bug.py` — весь файл (3).
- `test_projects_router.py::test_patch_project` — дубль `test_rbac_isolation.py::test_pm_updates_foreign_project`.
- `test_projects_router.py::test_delete_project_as_admin` — дубль `test_delete_project_soft_deletes_for_any_user`.
- `test_basic.py::test_imports` — `JWT_ALGORITHM == "HS256"`, `MAX_FILE_SIZE_MB == 50`.
- `test_basic.py::test_hash_password` — дубль `test_auth.py` и `test_admin_resets_password`.
- `test_basic.py::test_generate_list, test_generate_smeta` — «вернулись bytes > 0»; `generate_smeta` никто не вызывает.
- `test_spa_catch_all.py::test_spa_path_returns_200` — дубль `test_spa_path_returns_html` (перенести туда проверку статуса).
- `test_schema_integrity.py` — весь файл (6), см. раздел 0.
- `test_storage_client_thread_safe.py::test_get_client_reuses_existing` — дубль `test_concurrent_get_client_builds_one_instance`.
- `test_storage_service.py::test_put_get_roundtrip` — проверяет фейк; круг покрыт тестами скачивания.
- `test_storage_service.py::test_get_missing_raises_storage_error` — дубль `test_load_bytes_reads_from_s3`.
- `test_storage_service.py::test_delete_object_idempotent` — свойство фейка.
- `test_storage_service.py::test_store_input_file_returns_key, test_store_result_file_returns_key` — проброс.

### Ф1. Редактор, свёртка, расчёты, выгрузка, сводная

- `analogsPanel › перед запуском показывает оценку объёма и предупреждает о плате` — формулировка confirm; само подтверждение проверяет «отказ ничего не запускает».
- `collapseRows › ключ группы` (4 теста) — все случаи уже в общем с сервером `collapseKey.fixtures.json`.
- `editorAsPage › окна поверх экрана не появляется` — класса `.de-overlay` в коде нет, проверка вечно зелёная.
- `editorClipboard › сообщает пользователю, что именно произошло` — точный текст уведомления.
- `editorCollapse › собирает одинаковые позиции в одну строку` — суммы текстом; дубль `collapseRows › складывает объём и стоимость`.
- `editorCollapse › одиночная позиция группой не становится` — CSS-класс; дубль `collapseRows`.
- `editorCollapse › число свёрнутых групп видно на кнопке` — подпись кнопки.
- `editorCollapse › расхождение цен внутри группы показывается словом` — текст; дубль `collapseRows › стоимость складывает по позициям`.
- `editorCollapse › отметка свёрнутой строки отмечает обе / снятая отметка группы гасит и её позиции` — дубль `collapseRows › выделение`.
- `editorCompactHeader` — весь файл (6).
- `editorDeductions › показывает, сколько строк спрячет` — подпись кнопки.
- `editorNumberFormat` — 13 тестов: формат денег, `displayValue` сметы и перечня, текст и классы таблицы.
- `editorRowSkills › подсветка строк` (6) — поле → CSS-класс один к одному; правило вычета держат тесты negativeQty.
- `editorSheetTabs › документ из одного листа показывает прежний единственный итог` — подписи; отрицательная проверка станет вечно зелёной.
- `estimateMigrationPanel` — 5: сводка через parentElement, названия смет, «60»/«58», `samples.what` ×2 — печать текста сервера, дубли.
- `estimateRecalc › buildNormComment` (3) — точный текст подсказки старой сетки.
- `exportKpRef › строка с kp_ref получает __kp_ref…` — дубль `kpRefActive › выгрузка: недействующая пометка…`.
- `genericKitRows › оба класса описаны в стилях редактора` — читает CSS-файл.
- `negativeQty › formatQty › целые остаются без хвостовых нулей` — формат показа.
- `summarySectionWarnings › в разделе сказано, что правки уходят в смету / на вкладке «Сводная» этой пометки нет` — формулировка.
- `summarySections › скрытые строки бланка в себестоимость не входят` — тавтология `subtotal + x > subtotal`.
- `summaryTargetsSheet › показывает отклонение … в рублях и процентах` — округление и знак показа; числа держит summaryTargets.
- `summaryTargetsSheet › превышение цели красное, экономия зелёная` — inline color.

### Ф2. Страницы, дашборд, канбан, КП, статус задачи

- `AdminHealthPanel › несколько стартов за час выделены тревожным цветом`, `› вчерашние 429 показаны спокойно` — только цвет.
- `BatchProgressBar › renders a progress bar…, shows "N из M" text, fills bar proportionally (100%), (25%)` — дубль aria-теста и inline width (весь компонент, похоже, мёртв).
- `batchProgress › parses the first batch, parses the last batch` — дубль `parses "Обработка батча N из M"`.
- `CardPageMerge › чат-уточнение убран из интерфейса` — проверяет удалённую функцию.
- `DashboardBalance › меньше суток запаса — предупреждает словами` — формат показа.
- `DashboardQueueEta` — 4: тексты `describeEta` в ячейке, дубли `eta.test.ts`.
- `TaskStatusEta` — 5 из 6: тексты прогноза, дубли `eta.test.ts`.
- `eta › грубая оценка помечается и объясняется`, `› подсказка показывает объём со склонением`, `› без позиции с бэкенда строка пустая` — тексты тултипа, дубль.
- `PriceLearning › пустая очередь объясняет, когда появится предложение` — текст.
- `PromptRulesCard › подписывает, кто включил правило` — текст.
- `ProjectDetail › Bug 3 → Фаза 6` (5) — подписи из справочников; бейджа «Не рассчитана» уже нет.
- `ProjectDetail › вычитает верхний отступ…` — sticky/top.
- `SystemNotifications › AC10: длинный список названий сворачивается до трёх` — формат текста.
- `TaskStatus › renders the paused block`, `› shows «На паузе» status label`, `› offers «Продолжить» instead of a paid recalculation` — подписи, дубли тестов вызова.
- `dashboardPulseModal` — 4: подписи карточек, «14 мин»/«1.5K»/«$1.75», «Задач нет».
- `kanbanPausedStage › стадия «Смета»: бейдж, пояснение и кнопка` — дубль «клик зовёт resumeTask».
- `kpPrices › подсвечена «цена из КП»`, `› без kp_ref — ни класса, ни подсказки` — дубли `kpRefActive.test.ts`.
- `kpPricesRefresh › нажатие тоже перечитывает список` — счётчик вызовов.
- `kpPricesRefresh › 409 предпросмотра` (на обвязке Harness) — дубль теста на настоящем редакторе.
- `kpPricesRefresh › разные коэффициенты работ и материалов названы оба` — формулировка.
- `kpRequestPage › состояние разбора видно в заголовке колонки` — тексты статусов.
- `productionRoles › у каждой назначаемой роли есть подпись`, `› обе роли производства назначаются` — тип `Record` и дубль.
- `projectTargetBadge › экономия показана зелёным` — цвет.
- `smetaCardStages › AC-4, AC-5 ×2, AC-6` — подписи, иконки, цифры.
- `smetaListStages` — 9 из 10: сетка, отступы, подписи, дубли `smetaCardStages`.
- `smetaListSticky` — весь файл (2).
- `smetaListSum › AC-7 сумма`, `› токены, доллары и время` — формат; связка и суммы проверены в других.
- `stageLostPositionsWarning › без предупреждения панель свёрнута` — дубль `CardPageMerge`.
- `stageUsageChips › нулевые допы не занимают место` — косметика.
- `usageMetrics › токены — порядок величины`, `› длительность — по-русски` — форматтеры показа.
- `__type-tests__/api-tasks-exports.ts` — весь файл.

---

## 2. Переписать

### Общие фикстуры — сделать до переписывания

1. **Процессор на настоящей БД:** задача в `db_session` + `TaskProcessor` на ней,
   мокается только ИИ (`patch_claude_create`), результат читается из БД
   (`estimate_store.read_items`, `task.progress_data`, `progress_log`). Образец —
   `test_chunks_watcher_session.py`, `test_cancel_removes_job.py`. Закрывает ≈40
   тестов в Б1, Б3, Б4, Б5, где сейчас `TaskProcessor(db=MagicMock())` и разбор
   `await_args` собственных методов.
2. **Прайс с векторами:** строки прайса и кеша с `embedding` →
   `price_service.load_cache(db_session)`, мокается только
   `embedding_service.generate_embedding(s)`. Вместо ручной подмены восьми
   приватных глобалов `price_service`.
3. **Окружение КП в одном модуле:** фикстура `env` и `_auth/_wipe/_upload/_offer`
   сейчас скопированы в 4–5 файлах.
4. **Фабрика ошибок Anthropic API** (баланс, 429, 5xx) в conftest: сейчас пять
   фабрик и три способа подменить клиент.
5. **Цикл воркера на `TestSessionLocal`** со статусами job вместо подмены
   `claim_one`/`run_job`/`_inflight_*`; `os.cpu_count` закреплён.
6. **Фронт:** хелпер «число из текста» (NBSP, копейки) и поиск строк по роли
   вместо `.de-grid`, `.rdg-cell`, `getAllByRole('checkbox')[1]`.

**Сделано 25.10.2026 (фаза 3).** Как пользоваться — в docstring каждого модуля.

| № | Что | Где |
|---|---|---|
| 1 | `processor_env` — задача и `TaskProcessor` на `db_session` | `backend/tests/helpers/processor.py` |
| 2 | `price_db` (+ `axis`, `similar`) — прайс и кеш с векторами, подменена модель эмбеддингов | `backend/tests/helpers/prices.py` |
| 3 | `make_kp_env` (+ `headers`, `upload_offer`, `create_offer`, `add_offer`, `add_price`) | `backend/tests/helpers/kp.py` |
| 4 | `api_error`, `balance_error`, `rate_limit_error`, `server_error`, `claude_message`; фикстуры `claude_api`, `api_sleeps` | `backend/tests/helpers/anthropic_api.py` |
| 5 | `worker_loop` — `_poll_loop` по-настоящему, ядра и память закреплены | `backend/tests/helpers/worker_loop.py` |
| 6 | `parseScreenNumber`, `numberAfter`, `numberNextTo`, `getGridRow`, `cellIn` | `frontend/src/__tests__/screenQueries.ts` |

Плюс `app_sessions` в `conftest.py` — собственные сессии приложения
(`AsyncSessionLocal()`) идут в тестовую БД. Отступление от плана в п. 5: цикл
воркера — не на `TestSessionLocal`, а на своей базе-файле («Найдено по пути»,
п. 11). Помеченные ниже «[x] фаза 3» пункты уже переписаны на эти фикстуры.

### Оставлено при удалении — переписать, затем удалить

Исполнители фазы 1–2 нашли, что эти тесты — не чистые дубли: в каждом есть
проверка, которой больше нигде нет.

- `test_estimate_batch_mode.py::test_resume_from_batch_collects_and_runs_step3` —
  единственная проверка, что цены пачки пишутся в кеш цен и что ошибочный кусок
  пачки пропускается. → перенести обе проверки в переписанный
  `test_batch_retry_parity.py`, затем удалить.
- `test_anthropic_admin_cost.py::TestCredential::test_no_keys_at_all` — удалить
  вместе с исправлением `test_returns_none_without_admin_key` (обнулить оба ключа).
- `test_kp_requests_create.py::test_can_view_and_work_kp` — только он проверяет,
  что производство не управляет запросом, даже числясь автором (ПМ сменили роль).
  → добавить в `test_cancel_by_author_and_head_not_by_other_pm_or_production`
  кейсы «admin» и «автор с ролью производства → 403», затем удалить.
- `AdminHealthPanel › несколько стартов за час выделены тревожным цветом` —
  единственная проверка строки «подобрано брошенных задач: N». → убрать проверку
  цвета, число оставить.
- `eta › грубая оценка помечается и объясняется` — последняя проверка флага
  «грубая оценка» (две другие удалены). → оставить флаг, убрать текст подсказки.

### Б1. Балансы, траты на API, метрики, дашборд

- `test_admin.py::test_admin_list_tasks_requires_admin` — сверяет текст «Недостаточно прав». → только 403.
- `test_admin_api_health.py::test_balance_detail_includes_status_and_message` — юнит приватного форматтера. → в `test_process_pauses_on_insufficient_balance`: 402 и текст API → «402» в progress задачи.
- `test_admin_api_health.py::test_api_health_no_balance_names_the_proxy` — слова в hint. → `verdict == "no_balance"` и `via_proxy`.
- **[x] фаза 3** `test_balance_pause.py::test_chunk_retry_reraises_balance_immediately` — считает вызовы своего `_call_claude_json`. → `patch_claude_create` с балансовой 400: один вызов `messages.create` и исключение.
- `test_balance_pause_hardening.py::test_submit_estimate_batch_checkpoints_before_submit` — db=MagicMock, аргументы `_save_progress_data`. → db_session; после исключения в БД `_stage == "claude_partial"`.
- `test_balance_pause_hardening.py::test_fix_empty_prices_saves_paid_batches_before_balance_pause` — замоканы БД и свои методы. → db_session, второй вызов ИИ — баланс; читать рабочую версию сметы.
- `test_cost_sync_pause.py::test_401_pauses_too` — приватный глобал. → parametrize 401/403 с `test_403_pauses_for_a_day`: «второй тик не ходит».
- `test_anthropic_admin_cost.py::test_returns_none_without_admin_key` — при заданном `ANTHROPIC_API_KEY` уходит настоящий HTTP. → обнулить оба ключа.
- `test_anthropic_admin_cost.py::test_http_error_propagates` — тривиально. → httpx-ответ 403, в тексте ошибки «HTTP 403» — маркер паузы worker (закрывает контракт из «Найдено по пути», п. 4).
- `test_api_cost_pricing.py::TestBatchDiscount::test_web_search_not_discounted` — убрать строку-копию константы `WEB_SEARCH_COST_PER_REQUEST`, число $0.10 оставить.
- **[x] фаза 3** `test_api_rate_limit_counter.py::test_rate_limit_is_recorded` — приватный `_record_rate_limit`. → `call_claude` с одним 429, затем `GET /admin/queue-health`: `hits_1h == 1`, `max_wait_s_24h == 60`.
- **[x] фаза 3** `test_api_rate_limit_counter.py::test_recording_failure_never_raises` — приватный метод. → через `call_claude`: 429, затем успех при сломанной сессии → «ok».
- **[x] фаза 3** `test_api_rate_limit_counter.py::test_balance_error_is_not_counted` — monkeypatch своего метода. → настоящий 429 с «credit balance», строки `system_events` нет.
- `test_rate_limit_retry.py::test_default_sleep_used_when_no_retry_after_header, test_retry_after_above_minimum_uses_header_value, test_backoff_minimum_60s_for_first_429, test_exponential_backoff_increases_per_consecutive_429, test_backoff_capped_at_900s` — пять тестов одной формулы со слабыми `any(s >= X)`. → один parametrize «retry-after → точный список sleep».
- `test_rate_limit_retry.py::test_rate_limit_sleep_counted_in_cumulative_timeout` — бюджет не проверяется. → sleep 0.1 с при бюджете 0.05 с → TimeoutError, один вызов.
- `test_usage_extra_logged.py` — все 4: шпионят за kwargs своих функций. → `test_app` + `patch_claude_create` с usage; строка `ApiCallLog` (task_id, is_extra) в БД.
- `test_card_usage_api.py::test_queries_do_not_grow_with_card_count` — подмена `usage_for_tasks`, `calls == [5]`. → считать SQL через event engine для 1 и 5 карточек.
- `test_system_notifications.py::test_manager_sees_all_tasks, test_pm_sees_all_tasks_too` — один сценарий. → parametrize по роли.
- `test_resume_poller_balance_gate.py::test_failed_check_marks_progress_message, test_non_balance_error_reported_separately` — фразы. → parametrize: сырые код и текст API, `progress_log` не вырос, обрезка до 500.
- `test_resume_poller_balance_gate.py::test_no_event_when_nothing_claimed` — подмена `_claim_and_enqueue`. → настоящая гонка: pinger сам переводит задачу в pending.

### Б2. Воркер, очередь, ETA, возобновление

- `test_worker_memory_report.py::test_memory_above_threshold_recorded` + `test_admin_queue_health_resources.py::test_worker_memory_reported` — запись и показ проверены порознь, payload собран руками. → сквозной: `_report_memory_if_high(1500.5)` → `GET /admin/queue-health`.
- `test_worker_crash_recovery.py::test_announce_start_records_event_and_requeues` + `test_admin_worker_restarts.py::test_single_start_is_reported_calmly` — то же для события старта. → `_announce_start(slots=2)` → `GET /admin/queue-health`: starts_1h=1, slots=2, requeued=1.
- `test_eta_service.py::test_duration_is_rough_until_calibrated, test_history_calibrates_the_rate, test_outlier_does_not_break_the_median, test_calibrated_rate_is_clamped_to_sane_range` — ожидания выведены из дефолтов. → проверять прогноз по истории: «100 позиций за 1240 с» → ≈1240, rough=False.
- `test_eta_service.py::test_forecast_reads_progress_scalars_without_loading_the_whole_json` — приватный `_load_active_snapshots`. → публичный `queue_forecast(db, now=NOW)`.
- `test_cancel_removes_job.py::test_cancel_pending_jobs_removes_queued` — регресс был в эндпоинте, тест его не поймает. → `POST /tasks/{id}/cancel`: job `cancelled`, `claim_one` → None.
- `test_paused_resume_dead_end.py::test_resume_paused_without_checkpoint_restarts, test_resume_paused_null_progress_data` — копии. → parametrize по progress_data.
- `test_paused_resume_dead_end.py::test_resume_paused_batch_pending_goes_to_processing, test_resume_failed_batch_pending_goes_to_processing` — копии. → parametrize по статусу.
- `test_restart_no_double_run.py::test_supersede_removes_queued_and_running` — повторяет эндпоинтный. → добавить queued-job в `test_restart_supersedes_old_job`, сервисный убрать.
- `test_resume_poller.py::test_find_resumable_paused_ids_filters` — приватная выборка. → через `resume_paused_tasks`.
- `test_resume_poller.py::test_claim_flips_paused_to_pending_once` — `_claim` только из тестовой ветки. → два тика `resume_paused_tasks` подряд: второй [], job одна.
- `test_worker_admission.py::test_brake_on_by_container_ratio` — срабатывает через запас, не долю. → `WORKER_MEM_MIN_FREE_MB=0`.
- `test_worker_admission.py::test_slots_from_available_memory_on_shared_host, test_slots_limited_by_container_memory, test_slots_keep_configured_when_memory_is_plenty, test_slots_unchanged_when_ratio_disabled, test_slots_unchanged_without_cgroup` + `test_worker_duplicate_run_guard.py::test_slots_limited_by_cpu` — `os.cpu_count` не закреплён. → одна таблица с закреплённым `cpu_count`.
- **[x] фаза 3** `test_worker_admission.py::test_poll_loop_skips_claim_when_staggered` + `test_worker_memory_brake.py::test_poll_loop_skips_claim_when_braked` — список вызовов и `sem._value`. → parametrize на TestSessionLocal: queued-job остаётся queued.
- **[x] фаза 3** `test_worker_admission.py::test_started_at_recorded_and_cleaned` + `test_worker_duplicate_run_guard.py::test_inflight_task_ids_cleaned_after_run` — приватные `_inflight_*`. → следующую job той же задачи берут сразу.
- `test_worker_admission.py::test_burst_claims_are_stopped_after_first` — вызовы подменённого `claim_one`. → 4 queued-job и медленный run_job: в running ровно одна.
- **[x] фаза 3** `test_worker_duplicate_run_guard.py::test_poll_loop_drops_duplicate_and_does_not_run_it` — аргументы вызовов. → реальная БД: дубль `superseded`, run_job не стартовал.
- `test_worker_duplicate_run_guard.py::test_embedding_threads_leave_a_core` — повторяет формулу. → cpu_count=4, EMBEDDING_THREADS=0 → ровно 3.
- `test_worker_price_cache_warmup.py::test_warm_price_cache_loads, test_ensure_price_cache_retries_when_empty` — вызовы `load_cache`. → тестовая БД: `_ensure_price_cache()` → `is_cache_loaded()`.
- `test_task_worker_heartbeat.py::test_none_for_other_task_job, test_queued_job_has_no_heartbeat_yet, test_finished_job_is_not_a_live_signal` — сервис в обход эндпоинта. → parametrize `test_status_endpoint_null_without_job`.
- `test_memory_snapshot.py::test_snapshot_ratio_none_without_limit` — точная форма `as_dict()`. → оставить `ratio is None`.
- `test_task_timing.py::test_restart_resets_started_at` — `>=` проходит и без сброса. → started_at на час назад, после processing свежее.

### Б3. Обработка ИИ: Batch API, чанки, оптимизация, PDF

- `test_batch_poller.py::test_ended_runs_resume_and_completes, test_in_progress_is_noop, test_ended_resume_failure_marks_failed` — замокан свой `update_status`. → parametrize по статусу опроса, статус и `_stage` из БД.
- `test_batch_retry_parity.py::test_resume_from_batch_fills_missing_positions, test_resume_from_batch_skips_retry_when_all_priced, test_resume_from_batch_checkpoints_before_failing` — db=MagicMock, аргументы step3. → db_session, мок `collect_claude_batch` и ИИ; цены в смете и `progress_data` в БД.
- `test_claude_batch.py::test_web_search_tool_has_max_uses_cap` — константа. → `max_uses` в `params["tools"]` в `test_build_batch_request_shape`.
- `test_claude_batch.py::test_collect_claude_batch_keys_by_custom_id` — заглушка формы SDK. → errored-строка в JSONL MockTransport в `test_batch_results_proxy.py`.
- `test_claude_batch.py::test_batch_entry_logged_once, test_batch_entry_not_logged_twice, test_regular_call_logged_even_if_identical` — фейк-сессия отвечает «запись есть» на любой SELECT. → тестовая БД: batch дважды → 1 строка, обычный дважды → 2.
- `test_estimate_batch_mode.py::test_submit_estimate_batch_writes_checkpoint` — аргументы мока. → db_session, мок `submit_claude_batch`; `progress_data` в БД.
- `test_processing_mode_router.py` — все 5 на приватную функцию из пяти строк. → один parametrize, лучше через `POST /tasks`.
- **[x] фаза 3** `test_chunk_tally_visible.py::test_milestone_goes_to_history, test_milestone_silent_without_stage, test_pause_message_carries_tally, test_interrupt_message_without_tally_is_unchanged` — мок `update_progress`. → db_session: цифры 4 и 9 в `task.progress_log`.
- `test_chunks_progress_deadline.py::test_deadline_scales_with_batch_size` — копия формулы. → `large > small` и заметно больше штатной длительности.
- `test_chunks_progress_deadline.py::test_progress_does_not_pollute_history_log` — «не вызван». → db_session: `progress_log` пуст, `progress_message` обновлён.
- `test_truncated_response.py::test_truncated_response_is_still_logged` — замокан `_log_api_call`. → строка ApiCallLog с web_search_requests=4.
- `test_truncated_response.py::test_truncated_batch_is_split_in_half_and_priced` — БД и `write_items` замоканы. → смета в db_session, эндпоинт fix-empty-prices: цены в версии, три вызова.
- `test_list_truncated_split.py::test_truncated_chunk_is_split_and_stage_completes, test_bottom_of_recursion_reports_lost_positions, test_pdf_truncated_chunk_is_split` — подменены шесть приватных методов. → db_session, мок ИИ; позиции из EstimateVersion, предупреждение из `progress_log`.
- `test_lost_positions_reported.py::test_warning_names_positions_ai_skipped, test_no_warning_when_ai_returned_everything` — тот же набор моков. → так же.
- `test_list_from_project_resume.py::test_resume_pass1_skips_done_chunks, test_resume_pass1_done_skips_pass1_entirely, test_balance_error_in_pass1_propagates` — замоканы свои методы. → db_session + `store_input_row`, мок ИИ.
- `test_estimate_resume_checkpoint.py::test_save_claude_partial_writes_checkpoint` — форма dict. → круговой: после чекпоинта шаг 2 шлёт в ИИ только непосчитанные.
- `test_optimization_parallel.py::test_process_single_item_work_exception_returns_none_price, test_process_single_item_material_exception_returns_none_price` — один сценарий на приватной функции. → `_run_optimization_background` на db_session: «Ошибка поиска», задача completed.
- `test_optimization_parallel.py::test_checkpoint_skips_already_done_items` — фильтр переписан в тесте. → `_run_optimization_background` с `partial_results`: ключ (лист, строка).
- `test_optimize_endpoint.py::test_analyze_returns_items` — только ключи. → Кирпич М150 в items, total_analyzed=1, coverage_pct=100.
- `test_optimize_endpoint.py::test_run_starts_background` — только ответ. → Job «task.optimize» в БД, task.status=processing.
- `test_pdf_exporter.py::test_pdf_html_contains_itogo_row` — надпись. → сумма 1 500 000 в итоговой строке.

### Б4. Разбор файлов и xlsx

- `test_grand_position_not_total.py::test_quantity_of_equipment_is_the_total_column`, `test_grand_resource_rows.py::test_material_position_survives` — числа в «Количестве» и «всего» совпадают, тест разницы не видит. → фикстура в раскладке ГРАНД, разные числа, ожидать «всего» (см. «Найдено по пути», п. 1).
- `test_source_no_all_stages.py::test_summary_section_snapshot_keeps_number` — тест сам делает `list(rows)`. → через эндпоинт создания сводной.
- `test_source_no_all_stages.py::test_optimizer_column_mapping_ignores_new_column` — приватные `_find_header_row`, `_map_columns`. → публичный `parse_estimate_xlsx(generate_estimate_xlsx(…))`.
- `test_multisheet_estimate.py::TestExactNumbers::test_screen_formula_agrees_per_sheet_and_overall` — копия фронтовой формулы внутри теста. → vitest на `calcEstimateTotals` с теми же ITEMS: 13390 / 19055 / 32445.
- `test_multisheet_estimate.py::TestRoundTrip::test_material_is_not_linked_to_a_work_from_another_sheet` — упасть не может. → лист 2 начинается с материала.
- `test_multisheet_estimate.py::TestStep3KeepsSheets::test_every_branch_keeps_the_sheet`, `test_negative_quantity.py::test_step3_negative_item_has_no_prices` — БД MagicMock. → db_session и fake_s3, шаг 3, `progress_data["items"]` и файл.
- `test_negative_quantity.py::test_price_lookup_skips_negative_qty` — подменён `_price_svc`. → прайс в БД и `patch_claude_create`: у вычетов нет цены.
- `test_multisheet_list.py::TestChunksStayWithinSheet::test_items_returned_by_ai_get_the_chunk_sheet, test_existing_sheet_is_not_overwritten, test_single_sheet_file_leaves_items_unmarked` — приватные помощники. → обработка перечня по двухлистовому файлу.
- `test_xlsx_exporter.py::test_xlsx_tasks_sheet_rows, test_xlsx_slot_sheet_with_file_has_hyperlink, test_xlsx_total_row_summary_counts` + `test_export.py::test_export_xlsx_is_valid_workbook` — генератор на фейках, эндпоинт на пустом проекте. → `GET /projects/{id}/export` по проекту с задачами.
- `test_xlsx_optimizer.py::test_parse_estimate_xlsx_returns_items` — `isinstance`. → точные цены и total.
- `test_xlsx_optimizer.py::test_get_top_items_covers_threshold, test_get_top_items_filters_categories` — проходят на «вернуть всё» и пустом списке. → точные выбранные имена.
- `test_xlsx_optimizer.py::test_generate_optimized_xlsx_adds_columns, test_generate_optimized_xlsx_has_comparison_sheet` — ни одного значения. → значения в строках и в листе «Сравнение».
- `test_xlsx_summary.py::test_fixed_row_has_both_costs, test_manual_row_has_both_costs, test_contingency_has_both_costs, test_subtotal_has_both_costs` — одна проверка четыре раза. → parametrize.
- `test_xlsx_summary.py::test_single_value_rows_are_merged` — объединение ячеек — вёрстка. → только значения, в тот же parametrize.

### Б5. Цены, единицы, эталон, эмбеддинги

- `test_price_cache_no_full_reload.py::test_embedding_task_does_not_reload_whole_cache` — MagicMock-сессия и `assert_not_awaited`. → строка PriceCacheWork в БД, проверять `embedding`.
- **[x] фаза 3** `test_price_match_preview.py::test_match_found, test_just_below_threshold_suggests_threshold, test_nothing_similar` — подмена приватных кешей. → parametrize по похожести на векторах в БД (фикстура 2).
- **[x] фаза 3** `test_price_service_embedding.py` — 5 тестов подбора выше и ниже порога. → два теста на публичном `batch_embedding_match_*` (фикстура 2).
- `test_price_unit_match.py` — 12 тестов правила №8 (прайс ×5, кеш ×2, шаг 3 ×5) на MagicMock-БД с результатом из `await_args`. → фикстура 1, итог через `estimate_store.read_items`. **Фаза 3:** переписаны 2 из 12 (`test_cena_za_tonnu_…`, `test_ii_vernul_cenu_za_meshok_…`) — образец для остальных.
- `test_price_unit_reprice.py::test_dobor_ne_pishet_cenu_za_meshok, test_dobor_pereschityvaet_svodimuyu_edinicu` — подменены свои `read_items`/`write_items`. → db_session, `fix_empty_prices`, parametrize.
- `test_price_unit_reprice.py::test_promt_pereschyota_trebuet_edinicu_pozicii` — `inspect.getsource`. → `POST /tasks/{id}/estimate-items/{i}/reprice`: цена за мешок → пусто и пометка (закрывает непокрытую кнопку «Цена»).
- `test_unit_normalizer.py::TestNormalizeUnitQuantity` — 15 тестов по строке на кейс. → строками в таблицы `test_unit_multiplier_with_tail.py`.
- `test_reference_price_api.py::test_apply_reloads_price_cache` — счётчик шпиона. → после apply цена находится через `_exact_match_work`.
- `test_reference_price_duplicates.py::test_candidates_carry_id_and_source, test_no_vectors_gives_empty_list, test_batch_search_asks_the_model_once, test_batch_without_vectors_gives_empty_row_per_name` — восемь приватных глобалов. → фикстура 2.
- `test_reference_price_parse.py::test_plan_shows_every_price_that_will_be_erased, test_plan_marks_new_position_as_add, test_plan_blocks_incompatible_unit, test_plan_shows_material_price_that_will_be_replaced` — сервис в обход `/prices/reference/preview`. → через preview.
- `test_reference_price_real_format.py::test_conflict_inside_one_section_is_still_reported` — один лист, разведения нет — копия соседнего. → второй лист.
- `test_generate_embeddings_endpoint.py::test_generate_embeddings_status_pending_to_ready, test_generate_embeddings_works_without_uploaded_file, test_generate_embeddings_for_web_search_cache` — `updated` = `len(rows)`, запись векторов не проверена. → `embedding` и `embedding_status` в БД.
- `test_catalog_permissions.py` — 8 копий «pm → 403, руководитель/админ — нет». → два parametrize.
- `test_coefficient_and_percentages.py::test_xlsx_applies_coefficient_to_prices, test_version_export_matches_editor` — жёсткие координаты ячеек. → колонка по заголовку, числа оставить.
- Перенос без переписывания: 3 оставшихся кейса `TestMinPriceRule` → `test_price_min_kp.py`; `test_normalize_m100_not_equals_m50` → `test_normalize_name_collisions.py`.

### Б6. Запрос КП

- `test_kp_pricing.py::test_with_vat_without_rate_uses_default_22` — убрать `assert DEFAULT_VAT_RATE == 22`, поведение 1220 → 1000 оставить.
- `test_kp_requests_create.py::test_known_type_in_wrong_category_is_422, test_row_in_two_groups_is_422, test_missing_row_is_422, test_empty_groups_is_422` — четыре одинаковых. → parametrize + «ни одного KpRequest не создано».
- `test_kp_requests_create.py::test_purge_other_cards_untouched` — несуществующий id. → через эндпоинт: две карточки, одна удалена, вторая цела.
- `test_kp_requests_create.py::test_read_uploads_checks_count_before_reading, test_read_uploads_stops_at_limit, test_read_offer_upload_stops_at_limit` — точный список вызовов `read`. → parametrize: код 400/413 и «прочитано ≤ лимит+1».
- **[x] фаза 3** `test_kp_offers.py::test_complete_waits_for_running_parse` — точная формулировка. → `"ООО Металл" in detail`.
- `test_kp_parser.py::test_worker_knows_parse_job, test_upload_with_file_queues_parse_in_same_transaction` — строка `JOB_KIND` и форма payload. → загрузить КП, прогнать job через `worker.HANDLERS`, КП `parsed`.
- `test_kp_parser.py::test_pdf_goes_as_document_block, test_image_goes_as_image_block, test_xlsx_goes_as_text` — kwargs своей обёртки. → parametrize через `patch_claude_create`: блок в `messages`.
- **[x] фаза 3** `test_kp_apply.py::test_history_entry_and_no_correction_signals` — убрать проверку текста описания.
- `test_kp_clone_version_and_ref.py::test_create_manual_version_route_response_unchanged` — `set(body) == {…}` замораживает схему. → номер версии, строки, коэффициент, task_type в БД.
- Попутно: ослабить `version_display_name == "Цены из КП"` в `test_material_and_work_prices_go_to_new_version`.

### Б7. Документы, сводная, корректировки, снимок ИИ

- `test_documents_api.py::test_meta_versions_carry_expense_percentages` — только наличие ключей. → версия с `overhead_pct=5`, meta отдаёт её, а не 3%.
- `test_documents_api.py::test_history_is_trimmed_and_old_snapshots_dropped` — в обход эндпоинта. → 25 «Применить», GET history, откат старой — 422, свежей — 200.
- `test_summary_section_document.py::test_head_of_sales_can_edit_foreign_section` — не на самой слабой роли. → «Применить» от pm2.
- `test_correction_signals.py::test_added_and_removed_rows_are_signals, test_added_and_removed_rows_counted_separately` — один сценарий. → один тест через эндпоинты: stats и лента `/corrections`.
- `test_correction_signals.py::test_automatic_operations_are_not_signals` — сам подставляет `operation_type`. → ручная правка, затем `POST /history/{id}/revert` и `/price-units-check`: сигналов не прибавилось.
- `test_prompt_rules.py::test_rules_read_once_per_run` — имя обещает то, чего тест не проверяет. → включить второе правило после загрузки, `system` не изменился.
- `test_list_edits_reach_estimate.py::test_saved_rows_update_task_items, test_rows_of_foreign_format_do_not_wipe_task_items` — приватная `_sync_task_items`, правило №6 не защищено. → `POST /documents/{card}/completeness/apply`, затем `task.progress_data['items']`.
- `test_reconciliation.py` — сравнение `"3000.0"` строками в 6 тестах. → числами.

### Б8. RBAC, миграция смет, хранилище, прочее

- `test_estimate_migration_api.py::test_report_shows_both_totals_for_conflict, test_report_explains_conflict` — итоги «> 0 и не равны». → `14420.0`, `13501.24`, `diff_count == 1`.
- `test_estimate_migration_api.py::TestApply::test_apply_creates_missing_version` — только `len(rows)`. → имена строк и `price_work == 1000.0`.
- `test_estimate_migration_api.py::TestResolve::test_both_sides_saved_to_history` — пройдёт на мусоре. → точные цены обеих сторон.
- `test_estimate_migration_api.py::TestPermissions::test_manager_cannot_read_report, test_manager_cannot_apply` — `/resolve` не покрыт. → parametrize по трём эндпоинтам.
- `test_migrate_estimate_items.py::TestCreateVersions::test_task_without_items_is_skipped` — единственный уникальный. → в API-файл: `/apply` → статус `empty`.
- (Если функцию «Перевод смет» удалим — см. «Найдено по пути», п. 2 — эти тесты уходят вместе с ней.)
- `test_task_history.py::test_revert_no_dependents_executes_immediately` — только флаг `reverted`. → `estimation_status == "estimated"`, слот `optimized` удалён.
- `test_task_file_slots.py::test_upload_estimate_slot_damaged_xlsx_returns_warning` — `"warning" in data` истинно всегда. → `assert data["warning"]`.
- `test_task_file_slots.py::test_detach_task_from_project` — None → None. → привязать, отвязать, `project_id` в БД.
- `test_rbac_isolation.py::test_pm_archived_list, test_pm_sees_and_opens_shared_company_data` — держатся на мёртвом `is_shared`. → один тест без него.
- `test_rbac_isolation.py::test_backfill_moves_shared_owned_to_admin_archive` — убрать проверки `is_shared`.
- `test_projects_router.py::test_list_projects` — только ключи. → точные счётчики и `total_cost`.
- `test_workflow_cards_etag.py::test_workflow_cards_etag_304` — магическая строка Cache-Control. → после изменения карточки 200 и новый ETag.
- `test_auth.py::test_login_wrong_password, test_login_password_only_rejected` — текст `detail`. → только статус.
- `test_basic.py::test_parse_xml` — проходит почти на любом выводе. → XML с namespace, точные значения.
- `test_spa_catch_all.py::test_spa_path_returns_html` — падает на чистом клоне без `frontend/dist`. → путь к index.html в настройку, tmp-файл в тесте.

### Ф1. Редактор, свёртка, расчёты, выгрузка, сводная

- `coefficient › с коэффициентом видно, какой он и на что действует` — подпись. → ждать загрузку по data-row-count, цена 1050.
- **[x] фаза 3** `coefficient › итоги считаются по ставкам версии, если у неё свои` — подпись и строка с копейками. → нормализованное число 9800.
- `coefficient › правка ячейки при коэффициенте сохраняет исходную цену` — сам зовёт `fromGrid`. → «Применить», `price_work=1500` в payload.
- `collapseRows › служебные поля позиций свёрнутой строке не наследуются` — ключей `__*` ровно три. → отсутствие `__sheet`, `__base_price_*`.
- `editorCollapse › вкладки листов отключаются, итог по всему документу` — `.de-totals` и строка. → tablist=null, итог числом.
- `editorCollapse › общий объём не редактируется` — классы. → после двойного клика нет поля ввода.
- `editorCollapse › вставка из буфера отклоняется с подсказкой` — фраза и `isDirty`. → строки не изменились, «Применить» недоступна.
- **[x] фаза 3** `editorDeductions › вычет не попадает в общий объём свёрнутой группы` — `toContain('20')` выполняется при ошибке. → ячейка объёма = 20.
- `editorDraft › после смены вкладки вставка не уходит в чужую строку` — без выбранной ячейки регрессию не воспроизводит. → выбрать ячейку, вставить.
- `editorDraft › вставка в документ только для чтения игнорируется` — пройдёт и без `canWrite`. → кликнуть ячейку перед вставкой.
- `editorDraft › исходный файл заказчика открывается только на просмотр` — только фраза. → нет «Применить», правка не меняет строки (правило №2).
- `editorLinkState › сообщает открытую версию и вкладку наружу`, `› смена вкладки уходит наружу`, `editorSheetTabs › открытый лист уходит наружу` — точный объект. → `expect.objectContaining`.
- `editorPerf2000 › подготовка строк и колонок укладывается в бюджет`, `› поиск и итоги считаются быстро` — абсолютные мс в jsdom. → `vitest bench` вне обычного прогона или рост 2000→8000.
- `editorSheetTabs › итог показывает и лист, и весь документ` — подписи. → числа итогов.
- `estimateMigrationPanel › расхождение показывает оба итога…` — фраза. → два итога и число 4.
- `estimateMigrationPanel › после применения отчёт перечитывается` — счётчик GET. → второй ответ с другими числами на экране.
- `estimatePriceActions › в разделе сводной кнопок нет` — отрицательная текстовая проверка. → итог 4000, а не 4120.
- `estimatePriceActions › счётчик считает пустые цены и не считает вычет` — подпись. → юнит `hasEmptyPrice`.
- `exportBuilder › цены уходят с коэффициентом — ровно как на экране` — тавтология. → `rowsFromEditor(estimateAdapter.toGrid(stored, {coefficient}))` → 1050.
- `formatError` — 16 тестов с точными фразами. → один it.each «сырой текст → категория» + инварианты.

### Ф2. Страницы, дашборд, канбан, КП, статус задачи

- `AdminHealthPanel › показывает цифры памяти и число слотов` + `› нет цифр памяти…` — фразы целиком. → it.each: числа видны, нет «null».
- `AdminHealthPanel › свежие 429 выделены` — цвет. → числа и признак посредника.
- `DashboardBalance › показывает остаток и на сколько дней хватит` — формат «$450,00». → 450, 30, 45 в блоке.
- `DashboardBalance › без официальных данных подпись нейтральна` — текст. → it.each: кнопка активна/выключена.
- `DashboardBalance › удачная сверка не оставляет сообщения об ошибке` — отрицательная по тексту. → отсутствие блока ошибки по role/testid.
- `DashboardQueueEta › ожидающая задача показывает и время старта` + `› показывает позицию` — → один тест связки.
- `PriceLearning › показывает расхождение словами и не пишет в прайс сам` — правило №9 смешано с форматом. → «accept не вызван».
- `ProgressCounter › clamps overflow (done > total) to 100%` — `style.width`. → aria-valuenow/max.
- `ReconciliationPanel › не приписывает человеку то, что изменил сервис` — CSS-классы. → автор «сервис» в ячейке.
- `SidebarHoverExpand › не сворачивается, если открыта форма…`, `› Закреплённое меню › не сворачивается…` — 300 мс при задержке 200. → `vi.runAllTimers()`.
- `SystemNotifications › AC12: курсор сдвигается…` — второго опроса нет. → докрутить таймер: курсор 6, тост один.
- `SystemNotifications › AC12: событие без названий…` — точная строка. → `toContain('3')`.
- `TaskStatus › shows progress_message … processing` + `… pending` — → it.each.
- `TaskStatus › resume button visibility` — 6 тестов по видам чекпоинта. → it.each.
- `dashboardPulseModal › время не выдумывается…` — ровно три «—». → нет «0 мин» и «$0».
- `eta › считающаяся задача — время по часам и относительно` — регэксп уже падал после 23:20. → `toContain('через 40 мин')`.
- `eta › место в очереди` — 3 теста. → it.each.
- `kanbanPausedStage › после успешного продолжения доска перечитывается` — вызов `fetchCards` замоканного стора. → настоящий стор, мок `getWorkflowCards`.
- `kanbanPausedStage › стадия «Полнота»/«Перечень»/«Оптимизация»` — копии. → describe.each.
- `kpPrices › кнопка › неактивна…` (4) — один предикат. → it.each.
- `kpPrices › окно › показывает было → стало…` — формат. → цены, поставщик, флаг.
- `kpPricesRefresh › ×1,2 — пояснение видно; ×1 — нет` — фраза. → есть/нет `kp-apply-coefficient`.
- `kpPricesRefresh › редактор › 409 предпросмотра…` — читает стор. → версия по экрану.
- `kpRequestPage › цена в единице КП и приведённая видны` — формат. → оба числа.
- `kpRequestPage › ответ фонового опроса… не перетирает` — шпион на `ms === 30_000`. → fake timers, `advanceTimersToNextTimer`.
- `optimizationManualStart › клик по кнопке запускает задачу этапа`, `› «Использовать смету» только прикрепляет` — мок своего стора (правило №20). → настоящий стор, мок `api/workflowCards`: какой эндпоинт ушёл.
- `projectTargetBadge › показывает цель и превышение красным` — цвет. → «+50 000», «+20%».
- `requestKp › разбивает позиции на материалы и работы…` — формулировки ролей. → позиции в группах.
- `requestKp › показывает категорию, статус, кто взял…` — подписи. → подсчёт «КП получены: N».
- `smetaCardStages › AC-8: заблокированная стадия не раскрывается` — по тексту тултипа. → по роли.
- `stageUsageChips › AC-1: текущая стадия показывает свои токены…` — только формат. → две стадии, числа в своей секции.
- `usageMetrics › незаполненные стадии не превращаются в нули времени` — имя противоречит проверке. → переименовать.

---

## 3. Спорно — решает пользователь

По умолчанию делаю по рекомендации.

| # | Что | Тестов | Рекомендация |
|---|---|---|---|
| А | Синий курсив строки материала в xlsx (`test_xlsx_material_rows.py`) | 7 | Оставить одним parametrize «по каждому генератору: материал курсивом, работа нет»; убрать кегль, шрифт, рамку, `number_format`; значения ячеек — отдельными тестами |
| Б | Заливка «цена из КП» в xlsx (`test_kp_xlsx_marks.py`) | 6 | Оставить: в файле это единственное выражение правила №22; убрать сравнение констант цветов |
| В | Цены моделей `_COST_PER_TOKEN` (`test_api_cost_pricing.py`) + `parse_cost` в КП | 5 | 4 теста → один parametrize с точными числами (правило №13); в `parse_cost` — `cost_usd == parse_cost > 0` |
| Г | Колонка «№ в исходной смете»: полный список шапки без номеров (2 бэк), колонка первая (3 фронт) | 5 | Проверять только наличие/отсутствие `SOURCE_NO_HEADER` и что колонка первая |
| Д | Числа в примечаниях: `test_unit_compat` ×2, `test_material_kits` ×2, обрезка 20 номеров, `referenceImport` | 6 | Оставить, проверять числа и единицы, а не формулировку |
| Е | Подсветка строк по префиксу примечания: `genericKitRows` ×8, `priceUnitMismatchRow` ×3, «включает материалы» | 12 | Оставить: класс — результат функции распознавания, а не вёрстка (правила №5, №8, №22) |
| Ж | Префикс `«КП: »` (`test_prefix_is_fixed`) | 1 | Оставить только строку с `kp_contractor` |
| З | Лимит файла КП 50 МБ (`test_kp_file_limit_is_own_50_mb`) | 1 | Оставить: ловит реальный баг d4b5e17, поведенческим тестом не поймать |
| И | Нет `onupdate` у `updated_at` | 1 | Оставить: на него ссылается правило №15 |
| К | `WORKER_CONCURRENCY == 1` (`test_default_slots_are_sequential`) | 1 | Переписать: при `WORKER_CONCURRENCY=2` слоты берутся из настройки |
| Л | Стор сводной не правит строки разделов (имя метода) | 1 | Удалить |
| М | `status-colors-coverage.ts` | 1 | Заменить на `satisfies Record<TaskStatus, …>` у четырёх констант, файл удалить, поправить правило №20 |
| Н | «Екатеринбург» в промптах веб-поиска | 2 | Оставить, добавить в parametrize остальные 3 промпта с регионом |
| О | Промпт без правил «байт в байт» (`test_prompt_rules`) | 2 | Оставить (правило №21, метки кеша), переписать через `patch_claude_create` |
| П | Высота таблицы «на весь экран» (`gridFullHeight`) | 6 | Оставить: чистая геометрия, ловит реальный баг |
| Р | Прочерк без цели, отклонение по объекту (`summaryTargetsSheet`) | 3 | Оставить парой (правило №16) |
| С | Объём 0,61 не округляется (`formatDecimal`, `formatQty`) | 2 | Оставить один кейс |
| Т | Предупреждение «станет главнее прайсов» (`PriceLearning`) | 1 | Оставить: единственная защита предупреждения перед необратимым действием |
| У | Текст подсказки о перезапусках воркера | 1 | Убрать проверку текста, `starts_1h` оставить |
| Ф | `test_spa_routing` (render.yaml) | 1 | Зависит от Render: удаляем render.yaml — удаляем и тест |

---

## Фазы

### Фаза 0: Опасные тесты
- **Статус:** [x] 25.10.2026, вместе с удалением остатков Render
  (`plans/2026-10-25-chistka-repozitoriya.md`)
- Удалены два живых теста `test_migration_startup.py` и `test_schema_integrity.py`.
- Там же: удалён дубль `test_render_yaml_start_command_has_upgrade_head` и
  `test_start_command_has_no_obsolete_fix_script` (скрипт `fix_production_db.py`
  удалён); статические проверки переименованы `test_render_yaml_*` →
  `test_start_command_*` (читают Dockerfile). Спорный пункт «Ф» закрыт: Render
  погашен, `test_spa_routing.py` удалён вместе с `render.yaml`.
- Гейт: полный pytest.

### Фаза 1: Удаление на бэкенде
- **Статус:** [x] 25.10.2026 — удалено ≈235 тестов в 90 файлах, переносы сделаны; полный набор: 1550 passed
- Раздел 1, Б1–Б8; переносы проверок «перенести туда …» делаются в этой же фазе.
- Оставлены при удалении — не дубли, уходят в фазу 4 (см. «Оставлено при удалении»).
- Пункты по `test_estimate_migration_api.py`, `test_migrate_estimate_items.py` и
  `estimateMigrationPanel.test.tsx` (удалить и переписать) закрыты 25.10.2026:
  функция «Перевод смет» удалена вместе с тестами, `TestTotalsMatchFile` перенесён
  в `test_estimate_single_source.py`.
- Гейт: полный pytest (`cd backend && .venv/bin/python -m pytest`, в фоне, лог + `EXIT=`).

### Фаза 2: Удаление на фронте
- **Статус:** [x] 25.10.2026 — удалено 123 теста (663 → 540 passed); вместе с тестами удалён мёртвый
  `BatchProgressBar` и `utils/batchProgress` (бэкенд не присылает «батча N из M»)
- Раздел 1, Ф1–Ф2.
- Гейт: `npm test`, `npx tsc --noEmit`. **Внимание:** `tsconfig.json` исключает
  `src/__tests__`, поэтому типы тестов не проверяются вовсе; в `exportBuilder`,
  `negativeQty`, `summaryTargetsSheet`, `summaryRegressFixture` лежат старые ошибки
  типов. → отдельный tsconfig для тестов в фазе 5.

### Фаза 3: Общие фикстуры
- **Статус:** [x] 25.10.2026 — шесть фикстур (таблица в разделе 2, «Общие
  фикстуры»); на каждую переписаны тесты из раздела 2 (помечены «[x] фаза 3»):
  19 тестов бэкенда и 2 фронта. Каждый переписанный тест проверен поломкой
  продового кода — временно ломалась строка, тест падал, строка возвращалась.
- Заодно: копии окружения КП в `test_kp_offers/parser/pricelist/apply` заменены
  на `make_kp_env`; пять фабрик ошибок Anthropic (`test_balance_pause*`,
  `test_rate_limit_retry`, `test_admin_api_health`, `test_api_rate_limit_counter`)
  — на `tests/helpers/anthropic_api.py`.
- Гейт: полный pytest — 1542 passed, 4 failed (`test_spa_catch_all`: в рабочей
  копии нет `frontend/dist`, «Найдено по пути», п. 8); фронт — 549 passed, tsc чисто.

### Фаза 4: Переписывание бэкенда
- **Статус:** [x] 26.10.2026 — все пункты раздела 2 для Б1–Б8 и «Оставлено при
  удалении»; восемь исполнителей в отдельных git worktree, ветка на группу,
  слияние в `main` без конфликтов.
- Каждый переписанный тест проверен поломкой продового кода (временно ломалась
  строка — тест падал — строка возвращалась); всего несколько сотен мутаций.
- Разрешённые правки продового кода: `file_parser` (п. 1), `prices_catalog`
  (п. 9), `resume_poller` (тестовая ветка `runner` удалена), `config` +
  `main` (`FRONTEND_DIST_DIR`), удалена мёртвая `excel_service.generate_smeta`;
  отдельно — починка веб-поиска (п. 12) и защита разбора (п. 15).

### Фаза 5: Переписывание фронта
- **Статус:** [x] 26.10.2026 — Ф1 и Ф2; `formatError` — проверка категорий вместо
  точных фраз; `withGridLayout()` в `__tests__/gridLayout.ts`; старые ошибки типов
  в тестах Ф1 исправлены.

### Фаза 6: Спорные — по решению
- **Статус:** [x] 26.10.2026 — все пункты А–У по рекомендациям раздела 3
  («М»: `satisfies Record<TaskStatus, …>` у четырёх карт, `satisfies never` в
  `TaskStatusBadge`, `status-colors-coverage.ts` удалён, правило №20 обновлено).

### Фаза 7: Документация
- **Статус:** [x] 26.10.2026 — CLAUDE.md: раздел «Как гонять тесты» (по файлу
  работает, «каким должен быть тест», фикстуры), правило №20, строка фикстур в
  таблице; render.yaml убран раньше.

## Итог

Реализован целиком (25–26.10.2026). Опасные тесты убраны, ≈358 тестов-помех
удалено, ≈326 хрупких переписаны на поведение и каждый проверен поломкой кода,
спорные решены по рекомендациям, общие фикстуры в `backend/tests/helpers/`.
Полные наборы на `main` (e5dbaec) зелёные: бэкенд 1575 passed (7 мин 15 с),
фронт 67 файлов / 606 passed, `tsc` чисто, `ruff check app` чисто. По пути
исправлены две ошибки в проде: веб-поиск цены (п. 12) и цена материала в
предпросмотре подбора (п. 9), плюс однострочная шапка гранд-сметы (п. 1, 15).

Осталось — отдельными задачами («Найдено по пути»): п. 3 (`save_rows` для версии
входного файла), п. 13 (разбор заголовка «Цена … (за ед.)» в оптимизаторе),
п. 14 (новая запись кеша цен не видна точному поиску), п. 16 (мелочи).
