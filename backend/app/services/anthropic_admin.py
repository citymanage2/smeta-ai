"""Официальный отчёт Anthropic о тратах — `GET /v1/organizations/cost_report`.

Почему сырой HTTP, а не SDK: usage- и cost-отчётов в SDK Anthropic нет вовсе (в
`client.beta.organization` живёт управление организацией — люди, ключи,
воркспейсы, — а отчёты остались curl-only). Поэтому httpx.

Три вещи, которые здесь легко сделать неправильно:

1. **`amount` приходит в ЦЕНТАХ и строкой.** `"123.45"` при `currency: "USD"` —
   это $1.23, а не $123.45. Ошибка в сто раз, причём в сторону «денег нет».
   Переводим один раз, на границе, чтобы дальше по коду ходили только доллары.
2. **Ключ.** Отчёт принимает админский ключ (`sk-ant-admin01-...`), OAuth-токен с
   `org:admin` и обычный ключ, НЕ привязанный к конкретному workspace. Поэтому
   берём `ANTHROPIC_ADMIN_KEY`, а если его нет — рабочий ключ сервиса: он может
   подойти, и тогда сверка заводится без единого действия в Console. Не подойдёт
   — придёт 401/403, и остаток посчитается по собственному журналу.
3. **Запрос идёт тем же маршрутом, что и вызовы модели.** На проде РФ-IP закрыт
   геоблоком, и весь трафик идёт через свой прокси (`ANTHROPIC_BASE_URL`).
   Админский запрос — не исключение, иначе он упрётся в 403 на эдже.

День без трат возвращается бакетом с пустым `results`. Это ноль, а не «нет
данных»: пропустить такой день — оставить его несинхронизированным навсегда.

План: plans/2026-09-01-ostatok-deneg-na-api.md, Фаза 3.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Optional

import httpx
import structlog

from app.config import settings

logger = structlog.get_logger()

API_BASE = "https://api.anthropic.com"
COST_REPORT_PATH = "/v1/organizations/cost_report"
ANTHROPIC_VERSION = "2023-06-01"

# Отчёт отдаёт не больше 31 бакета за запрос (лимит эндпоинта).
MAX_BUCKETS = 31
# Полить чаще раза в минуту документация не разрешает, поэтому таймаут щедрый:
# лучше подождать, чем считать сверку сломанной и показать устаревшие данные.
REQUEST_TIMEOUT = 30.0
# Сотня центов в долларе. Вынесено константой, чтобы деление нельзя было
# «оптимизировать» мимо теста.
CENTS_IN_USD = Decimal("100")


class AdminApiError(RuntimeError):
    """Anthropic не отдал отчёт: неверный ключ, недоступность, неожиданный ответ.

    Отдельный тип, чтобы вызывающий отличил «сверка сломалась» (показываем
    последние известные данные и время последней удачной сверки) от «ключа нет»
    (сверка не подключена вовсе — это норма, а не поломка).
    """


def _credential() -> str:
    """Чем авторизуемся в отчёте о тратах.

    Админский ключ, если задан, иначе рабочий ключ сервиса. Второе не костыль:
    отчёт принимает три вида учётных данных — админский ключ, OAuth-токен с
    `org:admin` и **обычный ключ, не привязанный к конкретному workspace**.
    Рабочий ключ сервиса как раз может быть таким, и тогда сверка работает без
    единого действия в Console. Не подойдёт (ключ привязан к workspace, или
    организация личная) — придёт 401/403, он будет пойман, а остаток продолжит
    считаться по собственному журналу вызовов.
    """
    return settings.ANTHROPIC_ADMIN_KEY or settings.ANTHROPIC_API_KEY


def is_configured() -> bool:
    """Есть ли чем авторизоваться. Работает ли оно — покажет только запрос."""
    return bool(_credential())


def _base_url() -> str:
    """Тот же маршрут, что и у вызовов модели: с РФ-IP напрямую нельзя.

    Хвост `/v1` отрезаем: SDK Anthropic ожидает базу без него и сам дописывает
    путь, поэтому в env лежит база без версии — но посредника могут настроить и
    с ней. Не отрезав, мы бы стучались в `/v1/v1/organizations/...` и получали
    404, неотличимый в UI от «отчёт недоступен».
    """
    base = (settings.ANTHROPIC_BASE_URL or API_BASE).rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    return base


async def _request(params: dict) -> dict:
    """Один GET к cost_report. Вынесен отдельно — на нём стоят тесты."""
    headers = {
        "x-api-key": _credential(),
        "anthropic-version": ANTHROPIC_VERSION,
        # Просьба документации к интеграциям — представляться.
        "user-agent": "smeta-ai/1.0 (internal cost monitor)",
    }
    if settings.ANTHROPIC_PROXY_SECRET:
        headers["X-Proxy-Secret"] = settings.ANTHROPIC_PROXY_SECRET

    url = f"{_base_url()}{COST_REPORT_PATH}"
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(url, params=params, headers=headers)
    except httpx.HTTPError as exc:
        raise AdminApiError(f"Отчёт о тратах недоступен: {exc}") from exc

    if response.status_code != 200:
        # Текст ответа нужен целиком: 401 от Anthropic и 401 от нашего прокси
        # различаются только им, а лечатся по-разному.
        raise AdminApiError(
            f"Отчёт о тратах: HTTP {response.status_code} {response.text[:300]}"
        )
    try:
        return response.json()
    except ValueError as exc:
        raise AdminApiError(f"Отчёт о тратах: ответ не JSON ({exc})") from exc


def _day_of(bucket: dict) -> Optional[date]:
    """Дата бакета из `starting_at` (RFC 3339, всегда UTC)."""
    raw = bucket.get("starting_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _rfc3339(day: date) -> str:
    return datetime.combine(day, time.min, tzinfo=timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )


async def fetch_cost_days(
    starting_at: date, ending_at: date
) -> Optional[dict[date, Decimal]]:
    """Официальные траты по дням, в долларах. None — админ-ключ не задан.

    `starting_at` включительно, `ending_at` исключительно (как у эндпоинта).
    """
    if not is_configured():
        return None

    params = {
        "starting_at": _rfc3339(starting_at),
        "ending_at": _rfc3339(ending_at),
        "bucket_width": "1d",
        "limit": MAX_BUCKETS,
    }

    days: dict[date, Decimal] = {}
    seen_pages = 0
    while True:
        payload = await _request(params=dict(params))
        for bucket in payload.get("data") or []:
            day = _day_of(bucket)
            if day is None:
                continue
            total = Decimal("0")
            for item in bucket.get("results") or []:
                amount = item.get("amount")
                if amount is None:
                    continue
                try:
                    total += Decimal(str(amount)) / CENTS_IN_USD
                except (ArithmeticError, ValueError):
                    # Неразобранная строка суммы — это не повод потерять весь
                    # день: остальные позиции складываем, а факт пишем в лог.
                    logger.warning("Cost report: unparsable amount", amount=amount)
            # Складываем, а не присваиваем: один день может приехать двумя
            # бакетами на разных страницах.
            days[day] = days.get(day, Decimal("0")) + total

        next_page = payload.get("next_page")
        if not payload.get("has_more") or not next_page:
            break
        seen_pages += 1
        if seen_pages > MAX_BUCKETS:
            # Защита от бесконечного курсора: страниц физически не может быть
            # больше, чем дней в запросе.
            logger.warning("Cost report: too many pages, stopping", pages=seen_pages)
            break
        params["page"] = next_page

    return days
