"""
Tests for price search correctness in optimization:
- PriceService must have find_work_price / find_material_price methods
- Web search prompts must specify Екатеринбург region
- User prompt from wizard must be included in web search message
"""
import pytest
from unittest.mock import patch


@pytest.mark.asyncio
async def test_price_service_has_find_work_price():
    """PriceService must expose find_work_price (used by background task)."""
    from app.services.price_service import PriceService
    svc = PriceService()
    assert hasattr(svc, "find_work_price"), (
        "PriceService must have find_work_price — background task calls it directly"
    )


@pytest.mark.asyncio
async def test_price_service_has_find_material_price():
    """PriceService must expose find_material_price (used by background task)."""
    from app.services.price_service import PriceService
    svc = PriceService()
    assert hasattr(svc, "find_material_price"), (
        "PriceService must have find_material_price — background task calls it directly"
    )


@pytest.mark.asyncio
async def test_web_search_material_price_includes_ekaterinburg():
    """Web search for material price must specify Екатеринбург region."""
    import app.services.price_service as ps
    captured: list[list] = []

    async def mock_call_claude(messages, system_prompt="", use_web_search=False):
        captured.append(messages)
        return '{"price": 100, "source": "test"}'

    with patch.object(ps, "call_claude", side_effect=mock_call_claude):
        await ps._web_search_material_price("Кирпич М150", user_prompt="")

    assert captured, "call_claude was not called"
    content = " ".join(m["content"] for m in captured[0])
    assert "Екатеринбург" in content, (
        f"Web search must specify Екатеринбург region. Got: {content[:200]}"
    )


@pytest.mark.asyncio
async def test_web_search_work_price_includes_ekaterinburg():
    """Web search for work price must specify Екатеринбург region."""
    import app.services.price_service as ps
    captured: list[list] = []

    async def mock_call_claude(messages, system_prompt="", use_web_search=False):
        captured.append(messages)
        return '{"price": 500, "unit": "м2", "source": "test"}'

    with patch.object(ps, "call_claude", side_effect=mock_call_claude):
        await ps._web_search_work_price("Укладка кирпича", user_prompt="")

    assert captured, "call_claude was not called"
    content = " ".join(m["content"] for m in captured[0])
    assert "Екатеринбург" in content, (
        f"Web search must specify Екатеринбург region. Got: {content[:200]}"
    )


@pytest.mark.asyncio
async def test_web_search_material_price_includes_user_prompt():
    """User prompt must appear in web search message when provided."""
    import app.services.price_service as ps
    captured: list[list] = []
    user_prompt = "найди самую низкую цену от официальных дилеров"

    async def mock_call_claude(messages, system_prompt="", use_web_search=False):
        captured.append(messages)
        return '{"price": 100, "source": "test"}'

    with patch.object(ps, "call_claude", side_effect=mock_call_claude):
        await ps._web_search_material_price("Кирпич М150", user_prompt=user_prompt)

    assert captured, "call_claude was not called"
    content = " ".join(m["content"] for m in captured[0])
    assert user_prompt in content, (
        f"User prompt must be included in web search message. Got: {content[:300]}"
    )


@pytest.mark.asyncio
async def test_web_search_work_price_includes_user_prompt():
    """User prompt must appear in work price web search message when provided."""
    import app.services.price_service as ps
    captured: list[list] = []
    user_prompt = "предпочитай государственные расценки"

    async def mock_call_claude(messages, system_prompt="", use_web_search=False):
        captured.append(messages)
        return '{"price": 500, "unit": "м2", "source": "test"}'

    with patch.object(ps, "call_claude", side_effect=mock_call_claude):
        await ps._web_search_work_price("Укладка кирпича", user_prompt=user_prompt)

    assert captured, "call_claude was not called"
    content = " ".join(m["content"] for m in captured[0])
    assert user_prompt in content, (
        f"User prompt must be included in web search message. Got: {content[:300]}"
    )
