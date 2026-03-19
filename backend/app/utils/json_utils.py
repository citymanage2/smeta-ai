import json
import re
import structlog

logger = structlog.get_logger()


def extract_json(text: str) -> dict:
    """
    Robustly extract JSON from a Claude API response that may contain:
    - Markdown code fences: ```json ... ``` or ``` ... ```
    - Preamble text before the JSON object
    - Trailing text / explanations after the JSON object
    - Mixed whitespace / newlines

    Raises ValueError if no valid JSON object can be extracted.
    """
    if not text:
        raise ValueError("Empty response from Claude")

    text = text.strip()

    # ── Step 1: direct parse (clean JSON, fastest path) ──────────────────
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # ── Step 2: extract content captured BETWEEN fence markers ───────────
    # Uses a non-greedy group so we get exactly what's inside the first
    # ```json ... ``` or ``` ... ``` block, ignoring everything outside.
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence_match:
        inner = fence_match.group(1).strip()
        try:
            return json.loads(inner)
        except json.JSONDecodeError:
            # The fence content itself isn't valid JSON — fall through
            # using inner as the search base for subsequent steps
            if inner:
                text = inner

    # ── Step 3: slice from first { to last } ────────────────────────────
    # Handles preamble/trailing prose that survived Step 2.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    # ── Step 4: regex DOTALL — find the outermost {...} object ──────────
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass

    logger.error(
        "extract_json: could not extract valid JSON from Claude response",
        response_preview=text[:500],
    )
    raise ValueError(
        f"Could not extract valid JSON from response. First 200 chars: {text[:200]}"
    )
