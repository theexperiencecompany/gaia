"use client";

import { Button } from "@heroui/button";
import { ArrowLeft01Icon, Home01Icon } from "@icons";
import React from "react";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";

interface ErrorBoundaryProps {
  children: React.ReactNode;
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

  override componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    // Log error details for debugging or reporting
    console.error("Error caught in Error Boundary:", error, errorInfo);

    // Track error in PostHog. Full diagnostics stay in the console (and
    // Sentry); error.message/stack can carry user content, so analytics only
    // gets the stable error type and component stack.
    trackEvent(ANALYTICS_EVENTS.ERROR_OCCURRED, {
      error_type: "react_error_boundary",
      component_stack: errorInfo.componentStack,
    });
  }

  override render() {
    if (this.state.hasError) {
      return (
        <div className="fixed top-0 left-0 flex h-screen max-h-screen w-screen flex-col items-center justify-center bg-linear-to-b from-primary to-black">
          <h1 className="text-3xl font-bold text-white">
            Something went wrong!
          </h1>
          {this.state.error?.message && (
            <p className="mt-2 text-lg text-zinc-400">
              {this.state.error.message}
            </p>
          )}
          <div className="flex items-center gap-4 pt-5">
            <Button
              variant="solid"
              radius="md"
              className="text-white"
              onPress={() => window.location.replace("/")}
            >
              <Home01Icon width={20} />
              <span>Home</span>
            </Button>
            <Button
              variant="solid"
              radius="md"
              className="font-medium text-black"
              onPress={() => window.history.back()}
            >
              <ArrowLeft01Icon width={20} /> Back
            </Button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
