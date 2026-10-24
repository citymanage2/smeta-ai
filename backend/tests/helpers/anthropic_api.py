"""Anthropic API в тестах: ошибки, ответы и сценарий вызовов — в одном месте.

Зачем. До 25.10.2026 в тестах жило пять своих фабрик ошибок и три способа
подменить клиент. Каждая собирала исключение по-своему (разный класс на тот же
статус, разное тело), и тест мог проходить на ошибке, которой SDK никогда не
бросит. Здесь ошибка строится самим SDK из HTTP-ответа — ровно тот класс, тело и
текст, которые прилетят в проде, — а клиент подменяется одним способом:
`patch_claude_create` (фабрика `claude_service._get_client`).

Как пользоваться.

* Ошибка: `balance_error()`, `rate_limit_error(retry_after=30)`,
  `server_error(503)`, `overloaded_error()`, `connection_error()` или общий
  `api_error(status, message)`. Посредник (`ANTHROPIC_BASE_URL`) —
  `url=PROXY_URL`.
* Ответ ИИ: `claude_message({"items": [...]})` — dict/list уходят текстом JSON,
  `usage` и `stop_reason` задаются ключами (`stop_reason="max_tokens"` —
  оборванный ответ).
* Сценарий: фикстура `claude_api(шаг, шаг, ...)` подменяет `messages.create`.
  Шаг — ответ (`claude_message(...)`, строка или dict), исключение (бросается)
  или функция `kwargs -> шаг` (ответ по содержимому запроса, см.
  `prompt_text`). Возвращает `ClaudeScript`: `script.calls` — kwargs каждого
  вызова, `script.prompt(i)` — текст запроса. Лишний вызов сверх сценария —
  `AssertionError` (`repeat=True` повторяет последний шаг бесконечно).
* Сон между повторами: фикстура `api_sleeps` — список секунд, которые
  `call_claude` проспал бы (429 и 5xx); сам сон мгновенный. Подменяется только
  внутри `claude_service`: циклы процессора и воркера спят по-настоящему.
"""
import asyncio
import inspect
import json
from types import SimpleNamespace
from typing import Any, Callable, Iterable, Optional, Union

import anthropic
import httpx2
import pytest

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
PROXY_URL = "https://proxy.example/v1/messages"

# Дословный текст Anthropic при пустом счёте (приходит с HTTP 400).
BALANCE_MESSAGE = (
    "Your credit balance is too low to access the Anthropic API. "
    "Please go to Plans & Billing to upgrade or purchase credits."
)

_ERROR_TYPES = {
    400: "invalid_request_error",
    401: "authentication_error",
    402: "billing_error",
    403: "permission_error",
    404: "not_found_error",
    413: "request_too_large",
    429: "rate_limit_error",
    529: "overloaded_error",
}

_sdk_client: Optional[anthropic.AsyncAnthropic] = None


def _sdk() -> anthropic.AsyncAnthropic:
    """Клиент SDK только ради его же сборки ошибки из ответа; в сеть не ходит."""
    global _sdk_client
    if _sdk_client is None:
        _sdk_client = anthropic.AsyncAnthropic(api_key="test-key", base_url="https://api.anthropic.com")
    return _sdk_client


# ---------------------------------------------------------------------------
# Ошибки
# ---------------------------------------------------------------------------

def api_error(
    status: int,
    message: str,
    *,
    error_type: Optional[str] = None,
    headers: Optional[dict] = None,
    url: str = ANTHROPIC_URL,
) -> anthropic.APIStatusError:
    """Ошибка API ровно того класса, который SDK бросит на такой HTTP-ответ.

    400 → BadRequestError, 429 → RateLimitError, 529 → OverloadedError,
    5xx → InternalServerError, прочие — по таблице SDK.
    """
    kind = error_type or _ERROR_TYPES.get(status) or ("api_error" if status >= 500 else "error")
    body = {"type": "error", "error": {"type": kind, "message": message}}
    response = httpx2.Response(
        status,
        headers=headers or {},
        json=body,
        request=httpx2.Request("POST", url),
    )
    return _sdk()._make_status_error_from_response(response)


def balance_error(status: int = 400, message: str = BALANCE_MESSAGE, **kw: Any) -> anthropic.APIStatusError:
    """«Баланс исчерпан». Прямой Anthropic отвечает 400; посредник — чем угодно
    (402, 429, 5xx), поэтому статус задаётся."""
    return api_error(status, message, **kw)


