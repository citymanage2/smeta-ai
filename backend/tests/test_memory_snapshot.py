"""Измерение памяти: RSS процесса + реальный лимит контейнера (cgroup).

Зачем: воркер решает, сколько задач брать параллельно. До 30.07.2026 он решал по
константе и не знал лимита контейнера — три задачи разом давали OOM-kill (см.
plans/2026-07-30-parallelnaya-obrabotka-umiraet.md). Здесь проверяется, что цифры
читаются с обоих поколений cgroup и что отсутствие cgroup — не ошибка, а None.
"""
from app.utils import memory


def _fake_fs(monkeypatch, files: dict):
    """Подменить чтение файлов cgroup/proc: путь → содержимое (или KeyError → None)."""
    def fake_read(path: str):
        return files.get(path)

    monkeypatch.setattr(memory, "_read", fake_read)


def test_limit_from_cgroup_v2(monkeypatch):
    """Личный лимит контейнера — источник обязателен: цифра целиком наша."""
    _fake_fs(monkeypatch, {"/sys/fs/cgroup/memory.max": "2147483648\n"})
    assert memory.container_limit_mb() == (2048.0, "cgroup")


def test_limit_v2_max_means_no_limit_fallback_to_meminfo(monkeypatch):
    """`max` — лимита нет: берём память хоста, иначе слоты не от чего считать."""
    _fake_fs(monkeypatch, {
        "/sys/fs/cgroup/memory.max": "max\n",
        "/proc/meminfo": "MemTotal:        4194304 kB\nMemFree: 100 kB\n",
    })
    # Источник 'host': это память ВСЕЙ машины, её делят web и обработчик. Ровно
    # эту цифру прод показал 30.07.2026 как «лимит памяти 3911.8 МБ».
    assert memory.container_limit_mb() == (4096.0, "host")


def test_limit_from_cgroup_v1(monkeypatch):
    _fake_fs(monkeypatch, {"/sys/fs/cgroup/memory/memory.limit_in_bytes": "1073741824"})
    assert memory.container_limit_mb() == (1024.0, "cgroup")


def test_limit_v1_unlimited_is_ignored(monkeypatch):
    """v1 «без лимита» — число под 2^63; принять его = считать слоты от эксабайт."""
    _fake_fs(monkeypatch, {
        "/sys/fs/cgroup/memory/memory.limit_in_bytes": "9223372036854771712",
        "/proc/meminfo": "MemTotal:        2097152 kB\n",
    })
    assert memory.container_limit_mb() == (2048.0, "host")


def test_limit_none_without_cgroup_and_meminfo(monkeypatch):
    """Платформа без cgroup (macOS, тесты) — не ошибка, а «цифры нет»."""
    _fake_fs(monkeypatch, {})
    assert memory.container_limit_mb() == (None, None)


def test_usage_counts_anon_not_page_cache(monkeypatch):
    """Считаем анонимную память: страничный кэш ядро отдаёт без OOM.

    Ориентируясь на memory.current (кэш включён), тормоз срабатывал бы на
    здоровом контейнере.
    """
    _fake_fs(monkeypatch, {
        "/sys/fs/cgroup/memory.stat": "anon 536870912\nfile 1073741824\nslab 100\n",
    })
    assert memory.container_usage_mb() == 512.0


def test_usage_from_cgroup_v1_total_rss(monkeypatch):
    _fake_fs(monkeypatch, {
        "/sys/fs/cgroup/memory/memory.stat": "cache 999\ntotal_rss 268435456\n",
    })
    assert memory.container_usage_mb() == 256.0


def test_usage_none_without_cgroup(monkeypatch):
    _fake_fs(monkeypatch, {})
    assert memory.container_usage_mb() is None


def test_snapshot_ratio_prefers_container_over_process():
    """В контейнере есть дочерние процессы — OOM-killer смотрит на сумму."""
    snap = memory.MemorySnapshot(rss_mb=400.0, usage_mb=1600.0, limit_mb=2048.0)
    assert snap.used_mb == 1600.0
    assert snap.ratio == 0.781


def test_snapshot_ratio_falls_back_to_rss():
    snap = memory.MemorySnapshot(rss_mb=1024.0, usage_mb=None, limit_mb=2048.0)
    assert snap.used_mb == 1024.0
    assert snap.ratio == 0.5


def test_snapshot_ratio_none_without_limit():
    """Нет лимита — доли нет: делить не на что, а не «ноль»."""
    snap = memory.MemorySnapshot(rss_mb=1024.0, usage_mb=None, limit_mb=None)
    assert snap.ratio is None
    assert snap.as_dict() == {
        "rss_mb": 1024.0, "usage_mb": None, "limit_mb": None,
        "limit_source": None, "available_mb": None, "ratio": None,
    }


def test_rss_mb_returns_number_on_this_platform():
    """Смоук: цифра памяти должна получаться и на Linux, и на macOS."""
    value = memory.rss_mb()
    assert value is None or value > 0


def test_snapshot_never_raises():
    snap = memory.snapshot()
    assert isinstance(snap, memory.MemorySnapshot)
