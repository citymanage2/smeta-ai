"""Клиент S3 создаётся один раз даже при одновременных чтениях из потоков.

Файлы читаются в потоках (`run_in_threadpool`), и на свежем деплое несколько задач
разом входят в создание клиента: каждая первым делом грузит свой входной файл.
Создание клиента boto3 потокобезопасным не является (сами вызовы — да), поэтому
без замка это либо лишние клиенты, либо исключение в загрузке файла у живой задачи.

План: plans/2026-07-30-parallelnaya-obrabotka-umiraet.md, Фаза 6.
"""
import threading

from app.services import storage_service


def test_concurrent_get_client_builds_one_instance(monkeypatch):
    built = []
    start = threading.Barrier(8)

    class FakeClient:
        pass

    def slow_build():
        # Пауза внутри сборки — окно гонки, которое и ловил инцидент.
        threading.Event().wait(0.01)
        client = FakeClient()
        built.append(client)
        return client

    monkeypatch.setattr(storage_service, "_client", None)
    monkeypatch.setattr(storage_service, "_build_client", slow_build)

    results = []

    def worker():
        start.wait()
        results.append(storage_service._get_client())

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(built) == 1, "клиент собран несколько раз — замок не работает"
    assert len({id(r) for r in results}) == 1
    assert all(isinstance(r, FakeClient) for r in results)


def test_get_client_reuses_existing(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(storage_service, "_client", sentinel)
    monkeypatch.setattr(
        storage_service, "_build_client",
        lambda: pytest_fail("клиент пересоздан вместо переиспользования"),
    )

    assert storage_service._get_client() is sentinel


def pytest_fail(message: str):
    raise AssertionError(message)
