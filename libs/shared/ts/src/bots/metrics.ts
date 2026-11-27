/**
 * Prometheus series every bot exports on `GET /metrics` (see {@link BotServer}).
 * Recorded only by `BaseBotAdapter` and the shared outbound consumer, so all
 * five bots read one definition.
 */
import { Counter, collectDefaultMetrics, Gauge, Registry } from "prom-client";
import { OUTBOUND_QUEUES } from "./consumer/topology";
import type { PlatformName } from "./types";

export const BOT_OUTCOME = {
  OK: "ok",
  FAILED: "failed",
} as const;

export type BotOutcome = (typeof BOT_OUTCOME)[keyof typeof BOT_OUTCOME];

// OUTBOUND_QUEUES is a Record<PlatformName, …>, so its keys are exactly the platforms.
const PLATFORMS = Object.keys(OUTBOUND_QUEUES) as PlatformName[];
const OUTCOMES = Object.values(BOT_OUTCOME);

export const botRegistry = new Registry();
collectDefaultMetrics({ register: botRegistry });

const inboundTotal = new Counter({
  name: "gaia_bot_inbound_total",
  help: "Inbound platform messages handled, by outcome.",
  labelNames: ["platform", "outcome"] as const,
  registers: [botRegistry],
});

const outboundTotal = new Counter({
  name: "gaia_bot_outbound_total",
  help: "Outbound deliveries that ended, by outcome.",
  labelNames: ["platform", "outcome"] as const,
  registers: [botRegistry],
});

const platformConnected = new Gauge({
  name: "gaia_bot_platform_connected",
  help: "1 while the platform connection is established, 0 otherwise.",
  labelNames: ["platform"] as const,
  registers: [botRegistry],
});

// Zero at load so the first failure is an increase and absence means the metric is gone.
// The connection gauge is not pre-created: a webhook platform has no connection to report.
for (const platform of PLATFORMS) {
  for (const outcome of OUTCOMES) {
    inboundTotal.inc({ platform, outcome }, 0);
    outboundTotal.inc({ platform, outcome }, 0);
  }
}

export function recordInbound(
  platform: PlatformName,
  outcome: BotOutcome,
): void {
  inboundTotal.inc({ platform, outcome });
}

export function recordOutbound(
  platform: PlatformName,
  outcome: BotOutcome,
): void {
  outboundTotal.inc({ platform, outcome });
}

export function setPlatformConnected(
  platform: PlatformName,
  connected: boolean,
): void {
  platformConnected.set({ platform }, connected ? 1 : 0);
}
