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

/**
 * Queue-name prefix — mirrors ``OUTBOUND_QUEUE_PREFIX`` in
 * ``apps/api/app/constants/outbound.py``. Both sides build ``outbound.<platform>``
 * from it, so only the platform token can differ across the two files.
 */
const OUTBOUND_QUEUE_PREFIX = "outbound.";

/**
 * Per-platform durable work queues. The ``Record<PlatformName, …>`` type makes
 * this exhaustive — adding a PlatformName fails to compile until it is listed
 * here — and each name is derived from the shared prefix.
 */
export const OUTBOUND_QUEUES: Record<PlatformName, string> = {
  whatsapp: `${OUTBOUND_QUEUE_PREFIX}whatsapp`,
  slack: `${OUTBOUND_QUEUE_PREFIX}slack`,
  telegram: `${OUTBOUND_QUEUE_PREFIX}telegram`,
  discord: `${OUTBOUND_QUEUE_PREFIX}discord`,
};

/** Dead-letter queue name for a work queue. */
export const dlqName = (queue: string): string => `${queue}.dlq`;

/** Declaration arguments for a work queue: dead-letter to the shared DLX. */
export const workQueueArguments = (queue: string): Record<string, string> => ({
  "x-dead-letter-exchange": OUTBOUND_DLX,
  "x-dead-letter-routing-key": dlqName(queue),
});
