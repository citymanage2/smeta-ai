import asyncio
from typing import Any, Optional

import httpx
import anthropic
import structlog

from app.config import settings

logger = structlog.get_logger()

CLAUDE_MODEL = "claude-sonnet-4-6"

# Seconds to wait after a 429 when the API does not send a retry-after header.
# One full minute covers the standard per-minute token-rate window.
DEFAULT_RATE_LIMIT_DELAY = 60

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

    result = list(messages)
    if result and result[0]["role"] == "user":
        first_content = result[0]["content"]
        if isinstance(first_content, str):
            first_content = [{"type": "text", "text": first_content}]
        result[0] = {
            "role": "user",
            "content": image_data + first_content,
        }
    else:
        result.insert(0, {"role": "user", "content": image_data})
    return result


async def call_claude(
    messages: list[dict],
    system_prompt: str = "",
    use_web_search: bool = False,
    image_data: Optional[list[dict]] = None,
) -> str:
    """
    Call Claude API (non-streaming) with retry logic and optional web search.
    Returns the final text response.

    Uses non-streaming to avoid httpx.RemoteProtocolError (incomplete chunked read)
    that occurs when the server closes a streaming connection before completion.
    """
    tools = [WEB_SEARCH_TOOL] if use_web_search else []
    built_messages = _build_messages(messages, image_data)

    kwargs: dict[str, Any] = {
        "model": CLAUDE_MODEL,
        "max_tokens": 32000,
        "temperature": 0.1,
        "messages": built_messages,
    }
    if system_prompt:
        kwargs["system"] = system_prompt
    if tools:
        kwargs["tools"] = tools

    # Retryable error delays: rate limits, 5xx, connection / protocol errors
    delays = [2, 8, 30]
    last_error: Optional[Exception] = None

    for attempt, delay in enumerate(delays, start=1):
        try:
            logger.info(
                "Calling Claude API",
                model=CLAUDE_MODEL,
                attempt=attempt,
                use_web_search=use_web_search,
            )

            response = await _client.messages.create(**kwargs)

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

            # Extract all text blocks; skip tool_use / tool_result blocks
            text_parts = [
                block.text
                for block in response.content
                if hasattr(block, "text") and isinstance(block.text, str)
            ]
            result = "".join(text_parts)
            logger.info("Claude API call successful", chars=len(result), attempt=attempt)
            return result

        except anthropic.RateLimitError as e:
            last_error = e
            # Honour the retry-after header when the API tells us exactly how long
            # to wait (common for the 30 000 input-tokens-per-minute limit).
            retry_after_raw = getattr(e, "response", None) and e.response.headers.get("retry-after")
            wait = float(retry_after_raw) if retry_after_raw else DEFAULT_RATE_LIMIT_DELAY
            logger.warning(
                "Claude rate limit hit, retrying",
                attempt=attempt,
                wait=wait,
                retry_after_header=retry_after_raw,
                error=str(e) or repr(e),
            )
            if attempt < len(delays):
                await asyncio.sleep(wait)

        except (anthropic.APIConnectionError, httpx.RemoteProtocolError, httpx.ReadTimeout) as e:
            # httpx.RemoteProtocolError = incomplete chunked read (server closed stream early)
            # httpx.ReadTimeout       = read timeout exceeded
            # anthropic.APIConnectionError wraps other low-level connection failures
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
                # 4xx — do not retry (auth, bad request, etc.)
                logger.error(
                    "Claude API client error (not retrying)",
                    status_code=e.status_code,
                    error=str(e) or repr(e),
                    response_body=getattr(e, "response", None) and e.response.text,
                    exc_info=True,
                )
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

    async def call_with_files(
        self,
        file_contents: list,
        user_text: str,
        system_prompt: str = "",
        use_web_search: bool = False,
        max_tokens: int = 8096,
    ) -> str:
        content = []
        for fc in file_contents:
            if isinstance(fc, dict):
                content.append(fc)
            else:
                content.append({"type": "text", "text": str(fc)})
        content.append({"type": "text", "text": user_text})
        messages = [{"role": "user", "content": content}]
        return await call_claude(messages, system_prompt=system_prompt, use_web_search=use_web_search)


claude_service = ClaudeService()
