"use client";

import { ArrowLeft01Icon, Home01Icon } from "@icons";
import * as Sentry from "@sentry/nextjs";
import React from "react";
import { track } from "@/lib/analytics";

interface ErrorBoundaryProps {
  children: React.ReactNode;
  /** Replaces the full-screen page, for a boundary that guards one item. */
  fallback?: React.ReactNode;
  /** A new value clears the error and retries the render. */
  resetKey?: unknown;
  /** Tags the error report with what this boundary guards. */
  scope?: string;
  onError?: (error: Error) => void;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

class ErrorBoundary extends React.Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    // Update state to display fallback UI
    return { hasError: true, error };
  }

  override componentDidUpdate(prevProps: ErrorBoundaryProps) {
    if (this.state.hasError && prevProps.resetKey !== this.props.resetKey) {
      this.setState({ hasError: false, error: null });
    }
  }

  override componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    const { scope, onError } = this.props;
    console.error("Error caught in Error Boundary:", error, errorInfo);
    onError?.(error);

    // Full diagnostics go to the console and Sentry; error.message/stack can
    // carry user content, so analytics only gets the stable error type.
    Sentry.captureException(error, {
      tags: scope ? { error_boundary: scope } : undefined,
      extra: { componentStack: errorInfo.componentStack },
    });
    track("error:occurred", { error_type: "react_error_boundary" });
  }

  override render() {
    if (this.state.hasError) {
      if (this.props.fallback !== undefined) return this.props.fallback;
      return (
        <div className="fixed top-0 left-0 flex h-screen max-h-screen w-screen flex-col items-center justify-center bg-linear-to-b from-[#00bbff] to-black">
          <h1 className="text-3xl font-bold text-white">
            Something went wrong!
          </h1>
          {this.state.error?.message && (
            <p className="mt-2 text-lg text-gray-400">
              {this.state.error.message}
            </p>
          )}
          <div className="flex items-center gap-4 pt-5">
            <button
              type="button"
              className="flex gap-2 rounded-lg bg-black p-2 px-3 text-white transition-background hover:bg-[#00000086]"
              onClick={() => window.location.replace("/")}
            >
              <Home01Icon width={20} />
              <span>Home</span>
            </button>
            <button
              type="button"
              className="flex gap-2 rounded-lg bg-white p-2 px-3 font-medium text-black transition-background hover:bg-[#ffffff86]"
              onClick={() => window.history.back()}
            >
              <ArrowLeft01Icon width={20} /> Back
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
