import asyncio
from decimal import Decimal
from typing import Any, Callable, Optional

import httpx
import anthropic
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

logger = structlog.get_logger()

CLAUDE_MODEL = "claude-sonnet-4-6"


class InsufficientBalanceError(RuntimeError):
    """Anthropic API отклонил запрос из-за исчерпанного баланса счёта.

    Отдельный тип (а не голый RuntimeError), чтобы вызывающий код мог перевести
    задачу на паузу (`paused`) и автоматически возобновить её после пополнения,
    вместо перевода в `failed`. Наследуется от RuntimeError для обратной
    совместимости с существующими `except RuntimeError`.
    """

# USD per token for cost calculation
_COST_PER_TOKEN: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {
        "input": 3.0 / 1_000_000,
        "output": 15.0 / 1_000_000,
        "cache_read": 0.30 / 1_000_000,
        "cache_creation": 3.75 / 1_000_000,
    },
    # fallback for unknown models — same as sonnet
    "default": {
        "input": 3.0 / 1_000_000,
        "output": 15.0 / 1_000_000,
        "cache_read": 0.30 / 1_000_000,
        "cache_creation": 3.75 / 1_000_000,
    },
}


def _calc_cost(
    model: str,
    input_t: int,
    output_t: int,
    cache_read_t: int,
    cache_creation_t: int,
    batch: bool = False,
) -> Decimal:
    rates = _COST_PER_TOKEN.get(model, _COST_PER_TOKEN["default"])
    total = (
        input_t * rates["input"]
        + output_t * rates["output"]
        + cache_read_t * rates["cache_read"]
        + cache_creation_t * rates["cache_creation"]
    )
    # Batch API — 50% скидка на все токены.
    if batch:
        total *= 0.5
    return Decimal(str(round(total, 6)))


def _extract_result_text(content) -> str:
    """Извлечь итоговый текст из content-блоков ответа.

    При web_search Claude выдаёт несколько text-блоков (рассуждения + финальный
    JSON). Предпочитаем ПОСЛЕДНИЙ блок с '{'; иначе склеиваем все.
    """
    text_parts = [
        block.text
        for block in content
        if hasattr(block, "text") and isinstance(block.text, str)
    ]
    for part in reversed(text_parts):
        if "{" in part:
            return part
    return "".join(text_parts)


def _extract_usage(usage) -> tuple[int, int, int, int]:
    """(input, output, cache_read, cache_creation) из usage-объекта ответа."""
    return (
        getattr(usage, "input_tokens", 0) or 0,
        getattr(usage, "output_tokens", 0) or 0,
        getattr(usage, "cache_read_input_tokens", 0) or 0,
        getattr(usage, "cache_creation_input_tokens", 0) or 0,
    )


async def _log_api_call(
    task_id: Optional[str],
    db: Optional[AsyncSession],
    input_t: int,
    output_t: int,
    cache_read_t: int,
    cache_creation_t: int,
    batch: bool = False,
    duration_ms: Optional[int] = None,
) -> None:
    """Записать вызов в ApiCallLog (отдельной сессией). batch=True → тарифы ×0.5.

    duration_ms — длительность самого API-вызова (None для batch: там нет
    синхронного времени ответа, пачка считается на серверах Anthropic).
    """
    if db is None or task_id is None:
        return
    try:
        from app.models.api_call_log import ApiCallLog
        from app.database import AsyncSessionLocal
        cost = _calc_cost(CLAUDE_MODEL, input_t, output_t, cache_read_t, cache_creation_t, batch=batch)
        log_entry = ApiCallLog(
            task_id=task_id,
            model=CLAUDE_MODEL,
            input_tokens=input_t,
            output_tokens=output_t,
            cache_read_tokens=cache_read_t,
            cache_creation_tokens=cache_creation_t,
            cost_usd=cost,
            duration_ms=duration_ms,
        )
        # Независимая сессия — caller может параллельно использовать свою db (cancel-checks).
        async with AsyncSessionLocal() as log_db:
            log_db.add(log_entry)
            await log_db.commit()
    except Exception as log_err:
        logger.warning("Failed to log API call", error=str(log_err))

# Seconds to wait after a 429 when the API does not send a retry-after header.
DEFAULT_RATE_LIMIT_DELAY = 60

