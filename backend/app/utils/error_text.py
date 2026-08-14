"""Текст ошибки задачи: то, что человек увидит в карточке сметы.

`str(exc)` у части исключений самодостаточен («Исходная задача не найдена»), а у
части — нет: `KeyError("unit")` печатается как `'unit'`, и в интерфейсе стояло
ровно это. Такую строку нельзя ни понять, ни переслать — по ней не видно даже,
что это за род ошибки.

Поэтому: сообщение с кириллицей — наше, написанное для человека, идёт как есть.
Всё остальное — техническое, и к нему приписывается тип исключения.
"""
from __future__ import annotations

import re

_CYRILLIC = re.compile(r"[а-яёА-ЯЁ]")


def describe_exception(exc: BaseException) -> str:
    """Строка для `task.error_message`."""
    text = str(exc).strip()
    if text and _CYRILLIC.search(text):
        return text
    if not text:
        return type(exc).__name__
    return f"{type(exc).__name__}: {text}"
