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


class ResponseTruncatedError(ValueError):
    """Ответ упёрся в max_tokens и оборван на полуслове.

    Отдельный тип, потому что повторять ТОТ ЖЕ запрос бессмысленно: промпт не
    изменился, значит ответ снова не поместится. Раньше это был голый ValueError,
    его ретраил _call_claude_json_with_retry — три полных вызова по 32k output
    (~$1.44), все оплаченные и все обречённые. Caller должен уменьшить порцию
    данных (разбить чанк), а не повторять запрос.

    Наследуется от ValueError для обратной совместимости с `except ValueError`.
    """


class InsufficientBalanceError(RuntimeError):
    """Anthropic API отклонил запрос из-за исчерпанного баланса счёта.

    Отдельный тип (а не голый RuntimeError), чтобы вызывающий код мог перевести
    задачу на паузу (`paused`) и автоматически возобновить её после пополнения,
    вместо перевода в `failed`. Наследуется от RuntimeError для обратной
    совместимости с существующими `except RuntimeError`.

    `status_code`/`api_message` — сырой ответ API. Нужны, чтобы показать в UI
    ФАКТИЧЕСКУЮ причину: на сервере запросы идут через агрегатор
    (`ANTHROPIC_BASE_URL`), и «баланс исчерпан» может означать баланс агрегатора,
    а не Anthropic. Без этих деталей диагноз возможен только по логам worker'а.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        api_message: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.api_message = api_message


# Маркеры «баланс исчерпан» в тексте/коде ошибки. Anthropic шлёт "credit
# balance"; но запросы могут идти через агрегатор/прокси (settings base_url),
# который отдаёт свою формулировку/код — поэтому список шире. Держим его
# КОНСЕРВАТИВНЫМ: ложное срабатывание => задача уходит в paused и поллер
# ретраит её каждые 10 мин (вместо честного failed), поэтому сюда попадают
# только однозначно балансовые сигналы, без общих слов вроде "quota"/"payment".
_BALANCE_ERROR_MARKERS: tuple[str, ...] = (
    "credit balance",
    "insufficient balance",
    "insufficient funds",
    "insufficient_quota",
    "balance is too low",
    "out of credit",
    "недостаточно средств",
    "недостаточно баланса",
)


def _is_insufficient_balance(status_code: Optional[int], *texts: str) -> bool:
    """True, если ошибка означает исчерпанный баланс. 402 Payment Required —
    однозначный billing-статус; иначе — по маркерам в тексте/коде ошибки."""
    if status_code == 402:
        return True
    haystack = " ".join(t for t in texts if t).lower()
    return any(marker in haystack for marker in _BALANCE_ERROR_MARKERS)


def _raise_if_insufficient_balance(e: "anthropic.APIStatusError") -> None:
    """Если APIStatusError — про исчерпанный баланс, поднять InsufficientBalanceError.
    Иначе ничего не делает (вызывающий код сам решает, что с исходной ошибкой)."""
    body = getattr(e, "body", None) or {}
    err = body.get("error", {}) if isinstance(body, dict) else {}
    err_msg = err.get("message", "") if isinstance(err, dict) else ""
    err_code = (err.get("code") or err.get("type") or "") if isinstance(err, dict) else ""
    status_code = getattr(e, "status_code", None)
    if _is_insufficient_balance(status_code, err_msg, str(err_code), str(e)):
        raise InsufficientBalanceError(
            "Баланс API Anthropic меньше 0. Обратитесь к администратору сервиса",
            status_code=status_code,
            api_message=(err_msg or str(e) or "")[:300],
        ) from e

# Плата за один web-поиск: $10 / 1000 запросов. В токенах НЕ отражается —
# считается отдельной строкой счёта Anthropic (Total web search cost).
WEB_SEARCH_COST_PER_REQUEST = 10.0 / 1000

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
    web_search_requests: int = 0,
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
    # Поиски тарифицируются отдельно от токенов. Скидку batch на них НЕ применяем:
    # это консервативная оценка — лучше слегка завысить, чем снова не увидеть 22%.
    total += web_search_requests * WEB_SEARCH_COST_PER_REQUEST
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


def _extract_usage(usage) -> tuple[int, int, int, int, int]:
    """(input, output, cache_read, cache_creation, web_search_requests) из usage.

    web_search_requests лежит в usage.server_tool_use.web_search_requests и есть
    только когда в вызове был web search; иначе 0.
    """
    server_tool_use = getattr(usage, "server_tool_use", None)
    searches = getattr(server_tool_use, "web_search_requests", 0) or 0 if server_tool_use else 0
    return (
        getattr(usage, "input_tokens", 0) or 0,
        getattr(usage, "output_tokens", 0) or 0,
        getattr(usage, "cache_read_input_tokens", 0) or 0,
        getattr(usage, "cache_creation_input_tokens", 0) or 0,
        int(searches),
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
    web_search_requests: int = 0,
    batch_id: Optional[str] = None,
    batch_custom_id: Optional[str] = None,
) -> None:
    """Записать вызов в ApiCallLog (отдельной сессией). batch=True → тарифы ×0.5.

    duration_ms — длительность самого API-вызова (None для batch: там нет
    синхронного времени ответа, пачка считается на серверах Anthropic).
    web_search_requests — число поисков; тарифицируется отдельно от токенов.
    batch_id/batch_custom_id — координаты записи в пачке. Заданы → повторный сбор
    той же пачки (resume после рестарта поллера) не создаёт дубль строки.
    """
    if db is None or task_id is None:
        return
    try:
        from sqlalchemy import select

        from app.models.api_call_log import ApiCallLog
        from app.database import AsyncSessionLocal
        cost = _calc_cost(
            CLAUDE_MODEL, input_t, output_t, cache_read_t, cache_creation_t,
            batch=batch, web_search_requests=web_search_requests,
        )
        log_entry = ApiCallLog(
            task_id=task_id,
            model=CLAUDE_MODEL,
            input_tokens=input_t,
            output_tokens=output_t,
            cache_read_tokens=cache_read_t,
            cache_creation_tokens=cache_creation_t,
            web_search_requests=web_search_requests,
            cost_usd=cost,
            duration_ms=duration_ms,
            batch_id=batch_id,
            batch_custom_id=batch_custom_id,
        )
        # Независимая сессия — caller может параллельно использовать свою db (cancel-checks).
        async with AsyncSessionLocal() as log_db:
            if batch_id and batch_custom_id:
                already = await log_db.execute(
                    select(ApiCallLog.id)
                    .where(
                        ApiCallLog.batch_id == batch_id,
                        ApiCallLog.batch_custom_id == batch_custom_id,
                    )
                    .limit(1)
                )
                if already.scalar_one_or_none() is not None:
                    logger.info(
                        "Batch entry already logged, skipping duplicate",
                        batch_id=batch_id, custom_id=batch_custom_id,
                    )
                    return
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
    # Потолок поисков внутри одного вызова. Без него web search — 22% счёта
    # Anthropic (замер 28.07.2026), и он полностью невидим в api_call_log.
    "max_uses": settings.WEB_SEARCH_MAX_USES,
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

# Ленивый singleton клиента Anthropic: создаётся при первом вызове и кэшируется
# в модульной переменной. base_url и X-Proxy-Secret подставляются из env условно —
# код одинаков локально (прямой доступ) и на сервере (через посредника), вся
# разница только в env.
_client: Optional[anthropic.AsyncAnthropic] = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        if not settings.ANTHROPIC_API_KEY:
            raise RuntimeError(
                "ANTHROPIC_API_KEY не задан. Укажите ключ в .env "
                "(локально — ключ Anthropic; на сервере — ключ агрегатора "
                "или настоящий ключ при своём прокси)."
            )
        kwargs: dict[str, Any] = {
            "api_key": settings.ANTHROPIC_API_KEY,
            "http_client": _http_client,
        }
        if settings.ANTHROPIC_BASE_URL:
            kwargs["base_url"] = settings.ANTHROPIC_BASE_URL
        if settings.ANTHROPIC_PROXY_SECRET:
            kwargs["default_headers"] = {"X-Proxy-Secret": settings.ANTHROPIC_PROXY_SECRET}
        _client = anthropic.AsyncAnthropic(**kwargs)
    return _client

# Глобальный лимит одновременных вызовов Anthropic на процесс. При N параллельных
# задачах × M чанков суммарная конкуренция упирается в этот семафор — защита от
# каскада 429. Сам rate-limit sleep семафор НЕ держит.
# Под семафором: messages.create (+web search) и быстрые batch-вызовы (submit/poll/
# cancel). collect_claude_batch НЕ оборачиваем — это длинный стрим результатов,
# держать на нём слот значило бы морозить обычные create (P3-b).
_anthropic_semaphore = asyncio.Semaphore(settings.ANTHROPIC_MAX_CONCURRENCY)


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

    processing_timeout — if set, wraps ONLY the _get_client().messages.create() call
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
            async with _anthropic_semaphore:
                if remaining is not None:
                    sdk_kwargs = {**kwargs, "timeout": remaining}
                    response = await asyncio.wait_for(
                        _get_client().messages.create(**sdk_kwargs),
                        timeout=remaining,
                    )
                else:
                    response = await _get_client().messages.create(**kwargs)
            call_duration_ms = int((asyncio.get_event_loop().time() - attempt_start) * 1000)

            input_t, output_t, cache_read_t, cache_creation_t, searches_t = _extract_usage(
                response.usage
            )

            # Detect output truncation before trying to use the response.
            if response.stop_reason == "max_tokens":
                logger.error(
                    "Claude response truncated: max_tokens limit reached",
                    chars=sum(
                        len(b.text) for b in response.content if hasattr(b, "text")
                    ),
                    max_tokens=kwargs["max_tokens"],
                    output_tokens=output_t,
                )
                # Оборванный ответ всё равно оплачен — логируем ДО падения,
                # иначе эти токены не видны ни в метрике, ни в разборе трат.
                await _log_api_call(
                    task_id, db, input_t, output_t, cache_read_t, cache_creation_t,
                    duration_ms=call_duration_ms, web_search_requests=searches_t,
                )
                raise ResponseTruncatedError(
                    "Ответ слишком большой, разбейте выполнение на подэтапы"
                )

            # Extract the final text (prefer last block containing JSON).
            result = _extract_result_text(response.content)

            logger.info(
                "Claude API call successful",
                chars=len(result),
                attempt=attempt,
                cache_read_tokens=cache_read_t,
                cache_creation_tokens=cache_creation_t,
                web_search_requests=searches_t,
                duration_ms=call_duration_ms,
            )

            await _log_api_call(
                task_id, db, input_t, output_t, cache_read_t, cache_creation_t,
                duration_ms=call_duration_ms, web_search_requests=searches_t,
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
                # Билинг (исчерпанный баланс) → типизированная ошибка для paused;
                # распознаётся расширенно (402 + маркеры), в т.ч. через прокси.
                _raise_if_insufficient_balance(e)
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


async def api_ping() -> dict:
    """Пробный минимальный вызов API (max_tokens=1, без web search) — «есть ли
    деньги и доступ прямо сейчас».

    У Anthropic нет API проверки баланса, поэтому единственный честный способ —
    сделать запрос. Стоимость пренебрежимо мала (единицы токенов). Возвращает
    диагностический словарь БЕЗ секретов: куда идут запросы (base_url), заданы ли
    ключ/секрет прокси, и сырой ответ при ошибке.
    """
    info: dict = {
        "base_url": settings.ANTHROPIC_BASE_URL or "https://api.anthropic.com (напрямую)",
        "via_proxy": bool(settings.ANTHROPIC_BASE_URL),
        "api_key_set": bool(settings.ANTHROPIC_API_KEY),
        "proxy_secret_set": bool(settings.ANTHROPIC_PROXY_SECRET),
        "model": CLAUDE_MODEL,
    }
    try:
        async with _anthropic_semaphore:
            await _get_client().messages.create(
                model=CLAUDE_MODEL,
                max_tokens=1,
                messages=[{"role": "user", "content": "ping"}],
            )
        return {**info, "ok": True, "status_code": 200, "error": None, "is_balance_error": False}
    except anthropic.APIStatusError as e:
        body = getattr(e, "body", None) or {}
        err = body.get("error", {}) if isinstance(body, dict) else {}
        err_msg = err.get("message", "") if isinstance(err, dict) else ""
        err_code = (err.get("code") or err.get("type") or "") if isinstance(err, dict) else ""
        status_code = getattr(e, "status_code", None)
        is_balance = _is_insufficient_balance(status_code, err_msg, str(err_code), str(e))
        logger.warning(
            "API ping failed", status_code=status_code, error=err_msg or str(e), is_balance=is_balance
        )
        return {
            **info,
            "ok": False,
            "status_code": status_code,
            "error": (err_msg or str(e) or "")[:500],
            "error_code": str(err_code) or None,
            "is_balance_error": is_balance,
        }
    except Exception as e:
        logger.warning("API ping failed (non-status error)", error=str(e) or repr(e))
        return {
            **info,
            "ok": False,
            "status_code": None,
            "error": (str(e) or repr(e))[:500],
            "error_code": type(e).__name__,
            "is_balance_error": False,
        }


async def submit_claude_batch(requests: list[dict]) -> str:
    """Отправить пачку запросов. Возвращает batch_id (msgbatch_...).

    При исчерпанном балансе поднимает InsufficientBalanceError (не голый
    APIStatusError) — чтобы batch-задача ушла в paused и авто-возобновилась
    после пополнения, а не упала в failed."""
    async with _anthropic_semaphore:
        try:
            batch = await _get_client().messages.batches.create(requests=requests)
        except anthropic.APIStatusError as e:
            _raise_if_insufficient_balance(e)
            raise
    logger.info("Claude batch submitted", batch_id=batch.id, count=len(requests))
    return batch.id


async def poll_claude_batch(batch_id: str) -> str:
    """Вернуть processing_status пачки ('in_progress' | 'ended' | ...)."""
    async with _anthropic_semaphore:
        batch = await _get_client().messages.batches.retrieve(batch_id)
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
    stream = _get_client().messages.batches.results(batch_id)
    if inspect.isawaitable(stream):
        stream = await stream

    async for entry in stream:
        cid = entry.custom_id
        rtype = entry.result.type
        if rtype == "succeeded":
            msg = entry.result.message
            text = _extract_result_text(msg.content)
            input_t, output_t, cache_read_t, cache_creation_t, searches_t = _extract_usage(
                msg.usage
            )
            out[cid] = {
                "text": text,
                "error": None,
                "usage": {
                    "input": input_t,
                    "output": output_t,
                    "cache_read": cache_read_t,
                    "cache_creation": cache_creation_t,
                    "web_search_requests": searches_t,
                },
            }
            await _log_api_call(
                task_id, db, input_t, output_t, cache_read_t, cache_creation_t,
                batch=True, web_search_requests=searches_t,
                batch_id=batch_id, batch_custom_id=cid,
            )
        else:
            # errored | canceled | expired
            out[cid] = {"text": None, "error": rtype, "usage": None}
            logger.warning("Claude batch entry not succeeded", custom_id=cid, type=rtype)

    logger.info("Claude batch collected", batch_id=batch_id, count=len(out))
    return out


async def cancel_claude_batch(batch_id: str) -> None:
    """Отменить пачку (при отмене задачи)."""
    async with _anthropic_semaphore:
        await _get_client().messages.batches.cancel(batch_id)
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
