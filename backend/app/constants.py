ESTIMATE_TASK_TYPES = {
    "SMETA_FROM_LIST",
    "SMETA_FROM_PROJECT",
    "SMETA_FROM_EDC_PROJECT",
    "SMETA_FROM_GRAND_PROJECT",
    "SCAN_TO_EXCEL",
    "OPTIMIZE_SMETA",
}

TASK_TYPE_LABELS: dict[str, str] = {
    "SMETA_FROM_LIST": "Смета из ТЗ",
    "SMETA_FROM_PROJECT": "Смета из проекта",
    "SMETA_FROM_EDC_PROJECT": "Смета из EDC-проекта",
    "SMETA_FROM_GRAND_PROJECT": "Смета из GRAND-проекта",
    "SCAN_TO_EXCEL": "Сканирование в Excel",
    "LIST_FROM_TZ": "Список из ТЗ",
    "LIST_FROM_TZ_PROJECT": "Список из ТЗ проекта",
    "LIST_FROM_PROJECT": "Список из проекта",
    "RESEARCH_PROJECT": "Исследование проекта",
    "COMPARE_PROJECT_SMETA": "Сравнение сметы",
    "OPTIMIZE_SMETA": "Оптимизация сметы",
}

ESTIMATION_STATUS_LABELS: dict[str, str] = {
    "unestimated": "Не рассчитано",
    "estimated": "Рассчитано",
    "optimized": "Оптимизировано",
    "processing_optimization": "Оптимизируется",
    "not_applicable": "—",
}
