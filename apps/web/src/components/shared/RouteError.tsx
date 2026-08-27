"use client";

import { Button } from "@heroui/button";
import { Spinner } from "@heroui/spinner";
import { Home01Icon } from "@icons";
import { useEffect, useState } from "react";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import {
  isChunkLoadError,
  recoverFromChunkError,
} from "@/lib/chunkErrorRecovery";

interface RouteErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

/**
 * App Router segment error boundary. Rendered by `error.tsx` files so a render
 * error is contained to its route group (keeping the shell/nav alive) instead
 * of bubbling to `global-error.tsx` and replacing the whole document.
 */
export default function RouteError({ error, reset }: RouteErrorProps) {
  const isChunk = isChunkLoadError(error);

  // Errors whose recovery attempt already concluded without a reload. Keyed by
  // the error itself — a brand-new error derives its own pending state during
  // render instead of syncing stale state over from a prop change.
  const [failedRecoveryErrors, setFailedRecoveryErrors] = useState<
    Set<unknown>
  >(() => new Set());

  useEffect(() => {
    // A stale-asset chunk failure reached the boundary. Reload once to fetch
    // fresh chunks; if recovery is exhausted, fall through to the retryable UI.
    // `recoverFromChunkError` emits its own analytics for both paths.
    if (isChunk) {
      if (recoverFromChunkError(error) !== "reloading") {
        setFailedRecoveryErrors((prev) => new Set(prev).add(error));
      }
      return;
    }

    // Full diagnostics stay in the console (and Sentry). Only the stable,
    // non-sensitive digest is sent to analytics — error.message/stack can carry
    // backend responses, URLs, query params, or user content.
    console.error("Route error boundary caught:", error);
    trackEvent(ANALYTICS_EVENTS.ROUTE_ERROR_SHOWN, {
      error_type: "app_router_error_boundary",
      error_digest: error.digest,
    });
  }, [error, isChunk]);

  // While the guarded reload decision is pending for a chunk error, show a
  // neutral loader rather than flashing the error UI for what is about to
  // become a fresh page.
  if (isChunk && !failedRecoveryErrors.has(error)) {
    return (
      <div className="flex min-h-[60vh] w-full items-center justify-center p-6">
        <Spinner color="primary" />
      </div>
    );
  }

  return (
    <div className="flex min-h-[60vh] w-full flex-col items-center justify-center gap-2 p-6 text-center">
      <h1 className="text-2xl font-bold text-white">Something went wrong</h1>
      <p className="max-w-md text-zinc-400">
        An unexpected error occurred. Please try again or return home.
      </p>
      <div className="flex items-center gap-3 pt-4">
        <Button color="primary" onPress={reset}>
          Try again
        </Button>
        <Button
          variant="flat"
          startContent={<Home01Icon width={18} />}
          onPress={() => window.location.assign("/")}
        >
          Home
        </Button>
      </div>
    </div>
  );
}
