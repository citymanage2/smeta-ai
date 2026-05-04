import os
import asyncio
import tempfile
from datetime import datetime
from pathlib import Path

_file_lock = asyncio.Lock()


def get_weekly_path(vault: Path) -> Path:
    week = datetime.now().strftime("%G-W%V")
    return vault / "weekly" / f"{week}-tasks.md"


def _week_label() -> str:
    now = datetime.now()
    # Понедельник и воскресенье текущей ISO-недели
    monday = now - __import__("datetime").timedelta(days=now.weekday())
    sunday = monday + __import__("datetime").timedelta(days=6)
    return f"{monday.strftime('%d.%m')}–{sunday.strftime('%d.%m.%Y')}"


def _make_template(week_str: str) -> str:
    return f"""---
week: {week_str}
---

# Задачи: {_week_label()}
"""


def read_file(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


async def write_file(path: Path, content: str) -> None:
    async with _file_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
            suffix=".tmp",
        ) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        os.replace(tmp_path, path)


def ensure_template(path: Path) -> str:
    """Если файла нет — создаёт шаблон и возвращает его содержимое."""
    if path.exists():
        return read_file(path)
    week = datetime.now().strftime("%G-W%V")
    content = _make_template(week)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return content


def count_tasks(content: str) -> tuple[int, int]:
    """Возвращает (открытых, закрытых) задач."""
    open_ = content.count("- [ ]")
    done = content.count("- [x]")
    return open_, done
