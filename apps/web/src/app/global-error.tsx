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

interface GlobalErrorProps {
  error: Error & { digest?: string };
}

export default function GlobalError({ error }: GlobalErrorProps) {
  // Keyed by the error instance: each new error remounts the view, so its
  // recovery state is initialized from that error instead of being synced in
  // an adjustment effect after the prop changes.
  return <GlobalErrorView key={error.digest ?? error.message} error={error} />;
}

function GlobalErrorView({ error }: GlobalErrorProps) {
  const isChunk = isChunkLoadError(error);
  // Blank while a stale-chunk recovery reload may be pending; flips to the
  // error page below if recovery declines to reload.
  const [recovering, setRecovering] = useState(isChunk);

  useEffect(() => {
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