def rate_limit_error(
    retry_after: Union[int, float, str, None] = None,
    message: str = "Rate limit exceeded",
    **kw: Any,
) -> anthropic.RateLimitError:
    """429. `retry_after=None` — без заголовка retry-after."""
    headers = dict(kw.pop("headers", None) or {})
    if retry_after is not None:
        headers["retry-after"] = str(retry_after)
    return api_error(429, message, headers=headers, **kw)  # type: ignore[return-value]


def server_error(status: int = 500, message: str = "Internal server error", **kw: Any) -> anthropic.APIStatusError:
    """5xx: временный сбой сервера, `call_claude` его повторяет."""
    return api_error(status, message, **kw)


def overloaded_error(message: str = "Overloaded", **kw: Any) -> anthropic.APIStatusError:
    """529 — Anthropic перегружен."""
    return api_error(529, message, **kw)


def connection_error(url: str = ANTHROPIC_URL) -> anthropic.APIConnectionError:
    """Обрыв соединения до ответа (сеть, посредник недоступен)."""
    return anthropic.APIConnectionError(request=httpx2.Request("POST", url))


# ---------------------------------------------------------------------------
# Ответы
# ---------------------------------------------------------------------------

def claude_message(
    answer: Union[str, dict, list],
    *,
    stop_reason: str = "end_turn",
    input_tokens: int = 1000,
    output_tokens: int = 200,
    cache_read_input_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
    web_search_requests: int = 0,
) -> SimpleNamespace:
    """Ответ `messages.create` с теми полями, которые читает `call_claude`."""
    text = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
    server_tool_use = (
        SimpleNamespace(web_search_requests=web_search_requests) if web_search_requests else None
    )
    return SimpleNamespace(
        id="msg_test",
        type="message",
        role="assistant",
        model="claude-sonnet-5",
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
            cache_creation_input_tokens=cache_creation_input_tokens,
            server_tool_use=server_tool_use,
        ),
    )


def prompt_text(kwargs: dict) -> str:
    """Весь текст пользовательских сообщений запроса (блоки склеены переводом строки)."""
    parts: list[str] = []
    for message in kwargs.get("messages") or []:
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
            continue
        for block in content or []:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
    return "\n".join(parts)


Step = Union[SimpleNamespace, str, dict, list, BaseException, Callable[[dict], Any]]


class ClaudeScript:
    """Подменённый `messages.create`: отвечает по сценарию и помнит каждый вызов."""

    def __init__(self, steps: Iterable[Step], *, repeat: bool = False):
        self._steps = list(steps)
        self._repeat = repeat
        self.calls: list[dict] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if not self._steps:
            raise AssertionError(f"Лишний вызов ИИ (№{len(self.calls)}): сценарий кончился")
        step: Any = self._steps[0] if (self._repeat and len(self._steps) == 1) else self._steps.pop(0)
        if callable(step) and not isinstance(step, BaseException):
            step = step(kwargs)
            if inspect.isawaitable(step):
                step = await step
        if isinstance(step, BaseException):
            raise step
        if isinstance(step, (str, dict, list)):
            return claude_message(step)
        return step

    def prompt(self, index: int = -1) -> str:
        """Текст запроса вызова `index` (по умолчанию — последнего)."""
        return prompt_text(self.calls[index])


@pytest.fixture
def claude_api(patch_claude_create):
    """Подменить Claude API сценарием ответов: `script = claude_api(ответ, ошибка, ...)`."""

    def _install(*steps: Step, repeat: bool = False) -> ClaudeScript:
        script = ClaudeScript(steps, repeat=repeat)
        patch_claude_create(script.create)
        return script

    return _install


class _AsyncioWithRecordedSleep:
    """`asyncio` для модуля `claude_service`: sleep записывает паузу и не ждёт."""

    def __init__(self, waits: list):
        self._waits = waits

    async def sleep(self, delay: float, result: Any = None) -> Any:
        self._waits.append(delay)
        await asyncio.sleep(0)  # отдать управление, как настоящий sleep
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(asyncio, name)


@pytest.fixture
def api_sleeps(monkeypatch) -> list:
    """Паузы `call_claude` между повторами (секунды) — без самого ожидания."""
    from app.services import claude_service

    waits: list = []
    monkeypatch.setattr(claude_service, "asyncio", _AsyncioWithRecordedSleep(waits))
    return waits
