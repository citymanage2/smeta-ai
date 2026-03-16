import asyncio
from typing import Any, Optional
import anthropic
import structlog
from app.config import settings

logger = structlog.get_logger()

CLAUDE_MODEL = "claude-sonnet-4-0"

WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
}


def _build_messages(
    messages: list[dict],
    image_data: Optional[list[dict]] = None,
) -> list[dict]:
    """Build the messages list, optionally prepending image content blocks."""
    if not image_data:
        return messages

    # If image_data provided, inject into first user message or prepend new one
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
        result.insert(
            0,
            {
                "role": "user",
                "content": image_data,
            },
        )
    return result


async def call_claude(
    messages: list[dict],
    system_prompt: str = "",
    use_web_search: bool = False,
    image_data: Optional[list[dict]] = None,
) -> str:
    """
    Call Claude API with retry logic and optional web search tool.
    Returns the final text response.
    """
    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    tools = [WEB_SEARCH_TOOL] if use_web_search else []
    built_messages = _build_messages(messages, image_data)

    kwargs: dict[str, Any] = {
        "model": CLAUDE_MODEL,
        "max_tokens": 8096,
        "temperature": 0.1,
        "messages": built_messages,
    }
    if system_prompt:
        kwargs["system"] = system_prompt
    if tools:
        kwargs["tools"] = tools

    delays = [1, 4, 16]
    last_error: Exception | None = None

    for attempt, delay in enumerate(delays, start=1):
        try:
            logger.info(
                "Calling Claude API",
                model=CLAUDE_MODEL,
                attempt=attempt,
                use_web_search=use_web_search,
            )
            text_parts: list[str] = []

            async with client.messages.stream(**kwargs) as stream:
                async for event in stream:
                    # Collect text deltas
                    pass
                final_msg = await stream.get_final_message()

            # Extract text from response
            for block in final_msg.content:
                if hasattr(block, "text"):
                    text_parts.append(block.text)
                elif hasattr(block, "type") and block.type == "text":
                    text_parts.append(block.text)

            result = "".join(text_parts)
            logger.info("Claude API call successful", chars=len(result))
            return result

        except anthropic.RateLimitError as e:
            last_error = e
            logger.warning(
                "Claude rate limit hit, retrying",
                attempt=attempt,
                delay=delay,
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
                )
                if attempt < len(delays):
                    await asyncio.sleep(delay)
            else:
                logger.error("Claude API error", status_code=e.status_code, error=str(e))
                raise

        except Exception as e:
            logger.error("Unexpected Claude API error", error=str(e))
            raise

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
