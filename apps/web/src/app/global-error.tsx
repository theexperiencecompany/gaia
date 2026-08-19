"use client";

// This file is the Next.js global error boundary for the App Router.
// Placing it in the `app/` directory automatically applies it to the entire
// application, so you don't need to manually wrap your pages or layouts.

import * as Sentry from "@sentry/nextjs";
import NextError from "next/error";
import posthog from "posthog-js";
import { useEffect, useMemo } from "react";

import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import {
  isChunkLoadError,
  recoverFromChunkError,
} from "@/lib/chunkErrorRecovery";

export default function GlobalError({
  error,
}: {
  error: Error & { digest?: string };
}) {
  const isChunk = isChunkLoadError(error);
  // Derive recovering during render to avoid stale flash from effect-adjusted state.
  // Pure check: will this chunk error trigger a reload? (mirrors recoverFromChunkError's guard without side effects)
  const recovering = useMemo(() => {
    if (!isChunk) return false;
    if (typeof window === "undefined") return true;
    try {
      const raw = window.sessionStorage.getItem("gaia:chunk-recovery-at");
      if (raw === null) return true;
      const last = Number.parseInt(raw, 10);
      if (Number.isNaN(last)) return true;
      return Date.now() - last >= 10_000;
    } catch {
      return true;
    }
  }, [isChunk, error]);

  useEffect(() => {
    // Stale-asset chunk failure — reload once for fresh chunks. Skip Sentry:
    // this is an expected deploy-boundary condition, not an app fault.
    if (isChunk && recoverFromChunkError(error) === "reloading") return;
    if (isChunk) return;

    Sentry.captureException(error);
    posthog.captureException(error);
    // Full diagnostics go through Sentry/captureException above; error
    // message/stack can carry user content, so analytics only gets the stable
    // type and digest.
    trackEvent(ANALYTICS_EVENTS.ERROR_OCCURRED, {
      error_type: "global_error",
      digest: error.digest,
    });
  }, [error, isChunk]);

  return (
    <html lang="en">
      <body>
        {/* While a recovery reload is pending, render an empty document rather
        than flashing the error page for what is about to reload. Otherwise show
        `NextError` — the default Next.js error page (its type requires a
        `statusCode`; the App Router exposes none, so pass 0 for a generic
        message). */}
        {recovering ? null : <NextError statusCode={0} />}
      </body>
    </html>
  );
}
