import { Component, ReactNode } from "react";

interface Props {
  /** Optional custom fallback. If absent, a minimal generic UI is rendered. */
  fallback?: (error: Error, retry: () => void) => ReactNode;
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Per-page error boundary. WHY: a thrown render in one route shouldn't
 * blank the whole shell — operators need at least the nav and language
 * switcher to escape. React's `componentDidCatch` is still the only way
 * to do this in 2026.
 *
 * SAFETY: not a replacement for handled errors in API mutations — those
 * still go through React Query's `error` state. This catches *unhandled
 * render-time exceptions* in component subtrees.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error): void {
    // WHY: console is the dev visibility. Sprint-12+ may pipe these to a
    // backend log endpoint, but the in-process panel doesn't yet have one.
    // eslint-disable-next-line no-console
    console.error("[ErrorBoundary]", error);
  }

  retry = () => this.setState({ error: null });

  render() {
    if (this.state.error) {
      if (this.props.fallback) return this.props.fallback(this.state.error, this.retry);
      return (
        <div className="page" role="alert">
          <h1>Something went wrong</h1>
          <p style={{ color: "var(--muted-foreground)" }}>
            {this.state.error.message || "Unknown render error"}
          </p>
          <button
            type="button"
            onClick={this.retry}
            style={{
              padding: "0.5rem 1rem",
              background: "var(--foreground)",
              color: "var(--background)",
              border: "1px solid var(--foreground)",
              cursor: "pointer",
              fontFamily: "var(--font-mono)",
            }}
          >
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
