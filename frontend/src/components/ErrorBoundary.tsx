import { Component, type ErrorInfo, type ReactNode } from 'react';

/** Keeps one broken panel (or a WebGL failure) from blanking the whole app. */
export class ErrorBoundary extends Component<{ children: ReactNode; label: string; resetKey?: unknown }, { error: Error | null; key: unknown }> {
  override state: { error: Error | null; key: unknown } = { error: null, key: undefined };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  static getDerivedStateFromProps(props: { resetKey?: unknown }, state: { error: Error | null; key: unknown }) {
    if (props.resetKey !== state.key) return { error: null, key: props.resetKey };
    return null;
  }

  override componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`[${this.props.label}]`, error, info.componentStack);
  }

  override render() {
    if (this.state.error)
      return (
        <div className="notice err" role="alert" style={{ margin: 12 }}>
          <strong>{this.props.label} failed to render.</strong> {this.state.error.message}{' '}
          <button type="button" className="btn small" onClick={() => this.setState({ error: null })}>
            Retry
          </button>
        </div>
      );
    return this.props.children;
  }
}
