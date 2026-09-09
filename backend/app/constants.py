# Типы задач, результат которых — смета со стоимостью (estimation_status = "unestimated" при создании,
# потом "estimated"/"optimized" после обработки). Остальные типы дают перечни/проверки — "not_applicable".
# При добавлении задачи, результат которой — Excel со стоимостью, добавить её тип сюда.
ESTIMATE_TASK_TYPES: set[str] = {"ESTIMATE_FROM_LIST", "ESTIMATE_OPTIMIZATION"}

TASK_TYPE_LABELS: dict[str, str] = {
    "LIST_FROM_GRAND": "Перечень из Гранд-сметы",
    "CHECK_LIST_COMPLETENESS": "Проверка полноты перечня",
    "LIST_FROM_PROJECT": "Перечень из проекта",
    "CHECK_PROJECT_COMPLETENESS": "Проверка полноты (по проекту)",
    "ESTIMATE_FROM_LIST": "Смета из перечня",
    "ESTIMATE_OPTIMIZATION": "Оптимизация сметы",
}

ESTIMATION_STATUS_LABELS: dict[str, str] = {
    "unestimated": "Не рассчитано",
    "estimated": "Рассчитано",
    "optimized": "Оптимизировано",
    "optimizing": "Оптимизируется",
    "not_applicable": "—",
}

TASK_TYPE_TO_FIELD: dict[str, str] = {
    "LIST_FROM_GRAND": "list_task_id",
    "LIST_FROM_PROJECT": "list_task_id",
    "CHECK_LIST_COMPLETENESS": "completeness_task_id",
    "CHECK_PROJECT_COMPLETENESS": "completeness_task_id",
    "ESTIMATE_FROM_LIST": "estimate_task_id",
    "ESTIMATE_OPTIMIZATION": "optimization_task_id",
}

TASK_TYPE_TO_STAGE: dict[str, str] = {
    "LIST_FROM_GRAND": "list",
    "LIST_FROM_PROJECT": "list",
    "CHECK_LIST_COMPLETENESS": "completeness",
    "CHECK_PROJECT_COMPLETENESS": "completeness",
    "ESTIMATE_FROM_LIST": "estimate",
    "ESTIMATE_OPTIMIZATION": "optimization",
}

# Терминальные статусы задачи: дальше сама она не изменится (перезапуск создаёт
# новый прогон). В этот момент фиксируется finished_at — граница фактической
# обработки, по которой калибруется прогноз времени (см. eta_service).
TERMINAL_TASK_STATUSES: set[str] = {"completed", "failed", "cancelled"}

# Задача создана, файл к ней прикреплён — но в очередь она НЕ поставлена и ждёт
# нажатия человеком («Начать оптимизацию»). Отличается от `pending` тем, что
# `pending` означает «стоит в очереди и вот-вот пойдёт»: по нему считается
# ожидание в очереди, прогноз ETA и очередь дашборда. Статус намеренно не входит
# ни в один список «активных» (usage_metrics/eta_service.ACTIVE_STATUSES) —
# именно поэтому у незапущенной задачи не растёт счётчик ожидания.
# План: plans/2026-09-09-zapusk-optimizacii-knopkoj.md
TASK_STATUS_NOT_STARTED = "not_started"

# Типы задач, которые создаются незапущенными и ждут кнопки. Оптимизация —
# решение человека («оптимизировать эту смету»), а не следующий шаг конвейера:
# раньше она уходила в очередь в момент прикрепления сметы, и этап показывал
# «Идёт», хотя команды никто не давал.
MANUAL_START_TASK_TYPES: set[str] = {"ESTIMATE_OPTIMIZATION"}
