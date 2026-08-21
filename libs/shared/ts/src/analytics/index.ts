/**
 * Server-side PostHog analytics client for GAIA Node.js consumers.
 *
 * ## Why this exists alongside the web app's analytics
 *
 * The web app (`apps/web`) uses `posthog-js` — a browser SDK that runs in the
 * client, auto-captures pageviews, reads cookies, and ships events directly
 * from the user's browser. It is initialized in `instrumentation-client.ts`
 * and wrapped in `src/lib/analytics.ts`.
 *
 * This module uses `posthog-node` — a server-side SDK designed for Node.js
 * processes. It has no DOM, no auto-capture, and no cookie handling. Used by
 * the GAIA bots and any future server-side TypeScript consumer.
 *
 * The two SDKs are not interchangeable. Do not import this in the web app.
 *
 * ## Distinct ID strategy
 *
 * - Bots: `"<platform>:<platformUserId>"` (e.g. `"discord:123456789"`)
 *
 * These will not merge with web/backend events automatically. If cross-surface
 * stitching is needed in future, use PostHog's `alias` API.
 *
 * ## Event naming
 *
 * All events follow the project-wide `domain:action` convention used in
 * `apps/web/src/lib/analytics.ts` (e.g. `bot:message_received`). Event
 * name constants live in `./events/`.
 */

import { PostHog } from "posthog-node";

export type { BotEventName } from "./events/bots";
export { BOT_EVENTS } from "./events/bots";

/** PostHog US cloud — the region GAIA ingests into unless POSTHOG_HOST says otherwise. */
const DEFAULT_POSTHOG_HOST = "https://us.i.posthog.com";

/**
 * A PostHog client paired with the identity its events belong to.
 *
 * Resolving a bot user's distinct_id costs a link lookup, so it is done once by
 * the adapter and handed to helpers rather than recomputed — and passing the
 * pair together makes it impossible to capture an event without deciding whose
 * it is, which is how the `<platform>:<id>` ghost profiles happened.
 */
export interface AnalyticsContext {
  client: Analytics;
  /** The GAIA user id when the account is linked, else `"<platform>:<platformUserId>"`. */
  distinctId: string;
}

export class Analytics {
  private readonly client: PostHog | null;

  constructor(apiKey: string | undefined, host?: string) {
    if (!apiKey) {
      this.client = null;
      return;
    }

    this.client = new PostHog(apiKey, {
      // Configurable for the same reason the web app's /ingest rewrites are:
      // pinning the region here would ship an EU or self-hosted deployment's
      // data to the US cloud, across a data-residency boundary.
      host: host || process.env.POSTHOG_HOST || DEFAULT_POSTHOG_HOST,
      flushAt: 20,
      flushInterval: 10_000,
      // Do not attach $geoip_* properties from request IP. For a bot runtime
      // that already tags events with a platform handle, IP-based geo is
      // both redundant and privacy-sensitive.
      disableGeoip: true,
    });
  }

  /**
   * Captures a named event for the given distinct_id.
   * All extra properties are merged with the event payload.
   */
  capture(
    distinctId: string,
    event: string,
    properties?: Record<string, unknown>,
  ): void {
    if (!this.client) return;
    this.client.capture({ distinctId, event, properties });
  }

  /**
   * Merges `previousId`'s profile into `distinctId`'s.
   *
   * A bot user is anonymous until they link their GAIA account, so their early
   * events are keyed `"<platform>:<platformUserId>"`. Aliasing at link time
   * folds that history into the stable GAIA profile instead of leaving a second
   * ghost person behind — without it, cross-surface funnels (bot -> web) never
   * join up.
   */
  alias(previousId: string, distinctId: string): void {
    if (!this.client) return;
    // Argument order is the `$create_alias` wire convention, which is inverted
    // from how it reads: the OLD id goes in `distinctId` and the NEW one in
    // `alias`. Verified against both SDKs — posthog-python's
    // `alias(previous_id, distinct_id)` emits
    // `{distinct_id: previous_id, alias: distinct_id}`, and posthog-node's own
    // docstring example passes the anonymous id as `distinctId`.
    this.client.alias({ distinctId: previousId, alias: distinctId });
  }

  /**
   * Flushes all queued events and shuts down the PostHog client.
   * Must be called during graceful shutdown to avoid dropping events.
   */
  async shutdown(): Promise<void> {
    if (!this.client) return;
    await this.client.shutdown();
  }
}
