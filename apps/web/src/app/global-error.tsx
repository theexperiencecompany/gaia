"use client";

// This file is the Next.js global error boundary for the App Router.
// Placing it in the `app/` directory automatically applies it to the entire
// application, so you don't need to manually wrap your pages or layouts.

import * as Sentry from "@sentry/nextjs";
import NextError from "next/error";
import { useEffect } from "react";

import { trackError } from "@/lib/analytics";

export default function GlobalError({
  error,
}: {
  error: Error & { digest?: string };
}) {
  useEffect(() => {
    Sentry.captureException(error);
    trackError("global_error", error, {
      digest: error.digest,
    });
  }, [error]);

  return (
    <html lang="en">
      <body>
        {/* `NextError` is the default Next.js error page component. Its type
        definition requires a `statusCode` prop. However, since the App Router
        does not expose status codes for errors, we simply pass 0 to render a
        generic error message. */}
        <NextError statusCode={0} />
      </body>
    </html>
  );
}
