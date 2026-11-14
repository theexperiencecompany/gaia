import type { captureException } from "@sentry/nextjs";

/** Send an error to Sentry through its lazily loaded chunk, so an error boundary keeps Sentry off every page's first load. */
export function reportToSentry(
  ...args: Parameters<typeof captureException>
): void {
  void import("@/lib/observability/sentryClient").then((sentry) => {
    sentry.captureException(...args);
  });
}
