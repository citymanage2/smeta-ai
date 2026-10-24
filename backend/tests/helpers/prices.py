"""Прайс и кеш цен с векторами в тестовой БД — без подмены глобалов `price_service`.

Зачем. Подбор цены живёт в памяти процесса: `price_service.load_cache` читает
прайс и кеш прошлых задач из БД и собирает индексы и матрицы векторов в двадцать
модульных переменных. Тесты подменяли их руками — по восемь штук за раз — и
проверяли не подбор, а свою сборку матрицы; а забытая переменная утекала в
соседний тест. Здесь в БД кладутся настоящие строки с `embedding`, кеш строит
сам `load_cache`, а подменяется только модель эмбеддингов (внешний мир):
текст → вектор, который задал тест.

Как пользоваться (фикстура `price_db`):

    async def test_...(price_db):
        price_db.work("Кладка стен", unit="м3", prices={"Подрядчик": 5000}, vector=axis(0))
        price_db.material("Кирпич М150", unit="шт", price=12.5, vector=axis(1))
        price_db.cache_material("Смеси сухие", unit="кг", price=70, vector=axis(2))
        price_db.knows("Кладка из кирпича", similar(0.9, to=0))   # вектор запроса
        await price_db.load()                                     # коммит + load_cache
        found = await price_service.batch_embedding_match_works(["Кладка из кирпича"])

* `vector=` — вектор строки (что лежит в `embedding`); он же ответ модели на
  это название. Без `vector` строки нет в поиске по смыслу, только в точном.
* `price_db.knows(text, vector)` — что модель ответит на этот текст: поисковый
  запрос из сметы или название, которому вектор считает сам код (кеш цен,
  загрузка прайса). Чего модель «не знает»: поисковый запрос получает нулевой
  вектор — по нему ничего не находится; новое название — отказ модели
  (`EmbeddingUnavailableError`), строка пишется без вектора, как в проде при
  недоступной модели. `price_db.model.seen` — какие тексты ушли в модель
  (с префиксом `passage: ` / `query: `).
* `axis(i)` — единичный вектор по оси i; `similar(cos, to=i)` — вектор с
  косинусом ровно `cos` к `axis(i)`. Порог — `price_service.SIMILARITY_THRESHOLD`.
* Таблицы прайса и кеша (`price_works`, `price_materials`, `price_cache_*`)
  фикстура чистит до и после теста; кеш в памяти перед тестом пустой
  и не загружен, после теста возвращается прежним.
"""
import asyncio
import dis
import math
from typing import Any, Optional

import numpy as np
import pytest_asyncio
from sqlalchemy import delete

from app.models.price import PriceMaterial, PriceWork
from app.models.price_cache import PriceCacheMaterial, PriceCacheWork
from app.services import embedding_service, price_service
from app.utils.price_min import compute_min_price

DIM = 8

PRICE_TABLES = (PriceWork, PriceMaterial, PriceCacheWork, PriceCacheMaterial)


def axis(i: int) -> list[float]:
    """Единичный вектор по оси i."""
    vec = [0.0] * DIM
    vec[i] = 1.0
    return vec


def similar(cos: float, *, to: int = 0, via: Optional[int] = None) -> list[float]:
    """Вектор, у которого косинус к `axis(to)` равен ровно `cos`.

    Отклонение уходит в ось `via` (по умолчанию — следующую за `to`).
    """
    other = via if via is not None else (to + 1) % DIM
    vec = [0.0] * DIM
    vec[to] = cos
    vec[other] = math.sqrt(max(0.0, 1.0 - cos * cos))
    return vec


def _key(text: str) -> str:
    return embedding_service.normalize_name(text)


class FakeEmbeddingModel:
    """Модель эмбеддингов (как `fastembed.TextEmbedding`): текст → заданный вектор."""

    def __init__(self) -> None:
        self.vectors: dict[str, list[float]] = {}
        self.seen: list[str] = []

    def embed(self, texts):
        out = []
        for text in texts:
            self.seen.append(text)
            kind, _, bare = text.partition(": ")
            vector = self.vectors.get(_key(bare))
            if vector is None and kind == "passage":
                # Нулевой вектор строки прайса испортил бы поиск по всей матрице
                # (деление на нулевую норму), поэтому незнакомое название —
                # отказ модели, а не вектор.
                raise embedding_service.EmbeddingUnavailableError(
                    f"тестовая модель не знает текст {bare!r}: объявите price_db.knows(...)"
                )
            out.append(np.array(vector if vector is not None else [0.0] * DIM, dtype=np.float32))
        return out


