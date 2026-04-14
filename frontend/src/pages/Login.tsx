import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { login } from '../api/auth';

const Login: React.FC = () => {
  const navigate = useNavigate();
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!password.trim()) {
      setError('Введите пароль');
      return;
    }
    setLoading(true);
    setError('');

    try {
      const result = await login(password);
      if (result.role === 'admin') {
        navigate('/admin');
      } else {
        navigate('/task/create');
      }
    } catch (err: unknown) {
      const axiosError = err as { response?: { data?: { detail?: string }; status?: number }; request?: unknown };
      if (axiosError.response?.status === 401) {
        setError('Неверный пароль. Попробуйте ещё раз.');
      } else if (axiosError.request && !axiosError.response) {
        setError('Нет соединения с сервером. Проверьте интернет и попробуйте ещё раз.');
      } else {
        setError('Ошибка сервера. Попробуйте позже.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        backgroundColor: '#f8fafc',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '24px',
      }}
    >
      <div
        style={{
          width: '100%',
          maxWidth: '400px',
          backgroundColor: '#ffffff',
          borderRadius: '16px',
          boxShadow: '0 4px 24px rgba(0,0,0,0.08)',
          padding: '40px',
        }}
      >
        {/* Logo */}
        <div style={{ textAlign: 'center', marginBottom: '32px' }}>
          <h1
            style={{
              fontSize: '32px',
              fontWeight: 800,
              color: '#2563eb',
              margin: 0,
              letterSpacing: '-1px',
            }}
          >
            Smeta AI
          </h1>
          <p style={{ margin: '8px 0 0', color: '#64748b', fontSize: '15px' }}>
            Автоматизация строительных смет
          </p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} noValidate>
          <div style={{ marginBottom: '20px' }}>
            <label
              htmlFor="password"
              style={{
                display: 'block',
                fontSize: '14px',
                fontWeight: 600,
                color: '#374151',
                marginBottom: '8px',
              }}
            >
              Пароль доступа
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Введите пароль"
              autoFocus
              style={{
                width: '100%',
                padding: '11px 14px',
                fontSize: '15px',
                border: `1.5px solid ${error ? '#fca5a5' : '#e2e8f0'}`,
                borderRadius: '8px',
                outline: 'none',
                color: '#1e293b',
                backgroundColor: '#ffffff',
                boxSizing: 'border-box',
                transition: 'border-color 0.15s',
              }}
              onFocus={(e) => { if (!error) e.target.style.borderColor = '#2563eb'; }}
              onBlur={(e) => { if (!error) e.target.style.borderColor = '#e2e8f0'; }}
            />
          </div>

          {/* Error message */}
          {error && (
            <div
              style={{
                padding: '10px 14px',
                backgroundColor: '#fef2f2',
                border: '1px solid #fecaca',
                borderRadius: '8px',
                marginBottom: '20px',
                fontSize: '14px',
                color: '#dc2626',
              }}
            >
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            style={{
              width: '100%',
              padding: '12px',
              fontSize: '16px',
              fontWeight: 600,
              backgroundColor: loading ? '#93c5fd' : '#2563eb',
              color: '#ffffff',
              border: 'none',
              borderRadius: '8px',
              cursor: loading ? 'not-allowed' : 'pointer',
              transition: 'background-color 0.15s',
            }}
          >
            {loading ? 'Вход...' : 'Войти'}
          </button>
        </form>
      </div>
    </div>
  );
};

export default Login;
