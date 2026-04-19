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

SIMILARITY_THRESHOLD = 0.82  # порог cosine similarity для embedding-поиска

# In-memory cache
_works_cache: list[dict] = []
_materials_cache: list[dict] = []
_cache_loaded: bool = False

# Embedding matrices (shape N×1024, float32). None if no vectors available.
_works_embeddings: "Optional[np.ndarray]" = None  # type: ignore[type-arg]
_materials_embeddings: "Optional[np.ndarray]" = None  # type: ignore[type-arg]
_works_row_norms: "Optional[np.ndarray]" = None  # type: ignore[type-arg]
_materials_row_norms: "Optional[np.ndarray]" = None  # type: ignore[type-arg]


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
    """Find matching work via cosine similarity of OpenAI embeddings."""
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

        if scores[best_idx] >= SIMILARITY_THRESHOLD:
            logger.info("Embedding work match", name=name, score=float(scores[best_idx]))
            return _works_cache[best_idx]
        return None
    except Exception as e:
        logger.error("Embedding work match failed", error=str(e))
        return None


async def _embedding_match_material(name: str) -> Optional[float]:
    """Find matching material via cosine similarity of OpenAI embeddings."""
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

        if scores[best_idx] >= SIMILARITY_THRESHOLD:
            logger.info("Embedding material match", name=name, score=float(scores[best_idx]))
            return _materials_cache[best_idx].get("price")
        return None
    except Exception as e:
        logger.error("Embedding material match failed", error=str(e))
        return None


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

    works_result = await db.execute(select(PriceWork))
    works = works_result.scalars().all()
    _works_cache = [
        {
            "id": w.id,
            "name": w.name,
            "unit": w.unit,
            "prices": w.prices,
            "min_price": w.min_price,
        }
        for w in works
    ]

    # Build works embedding matrix — only if ALL rows have embeddings
    if _numpy_available and works and all(w.embedding for w in works):
        emb_matrix = np.array([w.embedding for w in works], dtype=np.float32)
        _works_embeddings = emb_matrix
        _works_row_norms = np.linalg.norm(emb_matrix, axis=1)
    else:
        _works_embeddings = None
        _works_row_norms = None

    materials_result = await db.execute(select(PriceMaterial))
    materials = materials_result.scalars().all()
    _materials_cache = [
        {
            "id": m.id,
            "name": m.name,
            "unit": m.unit,
            "price": m.price,
        }
        for m in materials
    ]

    # Build materials embedding matrix — only if ALL rows have embeddings
    if _numpy_available and materials and all(m.embedding for m in materials):
        emb_matrix = np.array([m.embedding for m in materials], dtype=np.float32)
        _materials_embeddings = emb_matrix
        _materials_row_norms = np.linalg.norm(emb_matrix, axis=1)
    else:
        _materials_embeddings = None
        _materials_row_norms = None

    _cache_loaded = True
    logger.info(
        "Price cache loaded",
        works=len(_works_cache),
        materials=len(_materials_cache),
        works_embeddings=_works_embeddings is not None,
        materials_embeddings=_materials_embeddings is not None,
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
