# План: оптимизация запускается кнопкой, а не сама

Дата: 2026-09-09
Спецификация: `specs/2026-09-09-zapusk-optimizacii-knopkoj.md`
Исследование: `thoughts/research/2026-09-09-zapusk-optimizacii-knopkoj.md`

## Решение одной строкой

Задача этапа «Оптимизация» создаётся в статусе `not_started` и не ставится в
очередь; кнопка «Начать оптимизацию» переводит её в `pending` и ставит job.

## Challenge Log

1. **Решает ли проблему?** Да: единственная точка автозапуска — `_enqueue_task`
   в `start-task`; из неё уходит только ESTIMATE_OPTIMIZATION, всё остальное
   не меняется. Критерии 1–8 спецификации закрыты фазами 1–2.
2. **Самое ли эффективное решение?** Альтернативы разобраны в исследовании
   (таблица A–D). Отдельный статус даёт правильные метрики, ETA и дашборд
   без единой частной проверки, потому что оба `ACTIVE_STATUSES` — списки
   «активных», а не «неактивных».
3. **Нет ли кода ради кода?** В плане нет ничего, кроме статуса, endpoint'а,
   отображения и кнопки. Кнопку «Отменить черновик» и авто-прикрепление сметы
   при завершении стадии «Смета» намеренно не делаем — их никто не просил.

## Фаза 1 — Бэкенд: `not_started` и запуск по кнопке [x]

* `constants.py`: `TASK_STATUS_NOT_STARTED = "not_started"` с объяснением, чем
  он отличается от `pending`.
* `workflow_cards.start_task`: для `ESTIMATE_OPTIMIZATION` создавать задачу
  с этим статусом и **не** звать `_enqueue_task`. Для остальных типов — как было.
* Новый `POST /workflow-cards/{card_id}/launch-task` (Form `task_type`):
  находит задачу этапа, требует статус `not_started`, переводит в `pending`,
  ставит job, возвращает обновлённую карточку. 404 — нет карточки/задачи,
  400 — неизвестный тип, 409 — задача не в `not_started`.
* Тесты (`backend/tests/test_optimization_manual_start.py`):
  создание не ставит job; статус `not_started`; launch ставит ровно один job и
  переводит в `pending`; повторный launch → 409; метрики не считают ожидание.

## Фаза 2 — Фронт: «Не запущено» и кнопка [x]

* `types/index.ts`, `types/workflow.ts`: `TaskStatus` += `'not_started'`.
* `utils/taskStatusView.ts`: `not_started` → «Ожидает» (цвет ожидания),
  чтобы узел этапа не выглядел идущим.
* `kanban/TaskStatusBadge.tsx`: «● Не запущено».
* `pipeline/PipelineStepper.computeNodeState`: `not_started` → `wait`.
* `kanban/CardStageContent.OptimizationStageBody`: при `not_started` — какая
  смета закреплена и кнопка «Начать оптимизацию»; форма выбора источника
  в этом состоянии не показывается.
* `card/StageProcessingPanel`: не показывать панель хода обработки для
  `not_started` — обрабатывать ещё нечего, а «Перезапустить» там читалось бы
  как второй способ запуска.
* `stores/kanban.ts` + `api/workflowCards.ts`: `launchTask(cardId, taskType)`.
* Тесты (`frontend/src/__tests__/optimizationManualStart.test.tsx`).

## Фаза 3 — Документация и завершение [x]

* `CLAUDE.md`: правило «этап оптимизации не запускается сам».
* Рефлексия в `.business/история/`.
* Коммит явными путями (в рабочей копии параллельно работают другие сессии).

## Итог

Реализован целиком. Фазы 1–3 выполнены, гейты пройдены (см. рефлексию
`.business/история/2026-09-09-zapusk-optimizacii-knopkoj.md`).
