"""Сверка стоимости смет по периодам (asyncpg-версия cost_regression_estimates.sql).

В образе backend нет psql, поэтому на Timeweb запускать так:

    docker compose exec worker python backend/scripts/cost_regression_estimates.py

Читает DATABASE_URL из окружения. Границы периодов — константы P2/P3 ниже.

ВАЖНО: cost_usd в логе — НЕ реальные деньги. Он не учитывает плату за web search,
неуспешные вызовы и наценку посредника, и безусловно уполовинен для batch.
Итоговый вывод делается сверкой блока 7 со списанием у посредника.
"""
import asyncio
import os

import asyncpg

# Границы периодов (по датам коммитов):
#   P1  < P2       — до fast/batch, прямой Anthropic
#   P2  P2..P3     — fast/batch + пауза по балансу, прямой Anthropic
#   P3  >= P3      — через посредника
P2 = "2026-07-21"
P3 = "2026-07-25"


def _dsn() -> str:
    dsn = os.environ["DATABASE_URL"]
    # SQLAlchemy формат: postgresql+asyncpg://...  →  asyncpg нужен postgresql://...
    return dsn.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgres+asyncpg://", "postgres://"
    )


def _print_table(title: str, rows: list[asyncpg.Record]) -> None:
    print(f"\n=== {title} ===")
    if not rows:
        print("(нет данных)")
        return
    cols = list(rows[0].keys())
    data = [[("" if r[c] is None else str(r[c])) for c in cols] for r in rows]
    widths = [max(len(cols[i]), *(len(row[i]) for row in data)) for i in range(len(cols))]
    print(" | ".join(c.ljust(widths[i]) for i, c in enumerate(cols)))
    print("-+-".join("-" * w for w in widths))
    for row in data:
        print(" | ".join(row[i].ljust(widths[i]) for i in range(len(cols))))


Q_PERIODS = """
WITH per_task AS (
    SELECT t.id, t.created_at, t.processing_mode,
           count(l.id) AS calls,
           sum(l.input_tokens) AS input_t,
           sum(l.output_tokens) AS output_t,
           sum(l.cache_read_tokens) AS cache_read_t,
           sum(l.cache_creation_tokens) AS cache_creation_t,
           sum(l.cost_usd) AS cost_usd
    FROM tasks t
    JOIN api_call_log l ON l.task_id = t.id
    WHERE t.task_type = 'ESTIMATE_FROM_LIST'
    GROUP BY t.id, t.created_at, t.processing_mode
)
SELECT CASE WHEN created_at < $1::timestamptz THEN '1. до fast/batch'
            WHEN created_at < $2::timestamptz THEN '2. fast/batch, напрямую'
            ELSE '3. через посредника' END AS period,
       count(*) AS tasks,
       round(avg(calls), 1) AS avg_calls,
       round(avg(input_t)) AS avg_input_t,
       round(avg(output_t)) AS avg_output_t,
       round(avg(cache_read_t)) AS avg_cache_read_t,
       round(avg(cache_creation_t)) AS avg_cache_creation_t,
       round(avg(cost_usd), 4) AS avg_cost_usd,
       round(avg(cost_usd) / nullif(avg(calls), 0), 4) AS avg_cost_per_call,
       round(sum(cost_usd), 2) AS total_cost_usd
FROM per_task
GROUP BY 1
ORDER BY 1
"""

Q_WEEKLY = """
WITH per_task AS (
    SELECT t.id, t.created_at, count(l.id) AS calls, sum(l.cost_usd) AS cost_usd
    FROM tasks t
    JOIN api_call_log l ON l.task_id = t.id
    WHERE t.task_type = 'ESTIMATE_FROM_LIST'
    GROUP BY t.id, t.created_at
)
SELECT date_trunc('week', created_at)::date AS week,
       count(*) AS tasks,
       round(avg(calls), 1) AS avg_calls,
       round(avg(cost_usd), 4) AS avg_cost_usd,
       round(sum(cost_usd), 2) AS total_cost_usd
FROM per_task
GROUP BY 1
ORDER BY 1
"""

