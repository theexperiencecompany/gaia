/**
 * RabbitMQ outbound-delivery topology — the per-platform queues the bots
 * consume backend-originated messages from.
 *
 * Kept byte-identical to ``apps/api/app/constants/outbound.py`` — RabbitMQ
 * rejects a redeclare whose arguments differ from the existing queue.
 */

import type { PlatformName } from "../types";

/** Dead-letter exchange every outbound work queue routes failed messages to. */
export const OUTBOUND_DLX = "outbound.dlx";

/** Per-platform durable work queues. */
export const OUTBOUND_QUEUES: Record<PlatformName, string> = {
  whatsapp: "outbound.whatsapp",
  slack: "outbound.slack",
  telegram: "outbound.telegram",
  discord: "outbound.discord",
};

/** Dead-letter queue name for a work queue. */
export const dlqName = (queue: string): string => `${queue}.dlq`;

/** Declaration arguments for a work queue: dead-letter to the shared DLX. */
export const workQueueArguments = (queue: string): Record<string, string> => ({
  "x-dead-letter-exchange": OUTBOUND_DLX,
  "x-dead-letter-routing-key": dlqName(queue),
});
