import React, { useState, useEffect, useCallback } from 'react';
import Layout from '../components/Layout';
import { SectionLoader } from '../components/ui/LumaSpin';
import { formatApiDetail } from '../utils/formatError';
import {
  AdminUser, AssignableRole,
  listUsers, createUser, updateUser, resetPassword,
  ROLE_LABELS, ASSIGNABLE_ROLES,
} from '../api/adminUsers';

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

const selectStyle: React.CSSProperties = {
  padding: '6px 10px',
  fontSize: '13px',
  border: '1.5px solid #e2e8f0',
  borderRadius: '7px',
  outline: 'none',
  color: '#1e293b',
  backgroundColor: '#ffffff',
  cursor: 'pointer',
};

const inputStyle: React.CSSProperties = {
  width: '100%',
  padding: '10px 12px',
  fontSize: '14px',
  border: '1.5px solid #e2e8f0',
  borderRadius: '8px',
  outline: 'none',
  color: '#1e293b',
  backgroundColor: '#ffffff',
  boxSizing: 'border-box',
};

const thStyle: React.CSSProperties = {
  padding: '12px 16px',
  textAlign: 'left',
  fontSize: '12px',
  fontWeight: 700,
  color: '#64748b',
  textTransform: 'uppercase',
  letterSpacing: '0.5px',
  whiteSpace: 'nowrap',
};

interface ResetState {
  user: AdminUser;
  password: string;
  loading: boolean;
  error: string;
}

