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
