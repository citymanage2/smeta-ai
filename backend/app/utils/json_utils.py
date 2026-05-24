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
    - Minor JSON syntax errors (repaired via json-repair if available)

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
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence_match:
        inner = fence_match.group(1).strip()
        try:
            return json.loads(inner)
        except json.JSONDecodeError:
            if inner:
                text = inner

    # ── Step 3: slice from first { to last } ────────────────────────────
    start = text.find("{")
    end = text.rfind("}")
    sliced = text[start : end + 1] if start != -1 and end != -1 and end > start else None
    if sliced:
        try:
            return json.loads(sliced)
        except json.JSONDecodeError:
            pass

    # ── Step 4: regex DOTALL — find the outermost {...} object ──────────
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass

    # ── Step 5: json-repair — fixes trailing commas, unescaped chars, etc. ──
    candidates = [c for c in [sliced, text] if c]
    for candidate in candidates:
        try:
            from json_repair import repair_json  # type: ignore[import]
            repaired = repair_json(candidate, return_objects=True)
            if isinstance(repaired, dict) and repaired:
                logger.warning(
                    "extract_json: used json-repair fallback",
                    preview=candidate[:200],
                )
                return repaired
        except Exception:
            pass

    logger.error(
        "extract_json: could not extract valid JSON from Claude response",
        response_preview=text[:1000],
    )
    raise ValueError(
        f"Could not extract valid JSON from response. First 200 chars: {text[:200]}"
    )
