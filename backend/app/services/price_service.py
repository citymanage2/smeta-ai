import asyncio
import re
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog
from app.models.price import PriceWork, PriceMaterial
from app.services.claude_service import claude_service as _claude_svc
from app.utils.json_utils import extract_json

try:
    import numpy as np
    _numpy_available = True
except ImportError:
    np = None  # type: ignore[assignment]
    _numpy_available = False

async def call_claude(messages: list, system_prompt: str = "", use_web_search: bool = False) -> str:
    return await _claude_svc.call(messages, system_prompt=system_prompt, use_web_search=use_web_search)

logger = structlog.get_logger()

SIMILARITY_THRESHOLD = 0.93  # порог cosine similarity для embedding-поиска (Cohere embed-v3)

# In-memory cache
_works_cache: list[dict] = []
_materials_cache: list[dict] = []
_cache_loaded: bool = False

# Embedding matrices (shape N×1024, float32). None if no vectors available.
_works_embeddings: "Optional[np.ndarray]" = None  # type: ignore[type-arg]
_materials_embeddings: "Optional[np.ndarray]" = None  # type: ignore[type-arg]
_works_row_norms: "Optional[np.ndarray]" = None  # type: ignore[type-arg]
_materials_row_norms: "Optional[np.ndarray]" = None  # type: ignore[type-arg]

# Маппинги: строка матрицы → индекс в кэше (для sparse матриц с частичными эмбеддингами)
_works_index_map: list[int] = []      # matrix_row → _works_cache index
_materials_index_map: list[int] = []  # matrix_row → _materials_cache index

# Lock for atomic cache replacement — prevents readers from seeing partially replaced globals
_cache_lock = asyncio.Lock()


def normalize_text(text: str) -> str:
    """Normalize text: lowercase, strip, replace ё->е."""
    text = text.lower().strip()
    text = text.replace("ё", "е")
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)
    return text


def _exact_match_work(name: str) -> Optional[dict]:
    norm = normalize_text(name)
    for item in _works_cache:
        if normalize_text(item["name"]) == norm:
            return item
    return None


def _exact_match_material(name: str) -> Optional[float]:
    norm = normalize_text(name)
    for item in _materials_cache:
        if normalize_text(item["name"]) == norm:
            return item.get("price")
    return None


async def _embedding_match_work(name: str) -> Optional[dict]:
    """Find matching work via cosine similarity of Cohere embeddings."""
    if not _numpy_available or _works_embeddings is None or _works_row_norms is None:
        return None

    try:
        import asyncio
        from app.services.embedding_service import normalize_name, generate_embedding

        normalized = normalize_name(name)
        query_vec = await asyncio.to_thread(generate_embedding, normalized, "search_query")
        query_arr = np.array(query_vec, dtype=np.float32)
        query_norm = float(np.linalg.norm(query_arr))
        if query_norm == 0:
            return None

        scores = np.dot(_works_embeddings, query_arr) / (_works_row_norms * query_norm)
        best_idx = int(np.argmax(scores))

        best_score = float(scores[best_idx])
        # Переводим индекс строки матрицы в индекс кэша через маппинг (sparse matrix)
        cache_idx = _works_index_map[best_idx]
        best_name = _works_cache[cache_idx]["name"] if _works_cache else "?"
        if best_score >= SIMILARITY_THRESHOLD:
            logger.info("Embedding work match HIT", query=name, matched=best_name, score=best_score)
            return _works_cache[cache_idx]
        logger.debug("Embedding work match MISS", query=name, best=best_name, score=best_score, threshold=SIMILARITY_THRESHOLD)
        return None
    except Exception as e:
        logger.error("Embedding work match failed", error=str(e))
        return None


