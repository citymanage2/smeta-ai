"""Разбивка токенов по последним сметам (ESTIMATE_FROM_LIST) из api_call_log.

Запуск в Render Shell web-сервиса (psql там нет, а asyncpg есть):

    cd /app && python backend/scripts/token_breakdown_estimates.py

Читает DATABASE_URL из окружения, сам убирает '+asyncpg' для asyncpg.connect.
"""
import asyncio
import os

import asyncpg

LIMIT = 20


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


async def main() -> None:
    conn = await asyncpg.connect(_dsn())
    try:
        per_task = await conn.fetch(
            """
            SELECT t.id, t.created_at::date AS date, t.cost AS estimate_cost_rub,
                   count(l.id) AS api_calls,
                   sum(l.input_tokens) AS input_t,
                   sum(l.output_tokens) AS output_t,
                   sum(l.cache_read_tokens) AS cache_read_t,
                   sum(l.cache_creation_tokens) AS cache_creation_t,
                   sum(l.input_tokens + l.output_tokens
                       + l.cache_read_tokens + l.cache_creation_tokens) AS total_t,
                   round(sum(l.cost_usd), 4) AS cost_usd
            FROM tasks t
            JOIN api_call_log l ON l.task_id = t.id
            WHERE t.task_type = 'ESTIMATE_FROM_LIST'
            GROUP BY t.id, t.created_at, t.cost
            ORDER BY t.created_at DESC
            LIMIT $1
            """,
            LIMIT,
        )
        _print_table(f"1. Пер-таск: последние {LIMIT} смет", per_task)

        averages = await conn.fetch(
            """
            WITH per_task AS (
                SELECT t.id,
                       count(l.id) AS api_calls,
                       sum(l.input_tokens) AS input_t,
                       sum(l.output_tokens) AS output_t,
                       sum(l.cache_read_tokens) AS cache_read_t,
                       sum(l.cache_creation_tokens) AS cache_creation_t,
                       sum(l.cost_usd) AS cost_usd
                FROM tasks t
                JOIN api_call_log l ON l.task_id = t.id
                WHERE t.task_type = 'ESTIMATE_FROM_LIST'
                GROUP BY t.id, t.created_at
                ORDER BY t.created_at DESC
                LIMIT $1
            )
            SELECT count(*) AS tasks,
                   round(avg(api_calls), 1) AS avg_api_calls,
                   round(avg(input_t)) AS avg_input_t,
                   round(avg(output_t)) AS avg_output_t,
                   round(avg(cache_read_t)) AS avg_cache_read_t,
                   round(avg(cache_creation_t)) AS avg_cache_creation_t,
                   round(avg(cost_usd), 4) AS avg_cost_usd
            FROM per_task
            """,
            LIMIT,
        )
        _print_table(f"2. Средние на одну смету (по последним {LIMIT})", averages)

        shares = await conn.fetch(
            """
            WITH per_task AS (
                SELECT l.input_tokens, l.output_tokens,
                       l.cache_read_tokens, l.cache_creation_tokens
                FROM tasks t
                JOIN api_call_log l ON l.task_id = t.id
                WHERE t.task_type = 'ESTIMATE_FROM_LIST'
                  AND t.id IN (
                      SELECT id FROM tasks
                      WHERE task_type = 'ESTIMATE_FROM_LIST'
                      ORDER BY created_at DESC LIMIT $1
                  )
            )
            SELECT sum(input_tokens) AS input_t,
                   sum(output_tokens) AS output_t,
                   sum(cache_read_tokens) AS cache_read_t,
                   sum(cache_creation_tokens) AS cache_creation_t,
                   round(100.0 * sum(input_tokens)          / nullif(sum(input_tokens+output_tokens+cache_read_tokens+cache_creation_tokens),0), 1) AS input_pct,
                   round(100.0 * sum(output_tokens)         / nullif(sum(input_tokens+output_tokens+cache_read_tokens+cache_creation_tokens),0), 1) AS output_pct,
                   round(100.0 * sum(cache_read_tokens)     / nullif(sum(input_tokens+output_tokens+cache_read_tokens+cache_creation_tokens),0), 1) AS cache_read_pct,
                   round(100.0 * sum(cache_creation_tokens) / nullif(sum(input_tokens+output_tokens+cache_read_tokens+cache_creation_tokens),0), 1) AS cache_creation_pct
            FROM per_task
            """,
            LIMIT,
        )
        _print_table(f"3. Доля типов токенов (по последним {LIMIT})", shares)

        calls = await conn.fetch(
            """
            SELECT l.called_at, l.input_tokens, l.output_tokens,
                   l.cache_read_tokens, l.cache_creation_tokens,
                   round(l.cost_usd, 4) AS cost_usd
            FROM api_call_log l
            WHERE l.task_id = (
                SELECT id FROM tasks
                WHERE task_type = 'ESTIMATE_FROM_LIST'
                ORDER BY created_at DESC LIMIT 1
            )
            ORDER BY l.called_at
            """
        )
        _print_table("4. Вызовы внутри самой свежей сметы", calls)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
