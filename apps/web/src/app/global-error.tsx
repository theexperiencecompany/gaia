"use client";

// This file is the Next.js global error boundary for the App Router.
// Placing it in the `app/` directory automatically applies it to the entire
// application, so you don't need to manually wrap your pages or layouts.

import * as Sentry from "@sentry/nextjs";
import NextError from "next/error";
import posthog from "posthog-js";
import { useEffect, useState } from "react";

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
  const [recovering, setRecovering] = useState(isChunk);

  useEffect(() => {
    // Stale-asset chunk failure — reload once for fresh chunks. Skip Sentry:
    // this is an expected deploy-boundary condition, not an app fault.
    if (isChunk && recoverFromChunkError(error) === "reloading") return;
    setRecovering(false);
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
