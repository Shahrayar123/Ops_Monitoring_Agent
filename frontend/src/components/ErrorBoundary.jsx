import { Component } from 'react'
import { Button } from './ui'

// Catches render-time crashes so one broken screen doesn't blank the whole app.
export class ErrorBoundary extends Component {
  state = { error: null }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    console.error('UI crash:', error, info)
  }

  render() {
    if (this.state.error) {
      return (
        <div className="grid min-h-[60vh] place-items-center p-6">
          <div className="card max-w-md p-8 text-center">
            <div className="mb-3 text-4xl">🧩</div>
            <h2 className="mb-2 text-lg font-bold" style={{ color: 'var(--ink)' }}>
              Something broke on this screen
            </h2>
            <p className="mb-5 text-sm" style={{ color: 'var(--muted)' }}>
              The rest of the app is fine. Try reloading this view.
            </p>
            <Button onClick={() => this.setState({ error: null })}>Try again</Button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
