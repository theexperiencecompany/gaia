// This file configures the initialization of Sentry on the client.
// The added config here will be used whenever a users loads a page in their browser.
// https://docs.sentry.io/platforms/javascript/guides/nextjs/
//
// Both Sentry (~128KB) and PostHog (~47KB) are fully deferred via dynamic import
// so their chunks do not execute during the critical rendering path. Without
// deferral Sentry alone causes ~630ms of long tasks (TBT) at page load.

// Type-only import — zero runtime cost.
import type * as SentryNs from "@sentry/nextjs";
import {
  EXTENSION_URL_PATTERNS,
  filterExceptionBeforeSend,
  filterSentryEvent,
  IGNORED_EXCEPTION_MESSAGES,
} from "@/lib/observability/exception-filter";

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

          // Drop noise from crawlers, extensions, and third-party scripts on SEO
          // pages: `ignoreErrors`/`denyUrls` handle benign messages and extension
          // URLs; `beforeSend` enforces the bundle-frame allowlist those can't express, matching PostHog's `before_send`.
          ignoreErrors: [...IGNORED_EXCEPTION_MESSAGES],
          denyUrls: [...EXTENSION_URL_PATTERNS],
          beforeSend: filterSentryEvent,
        });

        _captureRouterTransitionStart = Sentry.captureRouterTransitionStart;

        // Session Replay is heavy (~100KB, ~760ms exec) with no value before
        // engagement — it dominated TBT on content pages, so defer to first
        // interaction; error replay still works for any session a user participates in.
        const loadReplay = () => {
          Sentry.lazyLoadIntegration("replayIntegration")
            .then((replayIntegration) => {
              const client = Sentry.getClient();
              if (client) client.addIntegration(replayIntegration());
            })
            .catch(() => {
              // Replay is best-effort: a load failure must not break the page.
            });
        };
        const interactionEvents = [
          "pointerdown",
          "keydown",
          "touchstart",
          "scroll",
        ] as const;
        const onFirstInteraction = () => {
          for (const ev of interactionEvents) {
            window.removeEventListener(ev, onFirstInteraction);
          }
          loadReplay();
        };
        for (const ev of interactionEvents) {
          window.addEventListener(ev, onFirstInteraction, { passive: true });
        }
      } catch {
        // Observability should never break the app.
      }
    }

    // PostHog (any environment where the project token is set). A missing
    // token is the normal local setup, not an error: analytics stays off and
    // nothing is logged, the same way Sentry above is skipped without a DSN.
    const posthogProjectToken = process.env.NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN;
    if (!posthogProjectToken) return;

    try {
      const { default: posthog } = await import("posthog-js");
      posthog.init(posthogProjectToken, {
        // Ingestion goes through the first-party /ingest proxy (see next.config.mjs
        // rewrites → NEXT_PUBLIC_POSTHOG_HOST) so ad blockers can't drop events;
        // ui_host resolves the toolbar/"view in PostHog" links to the configured region.
        api_host: "/ingest",
        ui_host: process.env.NEXT_PUBLIC_POSTHOG_HOST,
        defaults: "2025-05-24",
        capture_exceptions: true,
        debug: process.env.NODE_ENV === "development",
        // Session replay must be opted into in code — without an explicit
        // `session_recording` block the SDK sends events but no `$snapshot`
        // data, leaving Replay/Sessions empty.
        session_recording: {},
        // Drop the same crawler / extension / third-party exception noise
        // Sentry filters above so both sinks stay in agreement.
        before_send: filterExceptionBeforeSend,
      });

      // Anything captured while init was queued at idle was buffered, not
      // dropped — replay it now, in order; imported dynamically to keep analytics off the critical rendering path.
      const { flushPendingAnalytics } = await import("@/lib/analytics");
      flushPendingAnalytics();
    } catch {
      // Analytics should never break the app.
    }
  };

  if ("requestIdleCallback" in window) {
    requestIdleCallback(loadObservability, { timeout: 4000 });
  } else {
    setTimeout(loadObservability, 3000);
  }
}

// Next.js calls this hook at the start of every client-side navigation.
// Transitions before Sentry loads go untracked — an acceptable tradeoff for
// eliminating ~630ms of TBT from the landing page.
export const onRouterTransitionStart: typeof SentryNs.captureRouterTransitionStart =
  (...args) => _captureRouterTransitionStart?.(...args);