Q_MODES = """
WITH per_task AS (
    SELECT t.id, t.created_at, t.processing_mode,
           count(l.id) AS calls, sum(l.cost_usd) AS cost_usd
    FROM tasks t
    JOIN api_call_log l ON l.task_id = t.id
    WHERE t.task_type = 'ESTIMATE_FROM_LIST'
      AND t.created_at >= $1::timestamptz
    GROUP BY t.id, t.created_at, t.processing_mode
)
SELECT processing_mode,
       CASE WHEN created_at < $2::timestamptz THEN 'напрямую' ELSE 'посредник' END AS route,
       count(*) AS tasks,
       round(avg(calls), 1) AS avg_calls,
       round(avg(cost_usd), 4) AS avg_cost_usd
FROM per_task
GROUP BY 1, 2
ORDER BY 1, 2
"""

# Одинаковый usage на одной задаче среди batch-вызовов (duration_ms IS NULL)
# почти наверняка означает повторно залогированный сбор той же пачки.
Q_DUP_TOTAL = """
WITH dup AS (
    SELECT task_id, count(*) AS n, min(cost_usd) AS cost_usd
    FROM api_call_log
    WHERE duration_ms IS NULL AND task_id IS NOT NULL
    GROUP BY task_id, input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens
    HAVING count(*) > 1
)
SELECT count(*) AS dup_groups,
       sum(n - 1) AS extra_rows,
       round(sum((n - 1) * cost_usd), 2) AS overcounted_usd
FROM dup
"""

Q_DUP_TOP = """
SELECT task_id, sum(n - 1) AS extra_rows, round(sum((n - 1) * cost_usd), 4) AS overcounted_usd
FROM (
    SELECT task_id, count(*) AS n, min(cost_usd) AS cost_usd
    FROM api_call_log
    WHERE duration_ms IS NULL AND task_id IS NOT NULL
    GROUP BY task_id, input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens
    HAVING count(*) > 1
) d
GROUP BY task_id
ORDER BY extra_rows DESC
LIMIT 10
"""

# В логе batch тарифицируется ×0.5 безусловно (claude_service.py:118-120).
# Если посредник скидку не даёт — реальная стоимость batch вдвое выше залогированной.
Q_BATCH_DISCOUNT = """
SELECT round(sum(cost_usd) FILTER (WHERE duration_ms IS NULL), 2) AS batch_logged_usd,
       round(sum(cost_usd) FILTER (WHERE duration_ms IS NULL) * 2, 2) AS batch_if_no_discount_usd,
       round(sum(cost_usd) FILTER (WHERE duration_ms IS NOT NULL), 2) AS sync_logged_usd
FROM api_call_log
"""

# До миграции 038 число поисков не писалось: у старых строк 0, и для них
# остаётся только вилка-оценка. У новых — факт из usage.server_tool_use.
Q_SEARCH = """
SELECT count(*) AS calls,
       count(*) FILTER (WHERE l.web_search_requests > 0) AS calls_with_known_searches,
       sum(l.web_search_requests) AS searches_known,
       round(sum(l.web_search_requests) * 0.01, 2) AS search_usd_known,
       round(avg(l.web_search_requests) FILTER (WHERE l.web_search_requests > 0), 1)
           AS avg_searches_per_call,
       round(count(*) FILTER (WHERE l.web_search_requests = 0) * 4 * 0.01, 2)
           AS search_usd_estimate_for_old_rows
FROM api_call_log l
JOIN tasks t ON t.id = l.task_id
WHERE t.task_type = 'ESTIMATE_FROM_LIST'
"""