def _cache_globals() -> list[str]:
    """Имена модульных переменных, которые подменяет `load_cache`.

    Список берётся из байт-кода самой функции: появится новая переменная — она
    сама попадёт под сброс и восстановление, и тест не начнёт зависеть от соседа.
    """
    return sorted({
        ins.argval for ins in dis.get_instructions(price_service.load_cache)
        if ins.opname == "STORE_GLOBAL"
    })


def _empty_like(value: Any) -> Any:
    if isinstance(value, list):
        return []
    if isinstance(value, dict):
        return {}
    if isinstance(value, bool):
        return False
    return None


class PriceDb:
    """Строки прайса и кеша в тестовой БД и модель эмбеддингов, которая их «знает»."""

    def __init__(self, db) -> None:
        self.db = db
        self.model = FakeEmbeddingModel()

    def _remember(self, name: str, vector: Optional[list]) -> Optional[list]:
        if vector is not None:
            self.model.vectors[_key(name)] = list(vector)
        return list(vector) if vector is not None else None

    def knows(self, text: str, vector: list) -> None:
        """Что модель ответит на этот текст (поисковый запрос или новое название)."""
        self.model.vectors[_key(text)] = list(vector)

    def work(
        self,
        name: str,
        *,
        unit: Optional[str] = "м2",
        prices: Optional[dict] = None,
        min_price: Optional[float] = None,
        vector: Optional[list] = None,
        **fields: Any,
    ) -> PriceWork:
        """Работа в прайсе. `min_price` по умолчанию — по правилу прайса (`compute_min_price`)."""
        prices = dict(prices) if prices is not None else {"Подрядчик": min_price or 100.0}
        row = PriceWork(
            name=name, unit=unit, prices=prices,
            min_price=min_price if min_price is not None else compute_min_price(prices),
            embedding=self._remember(name, vector), **fields,
        )
        self.db.add(row)
        return row

    def material(
        self,
        name: str,
        *,
        unit: Optional[str] = "шт",
        price: Optional[float] = 100.0,
        vector: Optional[list] = None,
        **fields: Any,
    ) -> PriceMaterial:
        row = PriceMaterial(name=name, unit=unit, price=price,
                            embedding=self._remember(name, vector), **fields)
        self.db.add(row)
        return row

    def cache_work(
        self,
        name: str,
        *,
        unit: Optional[str] = "м2",
        price: float = 100.0,
        vector: Optional[list] = None,
        **fields: Any,
    ) -> PriceCacheWork:
        """Цена работы из прошлых задач (кеш веб-поиска)."""
        row = PriceCacheWork(name=name, name_norm=price_service.normalize_text(name), unit=unit,
                             price=price, embedding=self._remember(name, vector), **fields)
        self.db.add(row)
        return row

    def cache_material(
        self,
        name: str,
        *,
        unit: Optional[str] = "шт",
        price: float = 100.0,
        vector: Optional[list] = None,
        **fields: Any,
    ) -> PriceCacheMaterial:
        row = PriceCacheMaterial(name=name, name_norm=price_service.normalize_text(name), unit=unit,
                                 price=price, embedding=self._remember(name, vector), **fields)
        self.db.add(row)
        return row

    async def load(self) -> None:
        """Записать строки и собрать кеш подбора тем же `load_cache`, что и в проде."""
        await self.db.commit()
        await price_service.load_cache(self.db)

    async def wipe(self) -> None:
        for model in PRICE_TABLES:
            await self.db.execute(delete(model))
        await self.db.commit()


async def drain_background_embeddings() -> None:
    """Дождаться фоновой записи векторов (`save_to_cache` ставит её задачей)."""
    pending = [t for t in list(price_service._background_tasks) if not t.done()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


@pytest_asyncio.fixture
async def price_db(db_session, monkeypatch):
    """Прайс и кеш цен в тестовой БД; модель эмбеддингов — подменённая."""
    for name in _cache_globals():
        monkeypatch.setattr(price_service, name, _empty_like(getattr(price_service, name)))

    book = PriceDb(db_session)
    monkeypatch.setattr(embedding_service, "_get_model", lambda: book.model)
    monkeypatch.setattr(embedding_service, "_model_type", "fastembed")

    await book.wipe()
    yield book
    await drain_background_embeddings()
    await db_session.rollback()
    await book.wipe()
