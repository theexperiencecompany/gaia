// This file configures the initialization of Sentry on the client.
// The added config here will be used whenever a users loads a page in their browser.
// https://docs.sentry.io/platforms/javascript/guides/nextjs/
//
// Both Sentry (~128KB) and PostHog (~47KB) are fully deferred via dynamic import
// so their chunks do not execute during the critical rendering path. Without
// deferral Sentry alone causes ~630ms of long tasks (TBT) at page load.

// Type-only import — zero runtime cost.
import type * as SentryNs from "@sentry/nextjs";

// Holds the real Sentry function once the module loads at idle time.
let _captureRouterTransitionStart:
  | typeof SentryNs.captureRouterTransitionStart
  | null = null;

if (typeof window !== "undefined") {
  const loadObservability = async () => {
    // Sentry (production only)
    if (process.env.NODE_ENV === "production") {
      try {
        const Sentry = await import("@sentry/nextjs");

        Sentry.init({
          dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,

          // Replay integration is lazy-loaded below after init — ~100KB gzipped.
          integrations: [],

          tracesSampleRate: 1,
          enableLogs: true,
          replaysSessionSampleRate: 0.1,
          replaysOnErrorSampleRate: 1.0,
          debug: false,
        });

        _captureRouterTransitionStart = Sentry.captureRouterTransitionStart;

        // Replay is best-effort — don't surface network errors to users.
        Sentry.lazyLoadIntegration("replayIntegration")
          .then((replayIntegration) => {
            const client = Sentry.getClient();
            if (client) client.addIntegration(replayIntegration());
          })
          .catch(() => {});
      } catch {
        // Observability should never break the app.
      }
    }

    // PostHog (any environment where the key is set)
    if (process.env.NEXT_PUBLIC_POSTHOG_KEY) {
      try {
        const { default: posthog } = await import("posthog-js");
        posthog.init(process.env.NEXT_PUBLIC_POSTHOG_KEY, {
          api_host: "/ingest",
          ui_host: "https://us.posthog.com",
          defaults: "2025-05-24",
          capture_exceptions: true,
          debug: process.env.NODE_ENV === "development",
        });
      } catch {
        // Analytics should never break the app.
      }
    }
  };

  if ("requestIdleCallback" in window) {
    requestIdleCallback(loadObservability, { timeout: 4000 });
  } else {
    setTimeout(loadObservability, 3000);
  }
}

// Next.js calls this hook at the start of every client-side navigation.
// Transitions that occur before Sentry loads (first few navigations after
// initial page load) will not be tracked — which is an acceptable tradeoff
// for eliminating ~630ms of TBT from the landing page.
export const onRouterTransitionStart: typeof SentryNs.captureRouterTransitionStart =
  (...args) => _captureRouterTransitionStart?.(...args);
