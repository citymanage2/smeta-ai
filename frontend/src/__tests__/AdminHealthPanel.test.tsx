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
import { numbersIn } from './screenQueries'

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

  // Строка перезапусков — единственное место, где видно, что обработчик умирает
  // и поднимается заново. Проверяются числа, а не фразы: формулировки меняются,
  // а потерять цифру (или напечатать «null» без cgroup) нельзя. Возраст старта
  // (5 с) выбран так, чтобы не совпасть ни с одним проверяемым числом — иначе
  // пропавшее число нашлось бы в нём.
  it.each([
    {
      name: 'память, слоты, перезапуски за час',
      restarts: { starts_1h: 1, last_age_s: 5, slots: 2, limit_mb: 2048, rss_mb: 780, requeued: 0 },
      numbers: [1, 2, 2048, 780],
    },
    {
      name: 'нет цифр памяти (платформа без cgroup)',
      restarts: { starts_1h: 1, last_age_s: 5, slots: 4, limit_mb: null, rss_mb: null, requeued: null },
      numbers: [1, 4],
    },
    {
      // Оставлено из «несколько стартов за час…» (план чистки тестов): других
      // проверок числа подобранных брошенных задач нет.
      name: 'подобраны брошенные задачи',
      restarts: { starts_1h: 4, last_age_s: 5, slots: 2, limit_mb: 2048, rss_mb: 900, requeued: 3 },
      numbers: [4, 2, 2048, 900, 3],
    },
  ])('$name — все числа видны, пустых нет', async ({ restarts, numbers }) => {
    getQueueHealth.mockResolvedValue(queueHealth(restarts))

    await check()

    const line = await screen.findByTestId('worker-restarts')
    expect(numbersIn(line.textContent)).toEqual(expect.arrayContaining(numbers))
    expect(line.textContent).not.toMatch(/null|undefined|NaN/)
  })

  it('без событий строки нет — не показываем ноль как факт', async () => {
    getQueueHealth.mockResolvedValue(queueHealth(null))

    await check()

    await waitFor(() => expect(screen.getByText('Очередь движется штатно.')).toBeInTheDocument())
    expect(screen.queryByTestId('worker-restarts')).toBeNull()
  })
})

describe('Диагностика: ограничения API (429)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getApiHealth.mockResolvedValue(API_OK)
  })

  it.each([
    { via_proxy: true, proxy: true },
    { via_proxy: false, proxy: false },
  ])('числа 429 видны; через посредника — $proxy', async ({ via_proxy, proxy }) => {
    getQueueHealth.mockResolvedValue(
      queueHealth(null, {
        hits_1h: 7,
        hits_24h: 21,
        last_age_s: 5,
        max_wait_s_24h: 240,
        via_proxy,
      })
    )

    await check()

    const line = await screen.findByTestId('api-rate-limits')
    expect(numbersIn(line.textContent)).toEqual(expect.arrayContaining([7, 21, 240]))
    if (proxy) expect(line).toHaveTextContent(/посредник/)
    else expect(line).not.toHaveTextContent(/посредник/)
  })

  it('429 не было вовсе — строки нет', async () => {
    getQueueHealth.mockResolvedValue(queueHealth(null, null))

    await check()

    await waitFor(() => expect(screen.getByText('Очередь движется штатно.')).toBeInTheDocument())
    expect(screen.queryByTestId('api-rate-limits')).toBeNull()
  })
})
