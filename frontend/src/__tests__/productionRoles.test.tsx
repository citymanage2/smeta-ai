/**
 * Роли отдела производства работ в интерфейсе (запрос КП, фаза 1).
 *
 * Снабжение и работа с подрядчиками видят только «Мои задачи КП»: меню без
 * проектов, архива, создания задач и прочего; любой другой экран уводит на
 * /kp. Сервер закрывает то же самое своим запретом — интерфейс не показывает
 * разделов, которые ответили бы 403.
 *
 * План: plans/2026-09-14-zapros-kp.md, фаза 1.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

const pollerSpy = vi.fn()
const notificationsSpy = vi.fn()

vi.mock('../components/ProjectsSidebar', () => ({
  default: () => <nav data-testid="projects-sidebar" />,
}))
vi.mock('../hooks/useGlobalTaskPoller', () => ({
  useGlobalTaskPoller: () => pollerSpy(),
}))
vi.mock('../hooks/useSystemNotifications', () => ({
  useSystemNotifications: () => notificationsSpy(),
}))
// Счётчик новых запросов КП в шапке производства (фаза 5) — без сети.
vi.mock('../hooks/useKpCounters', () => ({
  useKpCounters: () => 0,
  refreshKpCounters: () => undefined,
}))

const listUsers = vi.fn()
vi.mock('../api/adminUsers', async () => {
  const actual = await vi.importActual<typeof import('../api/adminUsers')>('../api/adminUsers')
  return {
    ...actual,
    listUsers: (...a: unknown[]) => listUsers(...a),
    createUser: vi.fn(),
    updateUser: vi.fn(),
    resetPassword: vi.fn(),
  }
})

import Layout from '../components/Layout'
import ProtectedRoute from '../components/ProtectedRoute'
import Employees from '../pages/Employees'
import { useAuthStore } from '../stores/auth'
import { ASSIGNABLE_ROLES, ROLE_LABELS } from '../api/adminUsers'
import {
  PRODUCTION_ROLES,
  isProductionRole,
  landingPathForRole,
} from '../utils/roles'

function loginAs(role: string) {
  useAuthStore.getState().setAuth('token', role, 'user')
}

const SALES_MENU = ['Проекты', 'Архив', 'Создать задачу', 'Калькулятор', 'Выученные цены']

describe('Роли: подписи и признаки', () => {
  it('у каждой назначаемой роли есть подпись', () => {
    for (const role of ASSIGNABLE_ROLES) {
      expect(ROLE_LABELS[role], role).toBeTruthy()
    }
    expect(ROLE_LABELS.supply_manager).toBe('Менеджер снабжения')
    expect(ROLE_LABELS.contractor_manager).toBe('Менеджер по работе с подрядчиками')
  })

  it('обе роли производства назначаются на странице «Сотрудники»', () => {
    for (const role of PRODUCTION_ROLES) {
      expect(ASSIGNABLE_ROLES).toContain(role)
    }
  })

  it('производство — только снабжение и подрядчики', () => {
    expect(isProductionRole('supply_manager')).toBe(true)
    expect(isProductionRole('contractor_manager')).toBe(true)
    for (const role of ['admin', 'head_of_sales', 'project_manager', 'user', null, undefined, '']) {
      expect(isProductionRole(role)).toBe(false)
    }
  })

  it('стартовая страница по роли', () => {
    expect(landingPathForRole('supply_manager')).toBe('/kp')
    expect(landingPathForRole('contractor_manager')).toBe('/kp')
    expect(landingPathForRole('project_manager')).toBe('/system')
    expect(landingPathForRole('admin')).toBe('/system')
  })

  it('стор выставляет isProduction при входе и сбрасывает при выходе', () => {
    loginAs('supply_manager')
    expect(useAuthStore.getState().isProduction).toBe(true)
    expect(useAuthStore.getState().isManager).toBe(false)
    useAuthStore.getState().logout()
    expect(useAuthStore.getState().isProduction).toBe(false)
  })
})

describe('Меню отдела производства', () => {
  beforeEach(() => {
    pollerSpy.mockClear()
    notificationsSpy.mockClear()
  })

  it.each(['supply_manager', 'contractor_manager'])('%s видит только «Мои задачи КП»', (role) => {
    loginAs(role)
    render(
      <MemoryRouter>
        <Layout><div>содержимое</div></Layout>
      </MemoryRouter>,
    )
    expect(screen.getByText('Мои задачи КП')).toBeInTheDocument()
    expect(screen.getByText('Выйти')).toBeInTheDocument()
    for (const label of SALES_MENU) {
      expect(screen.queryByText(label)).not.toBeInTheDocument()
    }
    expect(screen.queryByText('Сотрудники')).not.toBeInTheDocument()
    expect(screen.queryByTestId('projects-sidebar')).not.toBeInTheDocument()
    // Опросы задач и системных событий производству закрыты на сервере.
    expect(pollerSpy).not.toHaveBeenCalled()
    expect(notificationsSpy).not.toHaveBeenCalled()
    expect(screen.getByText(ROLE_LABELS[role])).toBeInTheDocument()
  })

  it('менеджер продаж видит прежнее меню без «Мои задачи КП»', () => {
    loginAs('project_manager')
    render(
      <MemoryRouter>
        <Layout><div>содержимое</div></Layout>
      </MemoryRouter>,
    )
    for (const label of SALES_MENU) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
    expect(screen.queryByText('Мои задачи КП')).not.toBeInTheDocument()
    expect(screen.getByTestId('projects-sidebar')).toBeInTheDocument()
    expect(pollerSpy).toHaveBeenCalled()
    expect(notificationsSpy).toHaveBeenCalled()
  })
})

describe('Маршруты: производству закрыто всё, кроме КП', () => {
  function renderAt(path: string) {
    return render(
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route
            path="/projects"
            element={<ProtectedRoute><div>Проекты-экран</div></ProtectedRoute>}
          />
          <Route
            path="/employees"
            element={<ProtectedRoute requireAdmin><div>Сотрудники-экран</div></ProtectedRoute>}
          />
          <Route
            path="/kp"
            element={<ProtectedRoute allowProduction><div>КП-экран</div></ProtectedRoute>}
          />
        </Routes>
      </MemoryRouter>,
    )
  }

  it('снабженец с экрана проектов уходит на /kp', () => {
    loginAs('supply_manager')
    renderAt('/projects')
    expect(screen.queryByText('Проекты-экран')).not.toBeInTheDocument()
    expect(screen.getByText('КП-экран')).toBeInTheDocument()
  })

  it('подрядчики с админского экрана уходят на /kp', () => {
    loginAs('contractor_manager')
    renderAt('/employees')
    expect(screen.getByText('КП-экран')).toBeInTheDocument()
  })

  it('производство открывает /kp', () => {
    loginAs('contractor_manager')
    renderAt('/kp')
    expect(screen.getByText('КП-экран')).toBeInTheDocument()
  })

  it('менеджер продаж открывает проекты как прежде', () => {
    loginAs('project_manager')
    renderAt('/projects')
    expect(screen.getByText('Проекты-экран')).toBeInTheDocument()
  })
})

describe('Сотрудники: новые роли в форме', () => {
  it('создание сотрудника предлагает роли производства с пояснением', async () => {
    loginAs('admin')
    listUsers.mockResolvedValue([])
    render(
      <MemoryRouter>
        <Employees />
      </MemoryRouter>,
    )
    await waitFor(() => expect(listUsers).toHaveBeenCalled())
    const select = screen.getByDisplayValue('Проектный менеджер') as HTMLSelectElement
    const options = Array.from(select.options).map((o) => o.textContent)
    expect(options).toContain('Менеджер снабжения')
    expect(options).toContain('Менеджер по работе с подрядчиками')
    expect(screen.queryByText(/видит только запросы КП/)).not.toBeInTheDocument()
    await userEvent.selectOptions(select, 'supply_manager')
    expect(screen.getByText(/видит только запросы КП/)).toBeInTheDocument()
  })
})
