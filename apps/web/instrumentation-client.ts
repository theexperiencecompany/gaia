// This file configures the initialization of Sentry on the client.
// The added config here will be used whenever a users loads a page in their browser.
// https://docs.sentry.io/platforms/javascript/guides/nextjs/

import * as Sentry from "@sentry/nextjs";
import posthog from "posthog-js";

if (process.env.NODE_ENV === "production") {
  Sentry.init({
    dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,

    // Replay integration is lazy-loaded below after the page settles — it's ~100KB
    // gzipped and shouldn't block LCP/TTI.
    integrations: [],

    // Define how likely traces are sampled. Adjust this value in production, or use tracesSampler for greater control.
    tracesSampleRate: 1,
    // Enable logs to be sent to Sentry
    enableLogs: true,

    // Define how likely Replay events are sampled.
    // This sets the sample rate to be 10%. You may want this to be 100% while
    // in development and sample at a lower rate in production
    replaysSessionSampleRate: 0.1,

    // Define how likely Replay events are sampled when an error occurs.
    replaysOnErrorSampleRate: 1.0,

    // Setting this option to true will print useful information to the console while you're setting up Sentry.
    debug: false,
  });

  // Defer replay integration until the browser is idle so it doesn't compete
  // with hydration / critical rendering.
  const loadReplay = () => {
    Sentry.lazyLoadIntegration("replayIntegration")
      .then((replayIntegration) => {
        const client = Sentry.getClient();
        if (client) client.addIntegration(replayIntegration());
      })
      .catch(() => {
        // Swallow — replay is best-effort, we don't want to surface network errors.
      });
  };
  if (typeof window !== "undefined") {
    if ("requestIdleCallback" in window) {
      (
        window as Window & {
          requestIdleCallback: (
            cb: () => void,
            opts?: { timeout: number },
          ) => number;
        }
      ).requestIdleCallback(loadReplay, { timeout: 4000 });
    } else {
      setTimeout(loadReplay, 3000);
    }
  }
}

export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;

if (process.env.NEXT_PUBLIC_POSTHOG_KEY) {
  posthog.init(process.env.NEXT_PUBLIC_POSTHOG_KEY, {
    api_host: "/ingest",
    ui_host: "https://us.posthog.com",
    defaults: "2025-05-24",
    capture_exceptions: true,
    debug: process.env.NODE_ENV === "development",
  });
}
