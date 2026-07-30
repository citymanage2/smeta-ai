"""Измерение памяти процесса и РЕАЛЬНОГО лимита контейнера.

Зачем отдельный модуль: воркер решает, сколько задач брать параллельно, и до
30.07.2026 решал это по константе `WORKER_RSS_PAUSE_MB=1536`, ничего не зная о
лимите контейнера (на Timeweb он задаётся пресетом приложения). Три одновременно
возобновлённые задачи выходили за лимит, контейнер получал OOM-kill, а задачи
висели «в обработке» до reclaim'а — см.
plans/2026-07-30-parallelnaya-obrabotka-umiraet.md.

Почему `usage` считается по анонимной памяти, а не по `memory.current`:
`memory.current` включает страничный кэш, который ядро отдаёт под давлением без
всякого OOM. Ориентируясь на него, тормоз срабатывал бы на здоровом контейнере.
Убивает же процесс невозвратная анонимная память — её и считаем (`anon` в
cgroup v2, `total_rss` в v1), а при отсутствии cgroup — RSS процесса.

Ничего не бросает: на macOS и в тестах cgroup нет, и это норма — вызывающий
получает None и работает как раньше.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Optional

_CGROUP_V2 = "/sys/fs/cgroup"
_CGROUP_V1 = "/sys/fs/cgroup/memory"

# cgroup v1 «без лимита» пишет не «max», а число близкое к 2^63 — трактуем как
# отсутствие лимита, иначе слоты считались бы от восьми эксабайт.
_V1_UNLIMITED_THRESHOLD = 1 << 62

_MB = 1024 * 1024


def _read(path: str) -> Optional[str]:
    try:
        with open(path, encoding="ascii") as f:
            return f.read()
    except (OSError, ValueError):
        return None


def _read_int(path: str) -> Optional[int]:
    raw = (_read(path) or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None  # 'max' в cgroup v2 — лимита нет


def _stat_field(path: str, field: str) -> Optional[int]:
    """Значение поля из cgroup memory.stat (формат «ключ значение» построчно)."""
    raw = _read(path)
    if not raw:
        return None
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == field:
            try:
                return int(parts[1])
            except ValueError:
                return None
    return None


def rss_mb() -> Optional[float]:
    """Память процесса, МБ. None — платформа не дала цифру.

    Без внешних зависимостей (psutil в проекте нет): на Linux, где живёт прод, —
    честный текущий RSS из /proc/self/status; иначе — пиковый ru_maxrss из
    resource (macOS отдаёт байты, Linux — килобайты).
    """
    raw = _read("/proc/self/status")
    if raw:
        for line in raw.splitlines():
            if line.startswith("VmRSS:"):
                try:
                    return round(int(line.split()[1]) / 1024, 1)
                except (IndexError, ValueError):
                    break
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        divisor = _MB if sys.platform == "darwin" else 1024
        return round(peak / divisor, 1)
    except Exception:  # noqa: BLE001 — измерение не обязано работать везде
        return None


def _meminfo_mb(field: str) -> Optional[float]:
    """Поле из /proc/meminfo в МБ (значения там в килобайтах)."""
    raw = _read("/proc/meminfo")
    if not raw:
        return None
    prefix = f"{field}:"
    for line in raw.splitlines():
        if line.startswith(prefix):
            try:
                return round(int(line.split()[1]) / 1024, 1)
            except (IndexError, ValueError):
                return None
    return None


def container_limit_mb() -> "tuple[Optional[float], Optional[str]]":
    """Сколько памяти отпущено, МБ, и ОТКУДА эта цифра.

    Источник обязателен: `cgroup` — личный лимит контейнера, и тогда цифра целиком
    наша; `host` — лимита нет, это память всей машины, которую делят web,
    обработчик и всё остальное. Разница принципиальна при разборе: 30.07.2026
    диагностика показала «лимит памяти 3911.8 МБ», и это была память машины, а не
    контейнера — вывод «памяти вдоволь» из неё делать нельзя.
    """
    v2 = _read_int(f"{_CGROUP_V2}/memory.max")
    if v2 is not None and v2 > 0:
        return round(v2 / _MB, 1), "cgroup"

    v1 = _read_int(f"{_CGROUP_V1}/memory.limit_in_bytes")
    if v1 is not None and 0 < v1 < _V1_UNLIMITED_THRESHOLD:
        return round(v1 / _MB, 1), "cgroup"

    total = _meminfo_mb("MemTotal")
    if total is not None:
        return total, "host"
    return None, None


def available_mb() -> Optional[float]:
    """Сколько памяти реально можно занять прямо сейчас (MemAvailable), МБ.

    На машине без личного лимита контейнера это единственная честная мера запаса:
    она учитывает и web-контейнер, и всё остальное, что уже занято.
    """
    return _meminfo_mb("MemAvailable")


def container_usage_mb() -> Optional[float]:
    """Занятая анонимная память контейнера, МБ (без страничного кэша).

    None — cgroup недоступна; вызывающий берёт RSS процесса.
    """
    anon = _stat_field(f"{_CGROUP_V2}/memory.stat", "anon")
    if anon is not None:
        return round(anon / _MB, 1)
    rss = _stat_field(f"{_CGROUP_V1}/memory.stat", "total_rss")
    if rss is not None:
        return round(rss / _MB, 1)
    return None


@dataclass(frozen=True)
class MemorySnapshot:
    """Снимок памяти: сколько занято процессом, контейнером и сколько отпущено."""

    rss_mb: Optional[float]
    usage_mb: Optional[float]
    limit_mb: Optional[float]
    # 'cgroup' — личный лимит контейнера; 'host' — память всей машины (лимита нет).
    limit_source: Optional[str] = None
    # Свободно прямо сейчас (MemAvailable). Единственная честная мера запаса, когда
    # личного лимита нет: учитывает и соседей по машине.
    available_mb: Optional[float] = None

    @property
    def used_mb(self) -> Optional[float]:
        """Чем мерить занятость: цифра контейнера точнее, RSS процесса — замена.

        В контейнере кроме воркера могут жить дочерние процессы (onnxruntime,
        alembic), и OOM-killer смотрит на сумму, а не на один процесс.
        """
        return self.usage_mb if self.usage_mb is not None else self.rss_mb

    @property
    def ratio(self) -> Optional[float]:
        """Доля занятой памяти от лимита (0..1+). None — считать не из чего."""
        used, limit = self.used_mb, self.limit_mb
        if used is None or not limit:
            return None
        return round(used / limit, 3)

    @property
    def headroom_mb(self) -> Optional[float]:
        """Сколько ещё можно занять до потолка. None — считать не из чего.

        С личным лимитом контейнера это «лимит минус занятое». Без лимита (общая
        машина) — MemAvailable: цифра машины минус наша занятость соврала бы, потому
        что остальное съедают соседи, а не мы.
        """
        if self.limit_source == "cgroup" and self.limit_mb:
            used = self.used_mb
            return None if used is None else round(self.limit_mb - used, 1)
        return self.available_mb

    def as_dict(self) -> dict:
        """Для payload системного события и ответа диагностики."""
        return {
            "rss_mb": self.rss_mb,
            "usage_mb": self.usage_mb,
            "limit_mb": self.limit_mb,
            "limit_source": self.limit_source,
            "available_mb": self.available_mb,
            "ratio": self.ratio,
        }


def snapshot() -> MemorySnapshot:
    """Снять текущее состояние памяти. Никогда не бросает."""
    limit, source = container_limit_mb()
    return MemorySnapshot(
        rss_mb=rss_mb(),
        usage_mb=container_usage_mb(),
        limit_mb=limit,
        limit_source=source,
        available_mb=available_mb(),
    )
