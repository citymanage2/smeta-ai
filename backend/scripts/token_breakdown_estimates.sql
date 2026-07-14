-- Разбивка токенов по последним сметам (ESTIMATE_FROM_LIST) из api_call_log.
-- Запускать на ПРОДЕ (Render → psql $DATABASE_URL или Render Shell).
-- Локально базы smeta_ai нет.

\echo '=== 1. Пер-таск: последние 20 смет ESTIMATE_FROM_LIST ==='
SELECT
    t.id,
    t.created_at::date                              AS date,
    t.cost                                          AS estimate_cost_rub,
    count(l.id)                                     AS api_calls,
    sum(l.input_tokens)                             AS input_t,
    sum(l.output_tokens)                            AS output_t,
    sum(l.cache_read_tokens)                        AS cache_read_t,
    sum(l.cache_creation_tokens)                    AS cache_creation_t,
    sum(l.input_tokens + l.output_tokens
        + l.cache_read_tokens + l.cache_creation_tokens) AS total_t,
    round(sum(l.cost_usd), 4)                       AS cost_usd
FROM tasks t
JOIN api_call_log l ON l.task_id = t.id
WHERE t.task_type = 'ESTIMATE_FROM_LIST'
GROUP BY t.id, t.created_at, t.cost
ORDER BY t.created_at DESC
LIMIT 20;

\echo '=== 2. Средние показатели на одну смету (по последним 20) ==='
WITH per_task AS (
    SELECT
        t.id,
        count(l.id)                  AS api_calls,
        sum(l.input_tokens)          AS input_t,
        sum(l.output_tokens)         AS output_t,
        sum(l.cache_read_tokens)     AS cache_read_t,
        sum(l.cache_creation_tokens) AS cache_creation_t,
        sum(l.cost_usd)              AS cost_usd
    FROM tasks t
    JOIN api_call_log l ON l.task_id = t.id
    WHERE t.task_type = 'ESTIMATE_FROM_LIST'
    GROUP BY t.id, t.created_at
    ORDER BY t.created_at DESC
    LIMIT 20
)
SELECT
    count(*)                              AS tasks,
    round(avg(api_calls), 1)              AS avg_api_calls,
    round(avg(input_t))                   AS avg_input_t,
    round(avg(output_t))                  AS avg_output_t,
    round(avg(cache_read_t))              AS avg_cache_read_t,
    round(avg(cache_creation_t))          AS avg_cache_creation_t,
    round(avg(cost_usd), 4)               AS avg_cost_usd
FROM per_task;

\echo '=== 3. Доля типов токенов (input vs output vs cache) по последним 20 сметам ==='
WITH per_task AS (
    SELECT t.id, l.input_tokens, l.output_tokens,
           l.cache_read_tokens, l.cache_creation_tokens
    FROM tasks t
    JOIN api_call_log l ON l.task_id = t.id
    WHERE t.task_type = 'ESTIMATE_FROM_LIST'
      AND t.id IN (
          SELECT id FROM tasks
          WHERE task_type = 'ESTIMATE_FROM_LIST'
          ORDER BY created_at DESC LIMIT 20
      )
)
SELECT
    sum(input_tokens)          AS input_t,
    sum(output_tokens)         AS output_t,
    sum(cache_read_tokens)     AS cache_read_t,
    sum(cache_creation_tokens) AS cache_creation_t,
    round(100.0 * sum(input_tokens)          / nullif(sum(input_tokens+output_tokens+cache_read_tokens+cache_creation_tokens),0), 1) AS input_pct,
    round(100.0 * sum(output_tokens)         / nullif(sum(input_tokens+output_tokens+cache_read_tokens+cache_creation_tokens),0), 1) AS output_pct,
    round(100.0 * sum(cache_read_tokens)     / nullif(sum(input_tokens+output_tokens+cache_read_tokens+cache_creation_tokens),0), 1) AS cache_read_pct,
    round(100.0 * sum(cache_creation_tokens) / nullif(sum(input_tokens+output_tokens+cache_read_tokens+cache_creation_tokens),0), 1) AS cache_creation_pct
FROM per_task;

\echo '=== 4. Распределение вызовов внутри одной сметы (input на вызов — виден рост от web search) ==='
-- Берём самую свежую смету и показываем каждый её вызов по порядку.
SELECT
    l.called_at,
    l.input_tokens,
    l.output_tokens,
    l.cache_read_tokens,
    l.cache_creation_tokens,
    round(l.cost_usd, 4) AS cost_usd
FROM api_call_log l
WHERE l.task_id = (
    SELECT id FROM tasks
    WHERE task_type = 'ESTIMATE_FROM_LIST'
    ORDER BY created_at DESC LIMIT 1
)
ORDER BY l.called_at;
