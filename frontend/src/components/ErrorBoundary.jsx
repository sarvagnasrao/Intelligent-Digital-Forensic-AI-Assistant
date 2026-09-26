import React from 'react'

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
    }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, errorInfo) {
    console.error('[IDF-AI] Component error:', error)
    this.setState({ errorInfo })
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: 300,
          padding: 40,
          textAlign: 'center',
        }}>
          <div style={{
            width: 56,
            height: 56,
            borderRadius: 16,
            background: 'rgba(239,68,68,0.1)',
            border: '1px solid rgba(239,68,68,0.2)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 24,
            marginBottom: 16,
          }}>
            ⚠
          </div>

          <h2 style={{
            fontSize: 16,
            fontWeight: 600,
            color: 'var(--text-primary)',
            marginBottom: 8,
          }}>
            Something went wrong
          </h2>

          <p style={{
            fontSize: 13,
            color: 'var(--color-white-3)',
            marginBottom: 20,
            maxWidth: 360,
          }}>
            {this.state.error?.message || 'An unexpected error occurred'}
          </p>

          <button
            onClick={() => {
              this.setState({ hasError: false, error: null })
              window.location.reload()
            }}
            style={{
              padding: '8px 20px',
              borderRadius: 8,
              background: 'rgba(99,102,241,0.15)',
              border: '1px solid rgba(99,102,241,0.3)',
              color: '#a5b4fc',
              fontSize: 13,
              cursor: 'pointer',
            }}
          >
            Reload page
          </button>

          {process.env.NODE_ENV === 'development' && (
            <details style={{
              marginTop: 20,
              fontSize: 11,
              color: 'var(--color-white-2)',
              textAlign: 'left',
              maxWidth: 500,
            }}>
              <summary style={{ cursor: 'pointer', marginBottom: 8 }}>
                Error details
              </summary>
              <pre style={{
                overflow: 'auto',
                padding: 12,
                background: 'rgba(0,0,0,0.3)',
                borderRadius: 6,
                fontSize: 10,
                lineHeight: 1.5,
              }}>
                {this.state.error?.stack}
              </pre>
            </details>
          )}
        </div>
      )
    }

    return this.props.children
  }
}