# Per-attempt minimum wait after consecutive 429 responses (exponential backoff).
# Index 0 = first 429, index 1 = second, index 2+ = third and beyond.
RATE_LIMIT_BACKOFF_MINIMUMS = [60, 120, 240]

# Hard cap on any single rate-limit wait.
RATE_LIMIT_MAX_WAIT = 900

WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
}

# Single shared client with generous timeouts.
# read=300s covers large project documents that take a long time to process.
_http_client = httpx.AsyncClient(
    timeout=httpx.Timeout(
        connect=10.0,
        read=300.0,
        write=30.0,
        pool=10.0,
    )
)

_client = anthropic.AsyncAnthropic(
    api_key=settings.ANTHROPIC_API_KEY,
    http_client=_http_client,
)


def _build_messages(
    messages: list[dict],
    image_data: Optional[list[dict]] = None,
) -> list[dict]:
    """Build the messages list, optionally prepending image content blocks."""
    if not image_data:
        return messages

    # Mark the last image block for prompt caching so PDF pages are cached
    # across chunk calls within the same 5-minute TTL window.
    cached_image_data = list(image_data)
    if cached_image_data:
        last = dict(cached_image_data[-1])
        last["cache_control"] = {"type": "ephemeral"}
        cached_image_data[-1] = last

    result = list(messages)
    if result and result[0]["role"] == "user":
        first_content = result[0]["content"]
        if isinstance(first_content, str):
            first_content = [{"type": "text", "text": first_content}]
        result[0] = {
            "role": "user",
            "content": cached_image_data + first_content,
        }
    else:
        result.insert(0, {"role": "user", "content": cached_image_data})
    return result


def _build_message_params(
    messages: list[dict],
    system_prompt: str = "",
    use_web_search: bool = False,
    image_data: Optional[list[dict]] = None,
    max_tokens: int = 32000,
) -> dict[str, Any]:
    """Собрать params для Messages API (модель, tokens, temperature, messages,
    закэшированный system, web_search tool). Общий код для call_claude и batch."""
    params: dict[str, Any] = {
        "model": CLAUDE_MODEL,
        "max_tokens": max_tokens,
        "temperature": 0.1,
        "messages": _build_messages(messages, image_data),
    }
    if system_prompt:
        params["system"] = [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ]
    if use_web_search:
        params["tools"] = [WEB_SEARCH_TOOL]
    return params


