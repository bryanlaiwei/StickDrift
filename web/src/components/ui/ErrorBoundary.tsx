import { Component, type ReactNode } from 'react'

/** Shows what went wrong instead of an empty page when a view throws while rendering. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <main className="wrap page-pad">
        <section className="panel">
          <h2>This page could not be shown</h2>
          <p className="muted">
            Something in the data did not match what the page expected. If the site was just updated, restart the
            backend so it matches, then reload.
          </p>
          <p className="error" role="alert">
            {this.state.error.message}
          </p>
          <p>
            <button className="btn btn-secondary btn-small" onClick={() => window.location.reload()}>
              Reload
            </button>
          </p>
        </section>
      </main>
    )
  }
}