async def _embedding_match_material(name: str) -> Optional[float]:
    """Find matching material via cosine similarity of Cohere embeddings."""
    if not _numpy_available or _materials_embeddings is None or _materials_row_norms is None:
        return None

    try:
        import asyncio
        from app.services.embedding_service import normalize_name, generate_embedding

        normalized = normalize_name(name)
        query_vec = await asyncio.to_thread(generate_embedding, normalized, "search_query")
        query_arr = np.array(query_vec, dtype=np.float32)
        query_norm = float(np.linalg.norm(query_arr))
        if query_norm == 0:
            return None

        scores = np.dot(_materials_embeddings, query_arr) / (_materials_row_norms * query_norm)
        best_idx = int(np.argmax(scores))

        best_score = float(scores[best_idx])
        # Переводим индекс строки матрицы в индекс кэша через маппинг (sparse matrix)
        cache_idx = _materials_index_map[best_idx]
        best_name = _materials_cache[cache_idx]["name"] if _materials_cache else "?"
        if best_score >= SIMILARITY_THRESHOLD:
            logger.info("Embedding material match HIT", query=name, matched=best_name, score=best_score)
            return _materials_cache[cache_idx].get("price")
        logger.debug("Embedding material match MISS", query=name, best=best_name, score=best_score, threshold=SIMILARITY_THRESHOLD)
        return None
    except Exception as e:
        logger.error("Embedding material match failed", error=str(e))
        return None


async def batch_embedding_match_works(names: list[str]) -> "list[Optional[dict]]":
    """Batch cosine-similarity search for works — one Cohere call for all names."""
    if not names:
        return []
    if not _numpy_available or _works_embeddings is None or _works_row_norms is None:
        return [None] * len(names)

    try:
        from app.services.embedding_service import normalize_name, generate_embeddings_batch

        normalized = [normalize_name(n) for n in names]
        query_vecs = await asyncio.to_thread(generate_embeddings_batch, normalized, "search_query")
        query_arr = np.array(query_vecs, dtype=np.float32)          # (M, 1024)
        query_norms = np.linalg.norm(query_arr, axis=1)             # (M,)

        # scores[n, m] = cosine(_works_embeddings[n], query_arr[m])
        raw = np.dot(_works_embeddings, query_arr.T)                 # (N, M)
        safe_qnorms = np.where(query_norms == 0, 1.0, query_norms)  # avoid /0
        scores = raw / (_works_row_norms[:, np.newaxis] * safe_qnorms[np.newaxis, :])  # (N, M)

        best_idx = np.argmax(scores, axis=0)                        # (M,)
        best_scores = scores[best_idx, np.arange(len(names))]       # (M,)

        results: list[Optional[dict]] = []
        for i, (bidx, bscore) in enumerate(zip(best_idx.tolist(), best_scores.tolist())):
            if query_norms[i] == 0:
                results.append(None)
                continue
            cache_idx = _works_index_map[bidx]
            matched_name = _works_cache[cache_idx]["name"] if _works_cache else "?"
            if bscore >= SIMILARITY_THRESHOLD:
                logger.info("Batch emb work HIT", query=names[i], matched=matched_name, score=bscore)
                results.append(_works_cache[cache_idx])
            else:
                logger.debug("Batch emb work MISS", query=names[i], best=matched_name, score=bscore)
                results.append(None)
        return results
    except Exception as e:
        logger.error("Batch embedding work match failed", error=str(e))
        return [None] * len(names)


async def batch_embedding_match_materials(names: list[str]) -> "list[Optional[float]]":
    """Batch cosine-similarity search for materials — one Cohere call for all names."""
    if not names:
        return []
    if not _numpy_available or _materials_embeddings is None or _materials_row_norms is None:
        return [None] * len(names)

    try:
        from app.services.embedding_service import normalize_name, generate_embeddings_batch

        normalized = [normalize_name(n) for n in names]
        query_vecs = await asyncio.to_thread(generate_embeddings_batch, normalized, "search_query")
        query_arr = np.array(query_vecs, dtype=np.float32)               # (M, 1024)
        query_norms = np.linalg.norm(query_arr, axis=1)                  # (M,)

        raw = np.dot(_materials_embeddings, query_arr.T)                  # (N, M)
        safe_qnorms = np.where(query_norms == 0, 1.0, query_norms)
        scores = raw / (_materials_row_norms[:, np.newaxis] * safe_qnorms[np.newaxis, :])  # (N, M)

        best_idx = np.argmax(scores, axis=0)                             # (M,)
        best_scores = scores[best_idx, np.arange(len(names))]            # (M,)

        results: list[Optional[float]] = []
        for i, (bidx, bscore) in enumerate(zip(best_idx.tolist(), best_scores.tolist())):
            if query_norms[i] == 0:
                results.append(None)
                continue
            cache_idx = _materials_index_map[bidx]
            matched_name = _materials_cache[cache_idx]["name"] if _materials_cache else "?"
            if bscore >= SIMILARITY_THRESHOLD:
                logger.info("Batch emb material HIT", query=names[i], matched=matched_name, score=bscore)
                results.append(_materials_cache[cache_idx].get("price"))
            else:
                logger.debug("Batch emb material MISS", query=names[i], best=matched_name, score=bscore)
                results.append(None)
        return results
    except Exception as e:
        logger.error("Batch embedding material match failed", error=str(e))
        return [None] * len(names)


