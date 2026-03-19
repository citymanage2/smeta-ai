import json
import re
import structlog

logger = structlog.get_logger()


def extract_json(text: str) -> dict:
    """
    Robustly extract JSON from a Claude API response that may contain:
    - Markdown code fences: ```json ... ``` or ``` ... ```
    - Preamble text before the JSON object
    - Trailing text after the JSON object
    - Mixed whitespace / newlines

    Raises ValueError if no valid JSON object can be extracted.
    """
    if not text:
        raise ValueError("Empty response from Claude")

    # Step 1: direct parse (fastest path — Claude returned clean JSON)
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # Step 2: strip ALL markdown code fences, then parse
    cleaned = re.sub(r"```(?:json)?\s*", "", text)
    cleaned = re.sub(r"```\s*$", "", cleaned, flags=re.MULTILINE)
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Step 3: regex — find the outermost {...} spanning the full object
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass

    # Step 4: slice from first { to last } on the original text
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    logger.error(
        "extract_json: could not extract valid JSON from Claude response",
        response_preview=text[:500],
    )
    raise ValueError(
        f"Could not extract valid JSON from response. First 200 chars: {text[:200]}"
    )
