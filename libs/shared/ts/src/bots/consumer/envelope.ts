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

/**
 * A file the bot should deliver. Bytes are NOT inlined — the bot fetches the
 * artifact from the backend (bot-authenticated) and uploads it to the platform.
 */
export const outboundAttachmentSchema = z.object({
  conversation_id: z.string().min(1),
  /**
   * Artifact path relative to the session's artifacts/ dir. Rejected at the
   * queue boundary if absolute or containing a `..` segment, so a malformed
   * envelope can't turn into arbitrary-file access in the artifact fetch.
   */
  path: z
    .string()
    .min(1)
    .refine((p) => !p.startsWith("/") && !p.split("/").includes(".."), {
      message: "path must be relative to artifacts/ (no leading '/' or '..')",
    }),
  filename: z.string().min(1),
  content_type: z.string().nullish(),
  caption: z.string().nullish(),
});

export const outboundMessageEnvelopeSchema = z
  .object({
    /** Unique id (idempotency + tracing). */
    id: z.string().min(1),
    /** Target platform — informational; each queue is already platform-specific. */
    platform: z.string().min(1),
    /** Platform-native destination id (wa_id, Discord/Telegram/Slack user id). */
    destination_id: z.string().min(1),
    /** Raw CommonMark message body. Optional when an attachment is present. */
    text: z.string().min(1).nullish(),
    /** A file to deliver (PDF/docx/etc.) — optional. */
    attachment: outboundAttachmentSchema.nullish(),
    /** ISO-8601 enqueue timestamp. */
    enqueued_at: z.string(),
  })
  .refine((e) => Boolean(e.text) || Boolean(e.attachment), {
    message: "envelope requires text or attachment",
  });

export type OutboundAttachment = z.infer<typeof outboundAttachmentSchema>;