async def _web_search_work_price(name: str, user_prompt: str = "") -> Optional[dict]:
    """Use Claude with web search to find lower price for the same work item."""
    extra = f"\nДополнительные инструкции: {user_prompt}" if user_prompt.strip() else ""
    messages = [
        {
            "role": "user",
            "content": (
                f"Найди актуальную рыночную цену на строительную работу: '{name}' "
                f"в Екатеринбурге (текущий год). "
                "Найди до 3 предложений от разных подрядчиков и выбери наименьшую цену "
                "на ту же позицию (не аналог — именно эту работу). "
                "Укажи цену за единицу измерения. "
                "Ответь в формате JSON: {\"price\": число, \"unit\": \"ед. изм.\", \"source\": \"источник\"}"
                f"{extra}"
            ),
        }
    ]

    try:
        response = await call_claude(
            messages,
            system_prompt="Ты эксперт по ценообразованию в строительстве.",
            use_web_search=True,
        )
        try:
            data = extract_json(response)
            price = float(data.get("price", 0))
            unit = data.get("unit", "")
            web_source = data.get("source", "Веб-поиск")
            if price > 0:
                return {"prices": {"web": price}, "min_price": price, "unit": unit, "source": web_source}
        except (ValueError, TypeError):
            pass
        return None
    except Exception as e:
        logger.error("Web search work price failed", error=str(e))
        return None


async def _web_search_material_price(name: str, user_prompt: str = "") -> Optional[float]:
    """Use Claude with web search to find lower price for the same material."""
    extra = f"\nДополнительные инструкции: {user_prompt}" if user_prompt.strip() else ""
    messages = [
        {
            "role": "user",
            "content": (
                f"Найди актуальную розничную цену на строительный материал: '{name}' "
                f"в Екатеринбурге (текущий год). "
                "Найди до 3 предложений от разных поставщиков и выбери наименьшую цену "
                "на ту же позицию (не аналог — именно этот материал). "
                "Ответь в формате JSON: {\"price\": число, \"unit\": \"ед. изм.\", \"source\": \"источник\"}"
                f"{extra}"
            ),
        }
    ]

    try:
        response = await call_claude(
            messages,
            system_prompt="Ты эксперт по строительным материалам и ценообразованию.",
            use_web_search=True,
        )
        try:
            data = extract_json(response)
            price = float(data.get("price", 0))
            if price > 0:
                return price
        except (ValueError, TypeError):
            pass
        return None
    except Exception as e:
        logger.error("Web search material price failed", error=str(e))
        return None