async def call_claude(
    messages: list[dict],
    system_prompt: str = "",
    use_web_search: bool = False,
    image_data: Optional[list[dict]] = None,
    processing_timeout: Optional[float] = None,
    on_rate_limit_wait: Optional[Callable[[float], None]] = None,
    task_id: Optional[str] = None,
    db: Optional[AsyncSession] = None,
    max_tokens: int = 32000,
) -> str:
    """
    Call Claude API (non-streaming) with retry logic and optional web search.
    Returns the final text response.

    processing_timeout — if set, wraps ONLY the _client.messages.create() call
        (not the rate-limit sleep).  asyncio.TimeoutError is raised and propagated
        immediately if the API call itself exceeds this budget.

    on_rate_limit_wait — optional callback(wait_seconds) invoked just before each
        rate-limit sleep so callers can react (e.g. extend a batch deadline).
    """
    kwargs = _build_message_params(
        messages,
        system_prompt=system_prompt,
        use_web_search=use_web_search,
        image_data=image_data,
        max_tokens=max_tokens,
    )

    # Retryable error delays for connection / 5xx errors (NOT used for rate limits).
    delays = [2, 8, 30, 60]
    last_error: Optional[Exception] = None

    # Count consecutive 429 responses to apply escalating backoff minimums.
    rate_limit_count = 0

    # Фиксируем момент начала всего вызова, чтобы учитывать время sleep при rate-limit.
    # Для каждого attempt используем оставшийся бюджет, а не исходный processing_timeout.
    call_start: float = asyncio.get_event_loop().time() if processing_timeout is not None else 0.0

    for attempt, delay in enumerate(delays, start=1):
        try:
            logger.info(
                "Calling Claude API",
                model=CLAUDE_MODEL,
                attempt=attempt,
                use_web_search=use_web_search,
            )

            # Вычисляем оставшийся временной бюджет с учётом всего прошедшего времени
            # (включая sleep при rate-limit предыдущих попыток).
            if processing_timeout is not None:
                elapsed = asyncio.get_event_loop().time() - call_start
                remaining = processing_timeout - elapsed
                if remaining <= 0:
                    raise asyncio.TimeoutError(
                        f"processing_timeout exceeded after {elapsed:.1f}s (budget: {processing_timeout}s)"
                    )
            else:
                remaining = None

            # Pass timeout directly to SDK (sets httpx total request timeout).
            # asyncio.wait_for обеспечивает отмену корутины по оставшемуся бюджету.
            attempt_start = asyncio.get_event_loop().time()
            if remaining is not None:
                sdk_kwargs = {**kwargs, "timeout": remaining}
                response = await asyncio.wait_for(
                    _client.messages.create(**sdk_kwargs),
                    timeout=remaining,
                )
            else:
                response = await _client.messages.create(**kwargs)
            call_duration_ms = int((asyncio.get_event_loop().time() - attempt_start) * 1000)

            # Detect output truncation before trying to use the response
            if response.stop_reason == "max_tokens":
                logger.error(
                    "Claude response truncated: max_tokens limit reached",
                    chars=sum(
                        len(b.text) for b in response.content if hasattr(b, "text")
                    ),
                    max_tokens=kwargs["max_tokens"],
                )
                raise ValueError(
                    "Ответ слишком большой, разбейте выполнение на подэтапы"
                )

            # Extract the final text (prefer last block containing JSON).
            result = _extract_result_text(response.content)

            input_t, output_t, cache_read_t, cache_creation_t = _extract_usage(response.usage)

            logger.info(
                "Claude API call successful",
                chars=len(result),
                attempt=attempt,
                cache_read_tokens=cache_read_t,
                cache_creation_tokens=cache_creation_t,
                duration_ms=call_duration_ms,
            )

            await _log_api_call(
                task_id, db, input_t, output_t, cache_read_t, cache_creation_t,
                duration_ms=call_duration_ms,
            )

            return result

        except asyncio.TimeoutError:
            # Real processing timeout — propagate immediately without retry.
            raise

        except anthropic.RateLimitError as e:
            rate_limit_count += 1
            last_error = e

            # Honour the retry-after header if provided, but apply backoff minimums.
            retry_after_raw = (
                e.response.headers.get("retry-after")
                if getattr(e, "response", None) is not None
                else None
            )
            api_retry_after = float(retry_after_raw) if retry_after_raw else DEFAULT_RATE_LIMIT_DELAY

            # Exponential backoff minimum: escalates with each consecutive 429.
            backoff_min = RATE_LIMIT_BACKOFF_MINIMUMS[
                min(rate_limit_count - 1, len(RATE_LIMIT_BACKOFF_MINIMUMS) - 1)
            ]
            wait = min(max(api_retry_after, backoff_min), RATE_LIMIT_MAX_WAIT)

            logger.warning(
                "Claude rate limit hit, retrying",
                attempt=attempt,
                rate_limit_count=rate_limit_count,
                api_retry_after=api_retry_after,
                actual_wait=wait,
                error=str(e) or repr(e),
            )

            if on_rate_limit_wait is not None:
                on_rate_limit_wait(wait)

            if attempt < len(delays):
                await asyncio.sleep(wait)

        except (anthropic.APIConnectionError, httpx.RemoteProtocolError, httpx.ReadTimeout) as e:
            last_error = e
            logger.warning(
                "Claude connection/protocol error, retrying",
                attempt=attempt,
                delay=delay,
                error=str(e) or repr(e),
                exc_info=True,
            )
            if attempt < len(delays):
                await asyncio.sleep(delay)

        except anthropic.APIStatusError as e:
            if e.status_code >= 500:
                last_error = e
                logger.warning(
                    "Claude server error, retrying",
                    attempt=attempt,
                    status_code=e.status_code,
                    delay=delay,
                    error=str(e) or repr(e),
                )
                if attempt < len(delays):
                    await asyncio.sleep(delay)
            else:
                logger.error(
                    "Claude API client error (not retrying)",
                    status_code=e.status_code,
                    error=str(e) or repr(e),
                    response_body=getattr(e, "response", None) and e.response.text,
                    exc_info=True,
                )
                body = getattr(e, "body", None) or {}
                err_msg = body.get("error", {}).get("message", "") if isinstance(body, dict) else ""
                if "credit balance" in err_msg.lower() or "credit balance" in str(e).lower():
                    raise InsufficientBalanceError(
                        "Баланс API Anthropic меньше 0. Обратитесь к администратору сервиса"
                    ) from e
                raise

        except Exception as e:
            logger.error(
                "Unexpected Claude API error",
                error=str(e) or repr(e),
                exc_info=True,
            )
            raise

    logger.error(
        "Claude API call failed after all retries",
        attempts=len(delays),
        last_error=str(last_error) or repr(last_error),
    )
    raise last_error or RuntimeError("Claude API call failed after all retries")


