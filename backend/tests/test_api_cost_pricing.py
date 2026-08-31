"""Прайс моделей закреплён точными числами.

Цена вызова — основа поля «остаток денег на API»: ошибка здесь не даёт
неточность, она даёт систематически убегающую цифру остатка. До 01.09.2026 в
коде намеренно стояла завышенная цена Sonnet 5 ($3/$15) как страховка на случай
объявленного повышения с 1 сентября. Повышение отменено: Anthropic объявил, что
вводная цена $2/$10 становится стандартной. Под остатком завышение в полтора
раза уже не страховка, а постоянная ложь в опасную сторону — сервис считал бы,
что денег на треть меньше, чем есть.

План: plans/2026-09-01-ostatok-deneg-na-api.md, Фаза 1.
"""
from decimal import Decimal

from app.services.claude_service import (
    WEB_SEARCH_COST_PER_REQUEST,
    _calc_cost,
    CLAUDE_MODEL,
)


class TestSonnet5Pricing:
    """Действующий прайс Claude Sonnet 5 — $2 / $10 / $2.50 / $0.20 за 1M."""

    def test_input_tokens(self):
        # 1M входных токенов = $2.00
        assert _calc_cost("claude-sonnet-5", 1_000_000, 0, 0, 0) == Decimal("2.0")

    def test_output_tokens(self):
        # 1M выходных = $10.00
        assert _calc_cost("claude-sonnet-5", 0, 1_000_000, 0, 0) == Decimal("10.0")

    def test_cache_read_tokens(self):
        # Чтение кеша — 0.1× от входа: 1M = $0.20
        assert _calc_cost("claude-sonnet-5", 0, 0, 1_000_000, 0) == Decimal("0.2")

    def test_cache_creation_tokens(self):
        # Запись кеша на 5 минут — 1.25× от входа: 1M = $2.50
        assert _calc_cost("claude-sonnet-5", 0, 0, 0, 1_000_000) == Decimal("2.5")

    def test_realistic_call(self):
        # Типовой вызов: 50k вход, 8k выход, 120k чтение кеша, 30k запись.
        # 0.10 + 0.08 + 0.024 + 0.075 = 0.279
        assert _calc_cost("claude-sonnet-5", 50_000, 8_000, 120_000, 30_000) == Decimal(
            "0.279"
        )

    def test_default_model_is_priced(self):
        """Рабочая модель сервиса не должна попадать в fallback-ветку."""
        from app.services.claude_service import _COST_PER_TOKEN

        assert CLAUDE_MODEL in _COST_PER_TOKEN


class TestBatchDiscount:
    """Batch API — половина цены на токены, но не на web-поиски."""

    def test_tokens_halved(self):
        assert _calc_cost(
            "claude-sonnet-5", 1_000_000, 1_000_000, 0, 0, batch=True
        ) == Decimal("6.0")

    def test_web_search_not_discounted(self):
        # 10 поисков по $0.01 = $0.10, скидка батча на них не распространяется.
        cost = _calc_cost(
            "claude-sonnet-5", 0, 0, 0, 0, batch=True, web_search_requests=10
        )
        assert cost == Decimal("0.1")
        assert WEB_SEARCH_COST_PER_REQUEST == 10.0 / 1000


class TestUnknownModel:
    """Неизвестная модель считается консервативно — занижать нельзя.

    Ошибка в меньшую сторону молча съедает остаток: сервис думает, что денег
    больше, чем есть, и упирается в исчерпанный баланс без предупреждения.
    """

    def test_not_cheaper_than_working_model(self):
        unknown = _calc_cost("claude-model-from-the-future", 1_000_000, 1_000_000, 0, 0)
        working = _calc_cost(CLAUDE_MODEL, 1_000_000, 1_000_000, 0, 0)
        assert unknown >= working
