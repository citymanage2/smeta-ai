/**
 * Диагностика в админке должна показывать перезапуски обработчика.
 *
 * 30.07.2026 три возобновлённые задачи повисли разом: контейнер обработчика
 * умирал от памяти и поднимался заново. Увидеть это было негде — при OOM-kill
 * процесс не успевает пожаловаться, а лог Timeweb пользователю недоступен.
 *
 * План: plans/2026-07-30-parallelnaya-obrabotka-umiraet.md, Фаза 4.
 */
import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const getApiHealth = vi.fn()
const getQueueHealth = vi.fn()

vi.mock('../api/admin', () => ({
  getApiHealth: (...args: unknown[]) => getApiHealth(...args),
  getQueueHealth: (...args: unknown[]) => getQueueHealth(...args),
}))

import { HealthPanel } from '../pages/Admin'
import type { QueueHealth } from '../api/admin'

const API_OK = {
  checked_at: new Date().toISOString(),
  ok: true,
  status_code: 200,
  error: null,
  base_url: null,
  via_proxy: false,
  api_key_set: true,
  proxy_secret_set: false,
  model: 'claude',
  paused_tasks: 0,
  verdict: 'ok' as const,
  hint: 'API доступен.',
}

function queueHealth(
  restarts: QueueHealth['worker_restarts'],
  rateLimits: QueueHealth['api_rate_limits'] = null
): QueueHealth {
  return {
    checked_at: new Date().toISOString(),
    counts: { queued: 0, running: 1, done: 5, failed: 0 },
    queued: { count: 0, oldest_age_s: null },
    running: { count: 1, oldest_claimed_age_s: 30, stale_count: 0 },
    visibility_timeout_s: 900,
    verdict: 'ok',
    hint: 'Очередь движется штатно.',
    db_connections: null,
    worker_memory: null,
    worker_restarts: restarts,
    api_rate_limits: rateLimits,
  }
}

async function check() {
  render(<HealthPanel />)
  await userEvent.click(screen.getByRole('button', { name: /Проверить сейчас/i }))
}

describe('Диагностика: перезапуски обработчика', () => {
  beforeAll(() => {
    // Звук уведомлений создаёт AudioContext на первый клик по документу, а в
    // jsdom его нет — без заглушки клик по кнопке проверки ронял бы тест.
    (globalThis as { AudioContext?: unknown }).AudioContext = class {
      state = 'running'
      resume() {}
    }
  })

  beforeEach(() => {
    getApiHealth.mockReset()
    getQueueHealth.mockReset()
    getApiHealth.mockResolvedValue(API_OK)
  })

  it('показывает цифры памяти и число слотов', async () => {
    getQueueHealth.mockResolvedValue(
      queueHealth({
        starts_1h: 1,
        last_age_s: 120,
        slots: 2,
        limit_mb: 2048,
        rss_mb: 780,
        requeued: 0,
      })
    )

    await check()

    const line = await screen.findByTestId('worker-restarts')
    expect(line).toHaveTextContent('1 за час')
    expect(line).toHaveTextContent('слотов 2')
    expect(line).toHaveTextContent('лимит памяти 2048 МБ')
    expect(line).toHaveTextContent('занято 780 МБ')
  })

  it('несколько стартов за час выделены тревожным цветом', async () => {
    getQueueHealth.mockResolvedValue(
      queueHealth({
        starts_1h: 4,
        last_age_s: 60,
        slots: 2,
        limit_mb: 2048,
        rss_mb: 900,
        requeued: 3,
      })
    )

    await check()

    const line = await screen.findByTestId('worker-restarts')
    expect(line).toHaveTextContent('4 за час')
    expect(line).toHaveTextContent('подобрано брошенных задач: 3')
    expect(line).toHaveStyle({ color: 'rgb(180, 83, 9)' })
  })

  it('без событий строки нет — не показываем ноль как факт', async () => {
    getQueueHealth.mockResolvedValue(queueHealth(null))

    await check()

    await waitFor(() => expect(screen.getByText('Очередь движется штатно.')).toBeInTheDocument())
    expect(screen.queryByTestId('worker-restarts')).toBeNull()
  })

  it('нет цифр памяти (платформа без cgroup) — строка всё равно читается', async () => {
    getQueueHealth.mockResolvedValue(
      queueHealth({
        starts_1h: 1,
        last_age_s: 5,
        slots: 4,
        limit_mb: null,
        rss_mb: null,
        requeued: null,
      })
    )

    await check()

    const line = await screen.findByTestId('worker-restarts')
    expect(line).toHaveTextContent('слотов 4')
    expect(line.textContent).not.toContain('лимит памяти')
  })
})

describe('Диагностика: ограничения API (429)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getApiHealth.mockResolvedValue(API_OK)
  })

  it('свежие 429 выделены — это текущая проблема, а не история', async () => {
    getQueueHealth.mockResolvedValue(
      queueHealth(null, {
        hits_1h: 7,
        hits_24h: 21,
        last_age_s: 120,
        max_wait_s_24h: 240,
        via_proxy: true,
      })
    )

    await check()

    const line = await screen.findByTestId('api-rate-limits')
    expect(line).toHaveTextContent('7 за час')
    expect(line).toHaveTextContent('21 за сутки')
    expect(line).toHaveTextContent('дольше всего ждали 240 с')
    expect(line).toHaveTextContent('через посредника')
    expect(line).toHaveStyle({ color: 'rgb(180, 83, 9)' })
  })

  it('вчерашние 429 показаны спокойно — упора в лимит сейчас нет', async () => {
    getQueueHealth.mockResolvedValue(
      queueHealth(null, {
        hits_1h: 0,
        hits_24h: 3,
        last_age_s: 36000,
        max_wait_s_24h: 60,
        via_proxy: false,
      })
    )

    await check()

    const line = await screen.findByTestId('api-rate-limits')
    expect(line).toHaveTextContent('0 за час')
    expect(line).toHaveTextContent('напрямую')
    expect(line).toHaveStyle({ color: 'rgb(100, 116, 139)' })
  })

  it('429 не было вовсе — строки нет', async () => {
    getQueueHealth.mockResolvedValue(queueHealth(null, null))

    await check()

    await waitFor(() => expect(screen.getByText('Очередь движется штатно.')).toBeInTheDocument())
    expect(screen.queryByTestId('api-rate-limits')).toBeNull()
  })
})
