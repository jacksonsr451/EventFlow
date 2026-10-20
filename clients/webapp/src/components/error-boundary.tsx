import { Component, type ErrorInfo, type ReactNode } from "react";
import { ErrorState } from "@eventflow/ui";

interface ErrorBoundaryState {
  error: Error | null;
}

export class AppErrorBoundary extends Component<
  { children: ReactNode },
  ErrorBoundaryState
> {
  override state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("Unhandled application error", error, info.componentStack);
  }

  override render() {
    if (this.state.error) {
      return (
        <main className="flex min-h-dvh items-center justify-center bg-background px-4">
          <div className="w-full max-w-lg">
            <ErrorState
              title="The application encountered an error"
              description="Reload the page to recover. If the problem continues, contact your workspace administrator."
              action={
                <button
                  type="button"
                  className="inline-flex h-10 items-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground"
                  onClick={() => window.location.reload()}
                >
                  Reload EventFlow
                </button>
              }
            />
          </div>
        </main>
      );
    }
    return this.props.children;
  }
}
