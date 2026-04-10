ESTIMATE_TASK_TYPES: set[str] = set()

TASK_TYPE_LABELS: dict[str, str] = {
    "LIST_FROM_GRAND": "Перечень из Гранд-сметы",
    "CHECK_LIST_COMPLETENESS": "Проверка полноты перечня",
}

ESTIMATION_STATUS_LABELS: dict[str, str] = {
    "unestimated": "Не рассчитано",
    "estimated": "Рассчитано",
    "optimized": "Оптимизировано",
    "optimizing": "Оптимизируется",
    "not_applicable": "—",
}
