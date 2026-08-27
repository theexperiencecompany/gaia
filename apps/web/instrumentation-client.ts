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

          // Drop noise thrown by crawlers, browser extensions, and third-party
          // scripts on our SEO pages. `ignoreErrors` / `denyUrls` handle the
          // benign message classes and extension URLs; `beforeSend` enforces
          // the bundle-frame allowlist those options cannot express, keeping
          // both sinks in agreement with PostHog's `before_send`.
          ignoreErrors: [...IGNORED_EXCEPTION_MESSAGES],
          denyUrls: [...EXTENSION_URL_PATTERNS],
          beforeSend: filterSentryEvent,
        });

        _captureRouterTransitionStart = Sentry.captureRouterTransitionStart;

        // Session Replay is a heavy integration (~100KB, ~760ms of script
        // execution) that provides no value before the user engages with the
        // page. Loading it during initial load dominated TBT on content pages,
        // so defer it to the first user interaction — error replay still works
        // for any session a real user actually participates in.
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

    // PostHog (any environment where the project token is set)
    const posthogProjectToken = process.env.NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN;
    if (!posthogProjectToken) {
      if (process.env.NODE_ENV === "development") {
        console.error(
          new Error(
            "NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN variable required by PostHog is missing or un-configured, this causes events to be silently missed. This error stops appearing once NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN is configured",
          ),
        );
      }
      return;
    }

    try {
      const { default: posthog } = await import("posthog-js");
      posthog.init(posthogProjectToken, {
        // Ingestion goes through the first-party /ingest proxy (see the
        // rewrites in next.config.mjs, which point it at
        // NEXT_PUBLIC_POSTHOG_HOST) so ad blockers cannot drop events.
        // ui_host names the real instance so the toolbar and "view in
        // PostHog" links resolve to the configured region, not the US default.
        api_host: "/ingest",
        ui_host: process.env.NEXT_PUBLIC_POSTHOG_HOST,
        defaults: "2025-05-24",
        capture_exceptions: true,
        debug: process.env.NODE_ENV === "development",
        // Drop the same crawler / extension / third-party exception noise
        // Sentry filters above so both sinks stay in agreement.
        before_send: filterExceptionBeforeSend,
      });
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
// Transitions that occur before Sentry loads (first few navigations after
// initial page load) will not be tracked — which is an acceptable tradeoff
// for eliminating ~630ms of TBT from the landing page.
export const onRouterTransitionStart: typeof SentryNs.captureRouterTransitionStart =
  (...args) => _captureRouterTransitionStart?.(...args);
