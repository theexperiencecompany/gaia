import { Alert01Icon } from "@icons";
import React from "react";

/** The raw-code fallback every OpenUI surface shows when a program fails to render. */
export function OpenUIErrorCard({
  code,
  error,
}: {
  code: string;
  error?: string;
}) {
  return (
    <div className="rounded-2xl bg-zinc-800 p-4 w-full max-w-lg">
      <div className="flex items-center gap-2 mb-2">
        <Alert01Icon className="h-4 w-4 text-red-400 shrink-0" />
        <p className="text-sm font-medium text-red-400">
          Component failed to render
        </p>
      </div>
      {error && <p className="text-xs text-zinc-500 mb-2">{error}</p>}
      <pre className="rounded-xl bg-zinc-900 p-3 text-xs text-zinc-400 overflow-x-auto whitespace-pre-wrap break-all">
        {code}
      </pre>
    </div>
  );
}

/** Catches a render error in an OpenUI tree and shows its source instead; resets when the code changes. */
export class OpenUIErrorBoundary extends React.Component<
  { children: React.ReactNode; code: string },
  { hasError: boolean; errorMessage: string }
> {
  constructor(props: { children: React.ReactNode; code: string }) {
    super(props);
    this.state = { hasError: false, errorMessage: "" };
  }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, errorMessage: error.message };
  }

  override componentDidUpdate(prevProps: { code: string }) {
    if (this.state.hasError && prevProps.code !== this.props.code) {
      this.setState({ hasError: false, errorMessage: "" });
    }
  }

  override componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("[OpenUI] Render error:", error, info, {
      code: this.props.code,
    });
  }

  override render() {
    if (this.state.hasError) {
      return (
        <OpenUIErrorCard
          code={this.props.code}
          error={this.state.errorMessage}
        />
      );
    }
    return this.props.children;
  }
}
