import re
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog
from app.models.price import PriceWork, PriceMaterial
from app.services.claude_service import claude_service as _claude_svc

async def call_claude(messages: list, system_prompt: str = "", use_web_search: bool = False) -> str:
    return await _claude_svc.call(messages, system_prompt=system_prompt, use_web_search=use_web_search)

logger = structlog.get_logger()

# In-memory cache
_works_cache: list[dict] = []
_materials_cache: list[dict] = []
_cache_loaded: bool = False


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


async def _semantic_match_work(name: str) -> Optional[dict]:
    """Use Claude to find semantically matching work."""
    if not _works_cache:
        return None

    work_names = [item["name"] for item in _works_cache[:200]]
    names_text = "\n".join(f"- {n}" for n in work_names)

    messages = [
        {
            "role": "user",
            "content": (
                f"Найди наиболее подходящее наименование работы из списка для запроса: '{name}'\n\n"
                f"Список доступных работ:\n{names_text}\n\n"
                "Ответь ТОЛЬКО точным наименованием из списка (скопируй строку), "
                "или 'НЕ НАЙДЕНО' если подходящего нет."
            ),
        }
    ]

    try:
        response = await call_claude(
            messages,
            system_prompt="Ты помощник по поиску строительных работ. Отвечай кратко и точно.",
        )
        response = response.strip()
        if response == "НЕ НАЙДЕНО" or not response:
            return None
        # Find matching item
        norm_response = normalize_text(response)
        for item in _works_cache:
            if normalize_text(item["name"]) == norm_response:
                return item
        return None
    except Exception as e:
        logger.error("Semantic work match failed", error=str(e))
        return None


async def _semantic_match_material(name: str) -> Optional[float]:
    """Use Claude to find semantically matching material."""
    if not _materials_cache:
        return None

    material_names = [item["name"] for item in _materials_cache[:200]]
    names_text = "\n".join(f"- {n}" for n in material_names)

    messages = [
        {
            "role": "user",
            "content": (
                f"Найди наиболее подходящее наименование материала из списка для запроса: '{name}'\n\n"
                f"Список доступных материалов:\n{names_text}\n\n"
                "Ответь ТОЛЬКО точным наименованием из списка (скопируй строку), "
                "или 'НЕ НАЙДЕНО' если подходящего нет."
            ),
        }
    ]

    try:
        response = await call_claude(
            messages,
            system_prompt="Ты помощник по поиску строительных материалов. Отвечай кратко и точно.",
        )
        response = response.strip()
        if response == "НЕ НАЙДЕНО" or not response:
            return None
        norm_response = normalize_text(response)
        for item in _materials_cache:
            if normalize_text(item["name"]) == norm_response:
                return item.get("price")
        return None
    except Exception as e:
        logger.error("Semantic material match failed", error=str(e))
        return None


async def _web_search_work_price(name: str) -> Optional[dict]:
    """Use Claude with web search to find work price."""
    messages = [
        {
            "role": "user",
            "content": (
                f"Найди актуальную рыночную цену на строительную работу: '{name}' в России (2024-2025). "
                "Укажи цену за единицу измерения. "
                "Ответь в формате JSON: {{\"price\": число, \"unit\": \"ед. изм.\", \"source\": \"источник\"}}"
            ),
        }
    ]

    try:
        response = await call_claude(
            messages,
            system_prompt="Ты эксперт по ценообразованию в строительстве.",
            use_web_search=True,
        )
        import json
        # Try to extract JSON from response
        import re
        json_match = re.search(r'\{[^{}]+\}', response)
        if json_match:
            data = json.loads(json_match.group())
            price = float(data.get("price", 0))
            unit = data.get("unit", "")
            if price > 0:
                return {"prices": {"web": price}, "min_price": price, "unit": unit}
        return None
    except Exception as e:
        logger.error("Web search work price failed", error=str(e))
        return None


async def _web_search_material_price(name: str) -> Optional[float]:
    """Use Claude with web search to find material price."""
    messages = [
        {
            "role": "user",
            "content": (
                f"Найди актуальную розничную цену на строительный материал: '{name}' в России (2024-2025). "
                "Ответь в формате JSON: {{\"price\": число, \"unit\": \"ед. изм.\"}}"
            ),
        }
    ]

    try:
        response = await call_claude(
            messages,
            system_prompt="Ты эксперт по строительным материалам и ценообразованию.",
            use_web_search=True,
        )
        import json, re
        json_match = re.search(r'\{[^{}]+\}', response)
        if json_match:
            data = json.loads(json_match.group())
            price = float(data.get("price", 0))
            if price > 0:
                return price
        return None
    except Exception as e:
        logger.error("Web search material price failed", error=str(e))
        return None


async def load_cache(db: AsyncSession) -> None:
    """Load price data from DB into in-memory cache."""
    global _works_cache, _materials_cache, _cache_loaded

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

    _cache_loaded = True
    logger.info(
        "Price cache loaded",
        works=len(_works_cache),
        materials=len(_materials_cache),
    )


async def find_work_price(name: str) -> Optional[dict]:
    """Find work price: exact match -> Claude semantic -> web search."""
    # 1. Exact match
    result = _exact_match_work(name)
    if result:
        return result

    # 2. Claude semantic match
    result = await _semantic_match_work(name)
    if result:
        return result

    # 3. Web search
    result = await _web_search_work_price(name)
    return result


async def find_material_price(name: str) -> Optional[float]:
    """Find material price: exact match -> Claude semantic -> web search."""
    # 1. Exact match
    result = _exact_match_material(name)
    if result is not None:
        return result

    # 2. Claude semantic match
    result = await _semantic_match_material(name)
    if result is not None:
        return result

    # 3. Web search
    result = await _web_search_material_price(name)
    return result


class PriceService:
    """Singleton wrapper for price service functions."""

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
