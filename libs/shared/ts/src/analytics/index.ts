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
 * processes. It has no DOM, no auto-capture, and no cookie handling. Suitable
 * for bots, the CLI, and any future server-side TypeScript consumer.
 *
 * The two SDKs are not interchangeable. Do not import this in the web app.
 *
 * ## Distinct ID strategy
 *
 * - Bots: `"<platform>:<platformUserId>"` (e.g. `"discord:123456789"`)
 * - CLI: `"cli:<machineId>"` where machineId is a stable UUID stored in
 *   `~/.gaia/analytics-id` (written on first run, never changes)
 *
 * These will not merge with web/backend events automatically. If cross-surface
 * stitching is needed in future, use PostHog's `alias` API.
 *
 * ## Event naming
 *
 * All events follow the project-wide `domain:action` convention used in
 * `apps/web/src/lib/analytics.ts` (e.g. `bot:message_received`,
 * `cli:command_started`). Event name constants live in `./events/`.
 */

import { PostHog } from "posthog-node";

export type { BotEventName } from "./events/bots";
export { BOT_EVENTS } from "./events/bots";
export type { CliEventName } from "./events/cli";
export { CLI_EVENTS } from "./events/cli";

export class Analytics {
  private readonly client: PostHog | null;

  constructor(apiKey: string | undefined) {
    if (!apiKey) {
      console.log("[analytics] POSTHOG_API_KEY not set — analytics disabled");
      this.client = null;
      return;
    }

    this.client = new PostHog(apiKey, {
      host: "https://us.i.posthog.com",
      flushAt: 20,
      flushInterval: 10_000,
    });
  }

  /**
   * Identifies a user and sets persistent properties on their PostHog profile.
   * Safe to call on every interaction — PostHog deduplicates by distinct_id.
   */
  identify(
    distinctId: string,
    properties?: Record<string, string | undefined>,
  ): void {
    if (!this.client) return;
    this.client.identify({ distinctId, properties });
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
   * Flushes all queued events and shuts down the PostHog client.
   * Must be called during graceful shutdown to avoid dropping events.
   */
  async shutdown(): Promise<void> {
    if (!this.client) return;
    await this.client.shutdown();
  }
}