# Эффект выката max_uses. Границу не задаём руками: первая строка с
# web_search_requests > 0 и есть первый вызов на новой версии кода.
# cost_usd после выката включает плату за поиск, до — нет, поэтому для
# сопоставимости считаем и «только токены».
Q_EFFECT = """
WITH cutoff AS (
    SELECT min(called_at) AS t FROM api_call_log WHERE web_search_requests > 0
),
per_task AS (
    SELECT t.id, t.created_at,
           count(l.id) AS calls,
           sum(l.web_search_requests) AS searches,
           sum(l.cost_usd) AS cost_usd,
           sum(l.cost_usd - l.web_search_requests * 0.01) AS cost_tokens_only
    FROM tasks t
    JOIN api_call_log l ON l.task_id = t.id
    WHERE t.task_type = 'ESTIMATE_FROM_LIST'
    GROUP BY t.id, t.created_at
)
SELECT CASE WHEN p.created_at < c.t THEN '1. до выката max_uses'
            ELSE '2. после' END AS period,
       count(*) AS tasks,
       round(avg(p.calls), 1) AS avg_calls,
       round(avg(p.searches), 1) AS avg_searches,
       round(avg(p.searches) / nullif(avg(p.calls), 0), 1) AS avg_searches_per_call,
       round(avg(p.cost_tokens_only), 4) AS avg_cost_tokens_only,
       round(avg(p.cost_usd), 4) AS avg_cost_total
FROM per_task p CROSS JOIN cutoff c
WHERE c.t IS NOT NULL
GROUP BY 1
ORDER BY 1
"""

# Риск обрезки при увеличении чанка. Основной проход идёт чанками по 10, значит
# output_tokens вызова — это ответ на ~10 позиций. Делим на 10 и смотрим, сколько
# позиций влезет в max_tokens=32000 с запасом 20%.
Q_TRUNCATION_RISK = """
SELECT count(*) AS calls,
       round(avg(l.output_tokens)) AS avg_out,
       percentile_disc(0.95) WITHIN GROUP (ORDER BY l.output_tokens) AS p95_out,
       max(l.output_tokens) AS max_out,
       round(max(l.output_tokens) / 10.0, 1) AS peak_out_per_item,
       floor(32000 * 0.8 / nullif(max(l.output_tokens) / 10.0, 0)) AS safe_chunk_by_peak,
       count(*) FILTER (WHERE l.output_tokens >= 31000) AS calls_near_limit
FROM api_call_log l
JOIN tasks t ON t.id = l.task_id
WHERE t.task_type = 'ESTIMATE_FROM_LIST'
  AND l.output_tokens > 0
"""

Q_MONTHLY = """
SELECT date_trunc('month', l.called_at)::date AS month,
       coalesce(t.task_type, '(без задачи)') AS task_type,
       count(*) AS calls,
       round(sum(l.cost_usd), 2) AS logged_usd
FROM api_call_log l
LEFT JOIN tasks t ON t.id = l.task_id
GROUP BY 1, 2
ORDER BY 1 DESC, logged_usd DESC
"""


async def main() -> None:
    conn = await asyncpg.connect(_dsn())
    try:
        _print_table("1. Сводка по периодам (ESTIMATE_FROM_LIST)",
                     await conn.fetch(Q_PERIODS, P2, P3))
        _print_table("2. Динамика по неделям: растёт ли число вызовов на смету",
                     await conn.fetch(Q_WEEKLY))
        _print_table("3. fast vs batch (периоды 2 и 3)",
                     await conn.fetch(Q_MODES, P2, P3))
        _print_table("4. Дубли batch-строк (повторный сбор пачки)",
                     await conn.fetch(Q_DUP_TOTAL))
        _print_table("4б. Топ-10 задач с дублями", await conn.fetch(Q_DUP_TOP))
        _print_table("5. Если посредник НЕ даёт batch-скидку",
                     await conn.fetch(Q_BATCH_DISCOUNT))
        _print_table("6. Оценка неучтённой платы за web search",
                     await conn.fetch(Q_SEARCH))
        _print_table("7. Итог по месяцам — для сверки со счётом Anthropic",
                     await conn.fetch(Q_MONTHLY))
        _print_table("8. Эффект выката max_uses (граница — первая строка с поисками)",
                     await conn.fetch(Q_EFFECT))
        _print_table("9. Запас до обрезки ответа (можно ли увеличить чанк)",
                     await conn.fetch(Q_TRUNCATION_RISK))
        print(
            "\nСверка: сумму logged_usd за период сравнить с Total cost в консоли\n"
            "Anthropic (platform.claude.com → Cost). После выката они должны почти\n"
            "совпасть: web search теперь входит в cost_usd. Расхождение сверх пары\n"
            "процентов = ещё одна невидимая статья, искать её."
        )
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
