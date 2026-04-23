import React from 'react';

interface Props {
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

interface State {
  error: Error | null;
}

class ErrorBoundary extends React.Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('[ErrorBoundary]', error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div style={{
          padding: '24px', margin: '24px',
          background: '#fef2f2', border: '1px solid #fecaca',
          borderRadius: '10px', color: '#dc2626',
        }}>
          <strong>Ошибка рендеринга</strong>
          <pre style={{ marginTop: 8, fontSize: 12, whiteSpace: 'pre-wrap', color: '#7f1d1d' }}>
            {this.state.error.message}
            {'\n\n'}
            {this.state.error.stack}
          </pre>
          <button
            onClick={() => this.setState({ error: null })}
            style={{
              marginTop: 12, padding: '8px 16px',
              background: '#dc2626', color: '#fff',
              border: 'none', borderRadius: 6, cursor: 'pointer',
            }}
          >
            Попробовать снова
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
