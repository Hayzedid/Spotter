import React, { Component } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'

class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, info) {
    console.error('Spotter UI error caught by ErrorBoundary:', error, info)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          padding: '40px',
          fontFamily: 'system-ui, sans-serif',
          background: '#071e24',
          color: '#f8fafc',
          minHeight: '100vh',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          alignItems: 'center',
        }}>
          <div style={{
            maxWidth: '680px',
            background: '#0b2a30',
            border: '1px solid #dc2626',
            borderRadius: '8px',
            padding: '24px',
          }}>
            <h2 style={{ color: '#ef4444', marginBottom: '12px', fontSize: '1.2rem' }}>
              Application Error
            </h2>
            <p style={{ color: '#93b4b6', fontSize: '0.9rem', marginBottom: '16px' }}>
              An error occurred while rendering the map or components:
            </p>
            <pre style={{
              background: '#051519',
              padding: '12px',
              borderRadius: '4px',
              color: '#fca5a5',
              fontSize: '0.8rem',
              overflowX: 'auto',
              whiteSpace: 'pre-wrap',
            }}>
              {this.state.error?.stack || this.state.error?.message || String(this.state.error)}
            </pre>
            <button
              onClick={() => window.location.reload()}
              style={{
                marginTop: '16px',
                padding: '8px 16px',
                background: '#0d9488',
                color: '#fff',
                border: 'none',
                borderRadius: '4px',
                cursor: 'pointer',
              }}
            >
              Reload Page
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

createRoot(document.getElementById('root')).render(
  <ErrorBoundary>
    <App />
  </ErrorBoundary>,
)