# ---------------------------------------------------------------------------
# Batch API — асинхронная пакетная обработка (Anthropic Message Batches).
# −50% стоимости, устойчивость к рестартам (batch считается на серверах Anthropic).
# ---------------------------------------------------------------------------


def build_batch_request(
    custom_id: str,
    messages: list[dict],
    system_prompt: str = "",
    use_web_search: bool = False,
    image_data: Optional[list[dict]] = None,
    max_tokens: int = 32000,
) -> dict:
    """Собрать один Request для batch с тем же составом params, что call_claude."""
    from anthropic.types.messages.batch_create_params import Request
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming

    params = _build_message_params(
        messages,
        system_prompt=system_prompt,
        use_web_search=use_web_search,
        image_data=image_data,
        max_tokens=max_tokens,
    )
    return Request(custom_id=custom_id, params=MessageCreateParamsNonStreaming(**params))


async def submit_claude_batch(requests: list[dict]) -> str:
    """Отправить пачку запросов. Возвращает batch_id (msgbatch_...)."""
    batch = await _client.messages.batches.create(requests=requests)
    logger.info("Claude batch submitted", batch_id=batch.id, count=len(requests))
    return batch.id


async def poll_claude_batch(batch_id: str) -> str:
    """Вернуть processing_status пачки ('in_progress' | 'ended' | ...)."""
    batch = await _client.messages.batches.retrieve(batch_id)
    return batch.processing_status


async def collect_claude_batch(
    batch_id: str,
    task_id: Optional[str] = None,
    db: Optional[AsyncSession] = None,
) -> dict[str, dict]:
    """Собрать результаты пачки в {custom_id: {text, error, usage}}.

    Порядок результатов произвольный — ключуем строго по custom_id.
    Успешные вызовы логируются в ApiCallLog по уполовиненным (batch) тарифам.
    """
    import inspect

    out: dict[str, dict] = {}
    stream = _client.messages.batches.results(batch_id)
    if inspect.isawaitable(stream):
        stream = await stream

    async for entry in stream:
        cid = entry.custom_id
        rtype = entry.result.type
        if rtype == "succeeded":
            msg = entry.result.message
            text = _extract_result_text(msg.content)
            input_t, output_t, cache_read_t, cache_creation_t = _extract_usage(msg.usage)
            out[cid] = {
                "text": text,
                "error": None,
                "usage": {
                    "input": input_t,
                    "output": output_t,
                    "cache_read": cache_read_t,
                    "cache_creation": cache_creation_t,
                },
            }
            await _log_api_call(
                task_id, db, input_t, output_t, cache_read_t, cache_creation_t, batch=True
            )
        else:
            # errored | canceled | expired
            out[cid] = {"text": None, "error": rtype, "usage": None}
            logger.warning("Claude batch entry not succeeded", custom_id=cid, type=rtype)

    logger.info("Claude batch collected", batch_id=batch_id, count=len(out))
    return out


async def cancel_claude_batch(batch_id: str) -> None:
    """Отменить пачку (при отмене задачи)."""
    await _client.messages.batches.cancel(batch_id)
    logger.info("Claude batch cancelled", batch_id=batch_id)


class ClaudeService:
    """Singleton wrapper around call_claude for use by task_processor."""

    async def call(
        self,
        messages: list[dict],
        system_prompt: str = "",
        use_web_search: bool = False,
        max_tokens: int = 8096,
    ) -> str:
        return await call_claude(messages, system_prompt=system_prompt, use_web_search=use_web_search)


claude_service = ClaudeService()