async def load_cache(db: AsyncSession) -> None:
    """Load price data from DB into in-memory cache, including embedding matrices."""
    global _works_cache, _materials_cache, _cache_loaded
    global _works_embeddings, _materials_embeddings, _works_row_norms, _materials_row_norms
    global _works_index_map, _materials_index_map

    # 1. Read from DB without lock — reads are safe to interleave
    works_result = await db.execute(select(PriceWork))
    works = works_result.scalars().all()

    # 2. Build works structures locally
    new_works_cache = [
        {
            "id": w.id,
            "name": w.name,
            "unit": w.unit,
            "prices": w.prices,
            "min_price": w.min_price,
        }
        for w in works
    ]

    # Строим sparse матрицу только из записей с эмбеддингами (частичные данные не блокируют поиск)
    works_with_emb = [(i, w) for i, w in enumerate(works) if w.embedding]
    if _numpy_available and works_with_emb:
        new_works_index_map = [i for i, _ in works_with_emb]
        emb_matrix = np.array([w.embedding for _, w in works_with_emb], dtype=np.float32)
        new_works_embeddings = emb_matrix
        new_works_row_norms = np.linalg.norm(emb_matrix, axis=1)
    else:
        new_works_index_map = []
        new_works_embeddings = None
        new_works_row_norms = None

    materials_result = await db.execute(select(PriceMaterial))
    materials = materials_result.scalars().all()

    # 3. Build materials structures locally
    new_materials_cache = [
        {
            "id": m.id,
            "name": m.name,
            "unit": m.unit,
            "price": m.price,
        }
        for m in materials
    ]

    # Строим sparse матрицу только из записей с эмбеддингами (частичные данные не блокируют поиск)
    materials_with_emb = [(i, m) for i, m in enumerate(materials) if m.embedding]
    if _numpy_available and materials_with_emb:
        new_materials_index_map = [i for i, _ in materials_with_emb]
        emb_matrix = np.array([m.embedding for _, m in materials_with_emb], dtype=np.float32)
        new_materials_embeddings = emb_matrix
        new_materials_row_norms = np.linalg.norm(emb_matrix, axis=1)
    else:
        new_materials_index_map = []
        new_materials_embeddings = None
        new_materials_row_norms = None

    # 4. Atomically replace globals — readers see either old or new consistent state
    async with _cache_lock:
        _works_cache = new_works_cache
        _works_embeddings = new_works_embeddings
        _works_row_norms = new_works_row_norms
        _works_index_map = new_works_index_map
        _materials_cache = new_materials_cache
        _materials_embeddings = new_materials_embeddings
        _materials_row_norms = new_materials_row_norms
        _materials_index_map = new_materials_index_map
        _cache_loaded = True

    logger.info(
        "Price cache loaded",
        works=len(new_works_cache),
        materials=len(new_materials_cache),
        works_embeddings=new_works_embeddings is not None,
        materials_embeddings=new_materials_embeddings is not None,
    )


async def find_work_price(name: str, user_prompt: str = "") -> Optional[dict]:
    """Find work price: exact match -> embedding search -> web search."""
    # 1. Exact match
    result = _exact_match_work(name)
    if result:
        return result

    # 2. Embedding match (OpenAI cosine similarity)
    result = await _embedding_match_work(name)
    if result:
        return result

    # 3. Web search (passes user_prompt for region/instructions context)
    result = await _web_search_work_price(name, user_prompt=user_prompt)
    return result


async def find_material_price(name: str, user_prompt: str = "") -> Optional[float]:
    """Find material price: exact match -> embedding search -> web search."""
    # 1. Exact match
    result = _exact_match_material(name)
    if result is not None:
        return result

    # 2. Embedding match (OpenAI cosine similarity)
    result = await _embedding_match_material(name)
    if result is not None:
        return result

    # 3. Web search (passes user_prompt for region/instructions context)
    result = await _web_search_material_price(name, user_prompt=user_prompt)
    return result


class PriceService:
    """Singleton wrapper for price service functions."""

    async def find_work_price(self, name: str, user_prompt: str = "") -> Optional[dict]:
        """Find lower price for the same work item."""
        return await find_work_price(name, user_prompt=user_prompt)

    async def find_material_price(self, name: str, user_prompt: str = "") -> Optional[float]:
        """Find lower price for the same material."""
        return await find_material_price(name, user_prompt=user_prompt)

    async def load_cache(self) -> None:
        """Load price cache from DB."""
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            await load_cache(db)

    async def enrich_items_with_prices(self, items: list) -> list:
        """Try to find prices for all items from the pricelist cache."""
        enriched = []
        for item in items:
            name = item.get("name", "")
            item_type = item.get("type", "")
            price_info = {"name": name, "type": item_type, "found": False}
            if item_type == "work":
                result = await find_work_price(name)
                if result:
                    price_info.update({"found": True, "price_data": result})
            else:
                result = await find_material_price(name)
                if result is not None:
                    price_info.update({"found": True, "price_data": {"price": result}})
            enriched.append(price_info)
        return enriched


price_service = PriceService()