const EmployeesPage: React.FC = () => {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // Форма создания
  const [newUsername, setNewUsername] = useState('');
  const [newFullName, setNewFullName] = useState('');
  const [newRole, setNewRole] = useState<AssignableRole>('project_manager');
  const [newPassword, setNewPassword] = useState('');
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState('');
  const [createSuccess, setCreateSuccess] = useState('');

  // Действия по строке
  const [rowBusy, setRowBusy] = useState<number | null>(null);
  const [resetState, setResetState] = useState<ResetState | null>(null);

  const fetchUsers = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await listUsers();
      setUsers(data);
    } catch {
      setError('Не удалось загрузить список сотрудников.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchUsers(); }, [fetchUsers]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newUsername.trim() || !newPassword.trim()) {
      setCreateError('Заполните логин и пароль.');
      return;
    }
    setCreating(true);
    setCreateError('');
    setCreateSuccess('');
    try {
      await createUser({
        username: newUsername.trim(),
        password: newPassword,
        role: newRole,
        full_name: newFullName.trim() || undefined,
      });
      setCreateSuccess(`Сотрудник «${newUsername.trim()}» создан.`);
      setNewUsername('');
      setNewFullName('');
      setNewRole('project_manager');
      setNewPassword('');
      await fetchUsers();
    } catch (err: unknown) {
      const e2 = err as { response?: { status?: number; data?: { detail?: string } } };
      if (e2.response?.status === 409) {
        setCreateError('Логин уже занят. Выберите другой.');
      } else {
        setCreateError(formatApiDetail(e2.response?.data?.detail, 'Не удалось создать сотрудника.'));
      }
    } finally {
      setCreating(false);
    }
  };

  const handleRoleChange = async (user: AdminUser, role: string) => {
    if (role === user.role) return;
    setRowBusy(user.id);
    setError('');
    try {
      const { user: updated } = await updateUser(user.id, { role });
      setUsers((prev) => prev.map((u) => (u.id === user.id ? updated : u)));
    } catch (err: unknown) {
      const e2 = err as { response?: { status?: number; data?: { detail?: string } } };
      if (e2.response?.status === 400) {
        setError(formatApiDetail(e2.response?.data?.detail, 'Нельзя снять роль последнего администратора.'));
      } else {
        setError('Не удалось изменить роль.');
      }
    } finally {
      setRowBusy(null);
    }
  };

  const handleToggleActive = async (user: AdminUser) => {
    setRowBusy(user.id);
    setError('');
    try {
      const { user: updated } = await updateUser(user.id, { is_active: !user.is_active });
      setUsers((prev) => prev.map((u) => (u.id === user.id ? updated : u)));
    } catch (err: unknown) {
      const e2 = err as { response?: { status?: number; data?: { detail?: string } } };
      if (e2.response?.status === 400) {
        setError(formatApiDetail(e2.response?.data?.detail, 'Нельзя деактивировать последнего администратора.'));
      } else {
        setError('Не удалось изменить статус.');
      }
    } finally {
      setRowBusy(null);
    }
  };

  const handleResetSubmit = async () => {
    if (!resetState) return;
    if (!resetState.password.trim()) {
      setResetState({ ...resetState, error: 'Введите новый пароль.' });
      return;
    }
    setResetState({ ...resetState, loading: true, error: '' });
    try {
      await resetPassword(resetState.user.id, resetState.password);
      setResetState(null);
    } catch (err: unknown) {
      const e2 = err as { response?: { data?: { detail?: string } } };
      setResetState((prev) => prev && {
        ...prev,
        loading: false,
        error: formatApiDetail(e2.response?.data?.detail, 'Не удалось сбросить пароль.'),
      });
    }
  };

  return (
    <Layout>
      <div>
        {/* Заголовок */}
        <div style={{ marginBottom: '24px' }}>
          <h2 style={{ margin: 0, fontSize: '26px', fontWeight: 700, color: '#0f172a' }}>
            Сотрудники
          </h2>
          <p style={{ margin: '6px 0 0', fontSize: '14px', color: '#64748b' }}>
            Управление персональными аккаунтами и правами доступа.
          </p>
        </div>

        {/* Форма создания */}
        <form
          onSubmit={handleCreate}
          style={{
            backgroundColor: '#ffffff',
            border: '1px solid #e2e8f0',
            borderRadius: '12px',
            padding: '24px',
            marginBottom: '28px',
            maxWidth: '900px',
          }}
        >
          <h3 style={{ margin: '0 0 16px', fontSize: '17px', fontWeight: 700, color: '#0f172a' }}>
            Новый сотрудник
          </h3>
          <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
            <div style={{ flex: '1 1 180px', minWidth: '160px' }}>
              <div style={{ fontSize: '12px', fontWeight: 600, color: '#94a3b8', marginBottom: '5px' }}>Логин *</div>
              <input
                type="text"
                value={newUsername}
                onChange={(e) => setNewUsername(e.target.value)}
                placeholder="Логин"
                autoComplete="off"
                style={inputStyle}
              />
            </div>
            <div style={{ flex: '1 1 200px', minWidth: '160px' }}>
              <div style={{ fontSize: '12px', fontWeight: 600, color: '#94a3b8', marginBottom: '5px' }}>ФИО</div>
              <input
                type="text"
                value={newFullName}
                onChange={(e) => setNewFullName(e.target.value)}
                placeholder="Иванов Иван"
                autoComplete="off"
                style={inputStyle}
              />
            </div>
            <div style={{ flex: '1 1 200px', minWidth: '180px' }}>
              <div style={{ fontSize: '12px', fontWeight: 600, color: '#94a3b8', marginBottom: '5px' }}>Роль *</div>
              <select
                value={newRole}
                onChange={(e) => setNewRole(e.target.value as AssignableRole)}
                style={{ ...inputStyle, cursor: 'pointer' }}
              >
                {ASSIGNABLE_ROLES.map((r) => (
                  <option key={r} value={r}>{ROLE_LABELS[r]}</option>
                ))}
              </select>
            </div>
            <div style={{ flex: '1 1 180px', minWidth: '160px' }}>
              <div style={{ fontSize: '12px', fontWeight: 600, color: '#94a3b8', marginBottom: '5px' }}>Пароль *</div>
              <input
                type="text"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="Пароль"
                autoComplete="new-password"
                style={inputStyle}
              />
            </div>
          </div>

          {createError && (
            <div style={{ marginTop: '14px', padding: '10px 14px', backgroundColor: '#fef2f2', border: '1px solid #fecaca', borderRadius: '8px', fontSize: '14px', color: '#dc2626' }}>
              {createError}
            </div>
          )}
          {createSuccess && (
            <div style={{ marginTop: '14px', padding: '10px 14px', backgroundColor: '#f0fdf4', border: '1px solid #86efac', borderRadius: '8px', fontSize: '14px', color: '#15803d' }}>
              {createSuccess}
            </div>
          )}

          <div style={{ marginTop: '16px' }}>
            <button
              type="submit"
              disabled={creating}
              style={{
                padding: '10px 22px',
                fontSize: '14px',
                fontWeight: 600,
                backgroundColor: creating ? '#93c5fd' : '#2563eb',
                color: '#ffffff',
                border: 'none',
                borderRadius: '8px',
                cursor: creating ? 'not-allowed' : 'pointer',
              }}
            >
              {creating ? 'Создание...' : 'Создать сотрудника'}
            </button>
          </div>
        </form>

        {/* Ошибка списка */}
        {error && (
          <div style={{ padding: '10px 14px', backgroundColor: '#fef2f2', border: '1px solid #fecaca', borderRadius: '8px', marginBottom: '14px', fontSize: '14px', color: '#dc2626' }}>
            {error}
          </div>
        )}

        {/* Таблица */}
        <div style={{ backgroundColor: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '10px', overflowX: 'auto' }}>
          {loading ? (
            <SectionLoader />
          ) : users.length === 0 ? (
            <div style={{ padding: '48px', textAlign: 'center', color: '#94a3b8' }}>Сотрудники не найдены</div>
          ) : (
            <table style={{ width: '100%', minWidth: '760px', borderCollapse: 'collapse', fontSize: '14px' }}>
              <thead>
                <tr style={{ backgroundColor: '#f8fafc', borderBottom: '2px solid #e2e8f0' }}>
                  {['Логин', 'ФИО', 'Роль', 'Статус', 'Создан', 'Действия'].map((col) => (
                    <th key={col} style={thStyle}>{col}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {users.map((u) => {
                  const busy = rowBusy === u.id;
                  return (
                    <tr
                      key={u.id}
                      style={{
                        borderBottom: '1px solid #e2e8f0',
                        backgroundColor: u.is_active ? '#ffffff' : '#f8fafc',
                        opacity: u.is_active ? 1 : 0.7,
                      }}
                    >
                      <td style={{ padding: '12px 16px', fontWeight: 600, color: '#1e293b' }}>{u.username}</td>
                      <td style={{ padding: '12px 16px', color: '#475569' }}>{u.full_name || '—'}</td>
                      <td style={{ padding: '12px 16px' }}>
                        <select
                          value={ASSIGNABLE_ROLES.includes(u.role as AssignableRole) ? u.role : u.role}
                          onChange={(e) => handleRoleChange(u, e.target.value)}
                          disabled={busy}
                          style={{ ...selectStyle, cursor: busy ? 'not-allowed' : 'pointer' }}
                        >
                          {/* legacy-роль (например 'user') показываем как есть, но выбрать можно только назначаемые */}
                          {!ASSIGNABLE_ROLES.includes(u.role as AssignableRole) && (
                            <option value={u.role}>{ROLE_LABELS[u.role] ?? u.role}</option>
                          )}
                          {ASSIGNABLE_ROLES.map((r) => (
                            <option key={r} value={r}>{ROLE_LABELS[r]}</option>
                          ))}
                        </select>
                      </td>
                      <td style={{ padding: '12px 16px' }}>
                        <span style={{
                          display: 'inline-block',
                          padding: '3px 10px',
                          backgroundColor: u.is_active ? '#f0fdf4' : '#f1f5f9',
                          color: u.is_active ? '#15803d' : '#64748b',
                          border: `1px solid ${u.is_active ? '#86efac' : '#cbd5e1'}`,
                          borderRadius: '12px',
                          fontSize: '12px',
                          fontWeight: 600,
                        }}>
                          {u.is_active ? 'Активен' : 'Отключён'}
                        </span>
                      </td>
                      <td style={{ padding: '12px 16px', color: '#475569', whiteSpace: 'nowrap' }}>
                        {formatDate(u.created_at)}
                      </td>
                      <td style={{ padding: '12px 16px', whiteSpace: 'nowrap' }}>
                        <div style={{ display: 'flex', gap: '8px' }}>
                          <button
                            onClick={() => handleToggleActive(u)}
                            disabled={busy}
                            style={{
                              padding: '5px 12px',
                              backgroundColor: u.is_active ? '#fef3c7' : '#dcfce7',
                              color: u.is_active ? '#b45309' : '#15803d',
                              border: 'none',
                              borderRadius: '6px',
                              cursor: busy ? 'not-allowed' : 'pointer',
                              fontSize: '13px',
                              fontWeight: 600,
                            }}
                          >
                            {u.is_active ? 'Деактивировать' : 'Активировать'}
                          </button>
                          <button
                            onClick={() => setResetState({ user: u, password: '', loading: false, error: '' })}
                            disabled={busy}
                            style={{
                              padding: '5px 12px',
                              backgroundColor: '#eff6ff',
                              color: '#1d4ed8',
                              border: 'none',
                              borderRadius: '6px',
                              cursor: busy ? 'not-allowed' : 'pointer',
                              fontSize: '13px',
                              fontWeight: 600,
                            }}
                          >
                            Сбросить пароль
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Модалка сброса пароля */}
      {resetState && (
        <div
          style={{ position: 'fixed', inset: 0, backgroundColor: 'rgba(0,0,0,0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}
          onClick={() => !resetState.loading && setResetState(null)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{ backgroundColor: '#ffffff', borderRadius: '12px', padding: '28px 32px', boxShadow: '0 8px 32px rgba(0,0,0,0.15)', maxWidth: '420px', width: '90%' }}
          >
            <h3 style={{ margin: '0 0 12px', fontSize: '18px', fontWeight: 700, color: '#0f172a' }}>
              Сброс пароля
            </h3>
            <p style={{ margin: '0 0 16px', fontSize: '14px', color: '#64748b' }}>
              Новый пароль для сотрудника <strong>«{resetState.user.username}»</strong>.
            </p>
            <input
              type="text"
              value={resetState.password}
              onChange={(e) => setResetState({ ...resetState, password: e.target.value })}
              placeholder="Новый пароль"
              autoComplete="new-password"
              autoFocus
              style={{ ...inputStyle, marginBottom: '12px' }}
            />
            {resetState.error && (
              <div style={{ padding: '9px 12px', backgroundColor: '#fef2f2', border: '1px solid #fecaca', borderRadius: '7px', marginBottom: '12px', fontSize: '13px', color: '#dc2626' }}>
                {resetState.error}
              </div>
            )}
            <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end' }}>
              <button
                onClick={() => setResetState(null)}
                disabled={resetState.loading}
                style={{ padding: '9px 20px', backgroundColor: '#f1f5f9', color: '#475569', border: 'none', borderRadius: '8px', cursor: 'pointer', fontSize: '14px', fontWeight: 600 }}
              >
                Отмена
              </button>
              <button
                onClick={handleResetSubmit}
                disabled={resetState.loading}
                style={{ padding: '9px 20px', backgroundColor: resetState.loading ? '#93c5fd' : '#2563eb', color: '#ffffff', border: 'none', borderRadius: '8px', cursor: resetState.loading ? 'not-allowed' : 'pointer', fontSize: '14px', fontWeight: 600 }}
              >
                {resetState.loading ? 'Сохранение...' : 'Сбросить пароль'}
              </button>
            </div>
          </div>
        </div>
      )}
    </Layout>
  );
};

export default EmployeesPage;
