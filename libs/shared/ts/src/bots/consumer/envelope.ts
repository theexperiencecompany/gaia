/**
 * Wire contract for messages the backend publishes to a platform's outbound
 * queue. Mirrors ``apps/api/app/schemas/outbound.py``.
 *
 * The consumer validates each message against this schema at the queue boundary
 * so a malformed or renamed payload is rejected to the DLQ with a clear reason,
 * rather than failing deep in the platform send path with an undefined field.
 *
 * The schema is the single source of truth; consumers derive the static type via
 * ``z.infer<typeof outboundMessageEnvelopeSchema>`` so runtime validation and the
 * static type cannot drift apart.
 */

import { z } from "zod";

export const outboundMessageEnvelopeSchema = z.object({
  /** Unique id (idempotency + tracing). */
  id: z.string().min(1),
  /** Target platform — informational; each queue is already platform-specific. */
  platform: z.string().min(1),
  /** Platform-native destination id (wa_id, Discord/Telegram/Slack user id). */
  destination_id: z.string().min(1),
  /** Raw CommonMark message body. */
  text: z.string().min(1),
  /** ISO-8601 enqueue timestamp. */
  enqueued_at: z.string(),
});
