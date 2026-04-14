ESTIMATE_TASK_TYPES: set[str] = set()

TASK_TYPE_LABELS: dict[str, str] = {
    "LIST_FROM_GRAND": "Перечень из Гранд-сметы",
    "CHECK_LIST_COMPLETENESS": "Проверка полноты перечня",
    "LIST_FROM_PROJECT": "Перечень из проекта",
    "CHECK_PROJECT_COMPLETENESS": "Проверка полноты (по проекту)",
}

ESTIMATION_STATUS_LABELS: dict[str, str] = {
    "unestimated": "Не рассчитано",
    "estimated": "Рассчитано",
    "optimized": "Оптимизировано",
    "optimizing": "Оптимизируется",
    "not_applicable": "—",
}
