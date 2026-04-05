/**
 * CLI analytics instance.
 *
 * Uses posthog-node — a server-side SDK designed for Node.js processes.
 * See libs/shared/ts/src/analytics/index.ts for the distinction between
 * this and the web app's posthog-js setup.
 *
 * POSTHOG_API_KEY is optional — analytics is a no-op when absent.
 */

import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { PostHog } from "posthog-node";

export const CLI_EVENTS = {
  COMMAND_STARTED: "cli:command_started",
  COMMAND_COMPLETED: "cli:command_completed",
  COMMAND_FAILED: "cli:command_failed",
  SETUP_COMPLETED: "cli:setup_completed",
  SERVICES_STARTED: "cli:services_started",
} as const;

function getOrCreateCliDistinctId(): string {
  const dir = path.join(os.homedir(), ".gaia");
  const file = path.join(dir, "analytics-id");
  if (fs.existsSync(file)) {
    return fs.readFileSync(file, "utf-8").trim();
  }
  const id = `cli:${crypto.randomUUID()}`;
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(file, id, "utf-8");
  return id;
}

export const CLI_DISTINCT_ID = getOrCreateCliDistinctId();

class Analytics {
  private readonly client: PostHog | null;

  constructor(apiKey: string | undefined) {
    if (!apiKey) {
      this.client = null;
      return;
    }
    this.client = new PostHog(apiKey, {
      host: "https://us.i.posthog.com",
      flushAt: 20,
      flushInterval: 10_000,
    });
  }

  capture(event: string, properties?: Record<string, unknown>): void {
    if (!this.client) return;
    this.client.capture({
      distinctId: CLI_DISTINCT_ID,
      event,
      properties,
    });
  }

  async shutdown(): Promise<void> {
    if (!this.client) return;
    await this.client.shutdown();
  }
}

export const analytics = new Analytics(process.env.POSTHOG_API_KEY);
