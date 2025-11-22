"use client";

import React from "react";

import { ArrowLeft01Icon, Home01Icon } from '@/icons';

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

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    // Log error details for debugging or reporting
    console.error("Error caught in Error Boundary:", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
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
              className="flex gap-2 rounded-lg bg-black p-2 px-3 text-white transition-background hover:bg-[#00000086]"
              onClick={() => (window.location.href = "/")}
            >
              <Home01Icon width={20} />
              <span>Home</span>
            </button>
            <button
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
